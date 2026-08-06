"""Thin async client for the ISTAT SDMX REST API.

Endpoint reference: https://esploradati.istat.it/SDMXWS/rest
Docs (Italian): https://ondata.github.io/guida-api-istat/

Design notes:
- No wrapper library: the deprecated `istatapi` package points at the
  decommissioned sdmx.istat.it endpoint. This client targets the current one
  and is ~150 lines we fully control.
- Uses httpx2 (the Pydantic-stewarded continuation of httpx), async so
  multiple datasets refresh concurrently.
- Data is requested as SDMX-CSV (Accept header). Structure/discovery calls
  return SDMX-ML (XML), parsed with the standard library.
"""

from __future__ import annotations

import asyncio
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx2

logger = logging.getLogger(__name__)

BASE_URL = "https://esploradati.istat.it/SDMXWS/rest"
AGENCY = "IT1"

# SDMX-CSV with human-readable labels alongside codes.
CSV_ACCEPT = "application/vnd.sdmx.data+csv;version=1.0.0;labels=both"
XML_ACCEPT = "application/vnd.sdmx.structure+xml;version=2.1"

# read= is the max gap BETWEEN chunks while streaming, not the whole download,
# so a slow-but-flowing extraction is fine; a server that goes silent times out.
DEFAULT_TIMEOUT = httpx2.Timeout(300.0, connect=30.0, read=120.0)
MAX_RETRIES = 3
RETRY_BACKOFF_S = 5.0
PROGRESS_EVERY_BYTES = 10 * 1024 * 1024  # log every 10 MB while downloading


class SdmxError(RuntimeError):
    """Raised when the ISTAT API returns an unusable response."""


@dataclass(frozen=True)
class Dataflow:
    flow_id: str
    agency: str
    version: str
    name: str  # preferred display name (English when available)
    all_names: tuple[str, ...] = ()  # every language, for keyword search


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


class IstatClient:
    """Async context-manager client for ISTAT SDMX REST."""

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

    async def __aenter__(self) -> IstatClient:
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
            raise RuntimeError("IstatClient must be used as an async context manager")
        return self._client

    async def _get(self, path: str, accept: str, params: dict | None = None) -> bytes:
        """GET with retries, streaming the body and logging download progress.

        Large ISTAT extractions ("ALL" keys) can take minutes server-side and
        return hundreds of MB — progress logs make the difference between
        "working" and "looks stuck".
        """
        url = f"{self.base_url}/{path.lstrip('/')}"
        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async with self.client.stream(
                    "GET", url, headers={"Accept": accept}, params=params
                ) as resp:
                    if resp.status_code == 404:
                        raise SdmxError(f"Not found (404): {url} — check the dataflow ID")
                    if resp.status_code >= 400:
                        body = (await resp.aread())[:500]
                        raise SdmxError(f"HTTP {resp.status_code} from {url}: {body!r}")
                    chunks: list[bytes] = []
                    received = 0
                    next_report = PROGRESS_EVERY_BYTES
                    async for chunk in resp.aiter_bytes():
                        chunks.append(chunk)
                        received += len(chunk)
                        if received >= next_report:
                            logger.info(
                                "still downloading %s — %.0f MB so far", url, received / 1e6
                            )
                            next_report += PROGRESS_EVERY_BYTES
                    return b"".join(chunks)
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
        raise SdmxError(f"Failed after {MAX_RETRIES} attempts: {url}") from last_error

    async def list_dataflows(self) -> list[Dataflow]:
        """All available dataflows (datasets) published by ISTAT."""
        raw = await self._get(f"dataflow/{AGENCY}/ALL/latest", accept=XML_ACCEPT)
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise SdmxError(
                "Could not parse dataflow XML — the API may be down or the "
                f"endpoint may have changed. First bytes: {raw[:200]!r}"
            ) from exc

        flows: list[Dataflow] = []
        for el in root.iter():
            if _strip_ns(el.tag) != "Dataflow":
                continue
            name = ""
            all_names: list[str] = []
            for child in el:
                if _strip_ns(child.tag) == "Name":
                    text = child.text or ""
                    if text:
                        all_names.append(text)
                    lang = child.get("{http://www.w3.org/XML/1998/namespace}lang", "")
                    if lang == "en" or not name:  # prefer English for display
                        name = text
            flows.append(
                Dataflow(
                    flow_id=el.get("id", ""),
                    agency=el.get("agencyID", AGENCY),
                    version=el.get("version", "1.0"),
                    name=name,
                    all_names=tuple(all_names),
                )
            )
        if not flows:
            raise SdmxError("Dataflow list came back empty — unexpected response shape")
        return flows

    async def get_dimensions(self, flow_id: str) -> list[str]:
        """Ordered dimension IDs of a dataflow's data structure.

        This is the order the dotted `key` filter uses (TIME_PERIOD excluded —
        time is filtered via startPeriod/endPeriod instead).
        """
        raw = await self._get(
            f"dataflow/{AGENCY}/{flow_id}/latest",
            accept=XML_ACCEPT,
            params={"references": "all"},
        )
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise SdmxError(
                f"Could not parse structure XML for {flow_id}. First bytes: {raw[:200]!r}"
            ) from exc

        dims: list[tuple[int, str]] = []
        for order, el in enumerate(root.iter()):
            if _strip_ns(el.tag) != "Dimension":
                continue
            dim_id = el.get("id")
            if not dim_id:
                continue
            position = int(el.get("position", order))
            dims.append((position, dim_id))
        if not dims:
            raise SdmxError(f"No dimensions found for {flow_id} — unexpected response shape")
        return [dim_id for _, dim_id in sorted(dims)]

    async def search_dataflows(self, keyword: str) -> list[Dataflow]:
        """Case-insensitive match on the ID and EVERY language's name."""
        keyword_lower = keyword.lower()
        return [
            f
            for f in await self.list_dataflows()
            if keyword_lower in f.flow_id.lower()
            or any(keyword_lower in n.lower() for n in f.all_names)
        ]

    async def get_data_csv(
        self,
        flow_id: str,
        key: str = "ALL",
        start_period: str | None = None,
        end_period: str | None = None,
    ) -> bytes:
        """Fetch observations as SDMX-CSV bytes.

        `key` is the dotted dimension filter (e.g. "A.ITTER107.....") or "ALL".
        """
        params: dict[str, str] = {}
        if start_period:
            params["startPeriod"] = start_period
        if end_period:
            params["endPeriod"] = end_period
        raw = await self._get(f"data/{flow_id}/{key}", accept=CSV_ACCEPT, params=params)
        head = raw[:200].lstrip()
        if head.startswith(b"<"):
            raise SdmxError(
                f"Expected CSV for {flow_id} but got XML/HTML — the flow may be "
                "empty for this key, or CSV is not supported for it. "
                f"First bytes: {head[:120]!r}"
            )
        return raw
