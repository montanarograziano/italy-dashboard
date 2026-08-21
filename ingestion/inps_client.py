"""Thin async client for the INPS StatKit Data Browser hub middleware.

INPS (Istituto Nazionale della Previdenza Sociale) publishes its statistical
observatories (pensions, private-sector employees, companies, employment
policies incl. NASPI/DIS-COLL) only through this JSON middleware: the classic
SDMX-REST NSI Web Service is blocked by a WAF for external access.

Endpoint reference: https://opendata.inps.it/databrowser/api/core

VERIFICATION NOTE: this client is written against the documented protocol and
the actual released implementation of https://github.com/ondata/opensdmx
(docs/inps/middleware-api.md, src/opensdmx/inps.py), not against a live INPS
response — opendata.inps.it was unreachable (TCP connect timeout) from this
environment while writing it, while inps.it's main site connected fine, so the
block looks scoped to this API subdomain rather than a real INPS outage.
Re-run the offline tests' fixtures against one real response before trusting
this for the dashboard's snapshot.

Design notes:
- Mirrors ingestion/sdmx_client.py's shape (async context manager, injectable
  transport, retries with backoff) but talks JSON (GET + POST), not SDMX-ML.
- The middleware has NO server-side data filter: `download/csv` always
  returns the whole dataflow regardless of any criteria body, and ignores a
  start/end period window entirely. `get_data_csv` therefore accepts (and
  ignores) `key`/`start_period`/`end_period` purely so callers written against
  IstatClient's signature (ingestion/fetch.py's fetch_dataset) work unchanged;
  narrowing has to happen client-side, in ingestion/fetch.py's `filters`.
- `get_codelist` covers PartialCodelists (per-dimension available values +
  human-readable names), including the hierarchical case (e.g. TERRITORIO):
  a value flagged `isSelectable: false` is a parent whose children are
  fetched with a follow-up POST, per docs/inps/middleware-api.md.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import httpx2

logger = logging.getLogger(__name__)

BASE_URL = "https://opendata.inps.it/databrowser/api/core"
AGENCY = "INPS"

# code (SPA URL) -> numeric nodeId. The middleware requires the id; passing
# the code silently falls back to another node, so this map is the only
# correct way to address a node.
NODES = {
    "politiche_occupazionali": 1,  # NASPI/DIS-COLL, other employment policies
    "pensioni": 2,
    "dipendenti": 3,
    "imprese": 4,
}

CSV_ACCEPT = "application/vnd.sdmx.data+csv"

DEFAULT_TIMEOUT = httpx2.Timeout(300.0, connect=30.0, read=120.0)
MAX_RETRIES = 3
RETRY_BACKOFF_S = 5.0


class InpsError(RuntimeError):
    """Raised when the INPS hub middleware returns an unusable response."""


@dataclass(frozen=True)
class Dataflow:
    flow_id: str
    node: int
    version: str
    name: str


def _dataset_id(flow_id: str, version: str) -> str:
    """`{agency},{flow},{version}` — the hub's dataset identifier."""
    return f"{AGENCY},{flow_id},{version}"


def _bare_flow_id(full_identifier: str) -> str:
    """`INPS,{flow},1.0` -> `{flow}`."""
    parts = full_identifier.split(",")
    return parts[1] if len(parts) >= 2 else full_identifier


def _catalog_dataset_ids(catalog: dict[str, Any]) -> list[str]:
    """Every dataset identifier in a node catalog, recursing over categories."""
    ids: list[str] = []

    def walk(cat: dict[str, Any]) -> None:
        ids.extend(cat.get("datasetIdentifiers") or [])
        for child in cat.get("childrenCategories") or []:
            walk(child)

    for group in catalog.get("categoryGroups") or []:
        for top in group.get("categories") or []:
            walk(top)
    return ids


def _leaf_labels(catalog: dict[str, Any]) -> dict[str, str]:
    """Map each bare flow id to the label of its leaf category (title fallback)."""
    labels: dict[str, str] = {}

    def walk(cat: dict[str, Any]) -> None:
        label = cat.get("label", "")
        for full_id in cat.get("datasetIdentifiers") or []:
            labels.setdefault(_bare_flow_id(full_id), label)
        for child in cat.get("childrenCategories") or []:
            walk(child)

    for group in catalog.get("categoryGroups") or []:
        for top in group.get("categories") or []:
            walk(top)
    return labels


class InpsClient:
    """Async context-manager client for the INPS hub middleware."""

    def __init__(
        self,
        base_url: str = BASE_URL,
        timeout: httpx2.Timeout = DEFAULT_TIMEOUT,
        transport: httpx2.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport  # injectable for tests (httpx2.MockTransport)
        self._client: httpx2.AsyncClient | None = None
        # df_id -> (node, version), built lazily by list_dataflows().
        self._index: dict[str, tuple[int, str]] = {}

    async def __aenter__(self) -> InpsClient:
        self._client = httpx2.AsyncClient(
            timeout=self._timeout, follow_redirects=True, transport=self._transport
        )
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx2.AsyncClient:
        if self._client is None:
            raise RuntimeError("InpsClient must be used as an async context manager")
        return self._client

    async def _request_json(
        self, path: str, *, method: str = "GET", json_body: Any = None
    ) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = await self.client.request(
                    method,
                    url,
                    json=json_body if method == "POST" else None,
                    headers={"Accept": "application/json"},
                )
                if resp.status_code == 404:
                    raise InpsError(f"Not found (404): {url}")
                if resp.status_code >= 400:
                    raise InpsError(f"HTTP {resp.status_code} from {url}: {resp.text[:500]!r}")
                return resp.json()
            except (httpx2.TransportError, httpx2.TimeoutException) as exc:
                last_error = exc
                if attempt < MAX_RETRIES:
                    wait = RETRY_BACKOFF_S * attempt
                    logger.warning(
                        "Attempt %d/%d failed for %s (%s); retrying in %.0fs",
                        attempt,
                        MAX_RETRIES,
                        url,
                        exc,
                        wait,
                    )
                    await asyncio.sleep(wait)
        raise InpsError(f"Failed after {MAX_RETRIES} attempts: {url}") from last_error

    async def _catalog(self, node: int) -> dict[str, Any]:
        return await self._request_json(f"nodes/{node}/catalog")

    async def list_dataflows(self) -> list[Dataflow]:
        """All dataflows across every node, and (re)build the df_id -> node index.

        A flow id that somehow appears in more than one node keeps its first
        node and logs a warning rather than silently overwriting the index.
        """
        flows: list[Dataflow] = []
        index: dict[str, tuple[int, str]] = {}
        seen: set[str] = set()
        for node in NODES.values():
            catalog = await self._catalog(node)
            title_map = {
                _bare_flow_id(fid): (meta or {}).get("title")
                for fid, meta in (catalog.get("datasetMap") or {}).items()
                if isinstance(meta, dict)
            }
            leaf_label = _leaf_labels(catalog)
            for full_id in _catalog_dataset_ids(catalog):
                flow_id = _bare_flow_id(full_id)
                parts = full_id.split(",")
                version = parts[2] if len(parts) >= 3 else "1.0"
                if flow_id in seen:
                    logger.warning(
                        "INPS dataflow %r appears in multiple nodes; keeping node %s",
                        flow_id,
                        index[flow_id][0],
                    )
                    continue
                seen.add(flow_id)
                index[flow_id] = (node, version)
                name = title_map.get(flow_id) or leaf_label.get(flow_id) or flow_id
                flows.append(Dataflow(flow_id=flow_id, node=node, version=version, name=name))
        if not flows:
            raise InpsError("Dataflow list came back empty across every node")
        self._index = index
        return flows

    async def search_dataflows(self, keyword: str) -> list[Dataflow]:
        """Case-insensitive match on the flow id or its display name."""
        keyword_lower = keyword.lower()
        return [
            f
            for f in await self.list_dataflows()
            if keyword_lower in f.flow_id.lower() or keyword_lower in f.name.lower()
        ]

    async def _resolve(self, flow_id: str) -> tuple[int, str]:
        if flow_id not in self._index:
            await self.list_dataflows()
        entry = self._index.get(flow_id)
        if entry is None:
            raise InpsError(f"INPS dataflow {flow_id!r} not found in any node catalog")
        return entry

    async def get_dimensions(self, flow_id: str) -> list[str]:
        """Ordered (non-time) dimension IDs of a dataflow's structure.

        Unlike ISTAT, this order is NOT a server-side filter key: the hub has
        no dotted-key syntax, every filter is applied client-side after a full
        download. The order is still useful documentation of what the
        dataflow is sliced by.
        """
        node, version = await self._resolve(flow_id)
        ds_id = _dataset_id(flow_id, version)
        structure = await self._request_json(f"nodes/{node}/datasets/{ds_id}/structure")
        time_dim = structure.get("timeDimension")
        dims = [
            c["id"]
            for c in (structure.get("criteria") or [])
            if c.get("id") and c["id"] != time_dim
        ]
        if not dims:
            raise InpsError(f"No dimensions found for {flow_id} — unexpected response shape")
        return dims

    async def _partial_codelist(
        self, node: int, ds_id: str, dim_id: str, parent: str | None
    ) -> list[dict[str, Any]]:
        """POST PartialCodelists/{dim} and return its raw value list.

        `parent` selects the children of a hierarchical parent code; `None`
        requests the root level (body `[]`).
        """
        body: list[dict[str, Any]] = (
            [] if parent is None else [{"id": dim_id, "values": [{"id": parent}]}]
        )
        payload = await self._request_json(
            f"nodes/{node}/datasets/{ds_id}/PartialCodelists/{dim_id}",
            method="POST",
            json_body=body,
        )
        for crit in payload.get("criteria") or []:
            if crit.get("id") == dim_id:
                return crit.get("values") or []
        return []

    async def get_codelist(self, flow_id: str, dimension_id: str) -> dict[str, str]:
        """Return `{code: name}` for one dimension's selectable values.

        Handles hierarchical dimensions (e.g. TERRITORIO): a value flagged
        `isSelectable: false` is a parent node, so its children are fetched
        and the parent itself is dropped. A `seen` guard stops cycles/repeats.
        """
        node, version = await self._resolve(flow_id)
        ds_id = _dataset_id(flow_id, version)
        codes: dict[str, str] = {}
        seen: set[str] = set()

        async def descend(parent: str | None) -> None:
            for value in await self._partial_codelist(node, ds_id, dimension_id, parent):
                vid = value.get("id")
                if not vid or vid in seen:
                    continue
                seen.add(vid)
                if value.get("isSelectable", True):
                    codes[vid] = value.get("name") or vid
                else:
                    await descend(vid)

        await descend(None)
        return codes

    async def get_data_csv(
        self,
        flow_id: str,
        key: str = "ALL",
        start_period: str | None = None,
        end_period: str | None = None,
    ) -> bytes:
        """Download the whole dataflow as SDMX-CSV.

        `key`/`start_period`/`end_period` are accepted for signature
        compatibility with IstatClient.get_data_csv (ingestion/fetch.py calls
        both the same way) but are IGNORED: the middleware has no server-side
        filter and always returns everything, narrowing has to happen in
        ingestion/fetch.py's `filters` after download, same as ISTAT dataflows
        that need client-side filtering.
        """
        node, version = await self._resolve(flow_id)
        ds_id = _dataset_id(flow_id, version)
        url = f"{self.base_url}/nodes/{node}/datasets/{ds_id}/download/csv"
        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = await self.client.post(url, json=[], headers={"Accept": CSV_ACCEPT})
                if resp.status_code == 404:
                    raise InpsError(f"Not found (404): {url} — check the dataflow ID")
                if resp.status_code >= 400:
                    raise InpsError(f"HTTP {resp.status_code} from {url}: {resp.text[:500]!r}")
                raw = resp.content
                head = raw[:200].lstrip()
                if head.startswith(b"{") or head.startswith(b"["):
                    raise InpsError(
                        f"Expected CSV for {flow_id} but got JSON — the hub may have "
                        f"returned an error body with HTTP 200. First bytes: {head[:120]!r}"
                    )
                return raw
            except (httpx2.TransportError, httpx2.TimeoutException) as exc:
                last_error = exc
                if attempt < MAX_RETRIES:
                    wait = RETRY_BACKOFF_S * attempt
                    logger.warning(
                        "Attempt %d/%d failed for %s (%s); retrying in %.0fs",
                        attempt,
                        MAX_RETRIES,
                        url,
                        exc,
                        wait,
                    )
                    await asyncio.sleep(wait)
        raise InpsError(f"Failed after {MAX_RETRIES} attempts: {url}") from last_error
