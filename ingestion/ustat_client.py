"""USTAT (Ufficio Statistica MUR) client for Italian university scholarships (DSU).

Queries dati-ustat.mur.gov.it CKAN API to discover and download the latest
"Numero di interventi" (number of scholarships granted) dataset. Data is
regional and broken down by type of support (housing, meal plan, fee waivers,
etc). Academic year basis (e.g., 2023 dataset covers a.a. 2022/23).
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
from collections.abc import AsyncGenerator
from typing import Any
from urllib.parse import urljoin

import httpx2  # type: ignore[import-not-found]

logger = logging.getLogger(__name__)

USTAT_API_BASE = "https://dati-ustat.mur.gov.it/api/3/action"
DATASET_ID = "diritto-allo-studio-universitario-dsu-regionale"
INTERVENTI_RESOURCE_NAME = "Numero di interventi"

# Map dataset versions to the academic year they cover (trailing label vs actual year)
# "2023" dataset = academic year 2022/23, published Jan 2023
DATASET_VERSIONS = {
    "2025": "2024/25",
    "2024": "2023/24",
    "2023": "2022/23",
    "2022": "2021/22",
    "2021": "2020/21",
}


async def _fetch_json(url: str, client: httpx2.AsyncClient) -> dict[str, Any]:
    """Fetch and parse JSON from USTAT API endpoint."""
    resp = await client.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


async def list_available_datasets(client: httpx2.AsyncClient) -> dict[str, str]:
    """Return {version: package_id} for all available DSU datasets.

    Queries CKAN to find all versions of the DSU dataset package, returning
    a mapping of version label (e.g., "2023") to the package ID needed for
    resource lookups.
    """
    # Fetch the full package list and filter locally (USTAT CKAN's search is unreliable)
    url = urljoin(USTAT_API_BASE + "/", "package_list")
    data = await _fetch_json(url, client)

    results = {}
    for pkg_id in data.get("result", []):
        # Filter for DSU packages: "YYYY-diritto-allo-studio-universitario-dsu-regionale"
        if "diritto-allo-studio-universitario-dsu-regionale" in pkg_id:
            # Parse version from name: "2023-diritto-allo-studio-universitario-dsu-regionale"
            parts = pkg_id.split("-")
            if parts and parts[0].isdigit():
                version = parts[0]
                results[version] = pkg_id
    return results


async def get_latest_interventi_csv_url(
    client: httpx2.AsyncClient,
) -> tuple[str, str]:
    """Fetch download URL for the latest 'Numero di interventi' CSV resource.

    Returns: (url, dataset_version_label) e.g., (
        "https://dati-ustat.mur.gov.it/dataset/.../download/2023_dsu_interventi.csv",
        "2023"
    )
    """
    versions = await list_available_datasets(client)
    if not versions:
        raise RuntimeError(f"No DSU datasets found at {USTAT_API_BASE}/package_search")

    # Use the latest (highest version number available)
    try:
        latest_version = max(versions.keys(), key=lambda x: int(x))
    except (ValueError, TypeError) as e:
        raise RuntimeError(f"Invalid version format in USTAT datasets: {e}") from e
    package_id = versions[latest_version]

    # Fetch package details to locate the "Numero di interventi" resource
    url = urljoin(USTAT_API_BASE + "/", f"package_show?id={package_id}")
    data = await _fetch_json(url, client)

    pkg = data.get("result", {})
    for resource in pkg.get("resources", []):
        if resource.get("name", "").startswith(
            f"{latest_version} Numero di interventi"
        ) or INTERVENTI_RESOURCE_NAME in resource.get("name", ""):
            csv_url = resource.get("url", "")
            if csv_url:
                return csv_url, latest_version

    raise RuntimeError(f"No '{INTERVENTI_RESOURCE_NAME}' resource found in dataset {package_id}")


async def download_interventi_csv(url: str, client: httpx2.AsyncClient) -> io.BytesIO:
    """Download CSV from USTAT server and return as BytesIO for parsing."""
    resp = await client.get(url, timeout=60)
    resp.raise_for_status()
    return io.BytesIO(resp.content)


async def fetch_interventi(
    client: httpx2.AsyncClient | None = None,
) -> AsyncGenerator[dict[str, str], None]:
    """Stream DSU 'Numero di interventi' records (scholarships by region).

    Each record represents the count of a specific scholarship type (housing,
    meal plan, fee waiver, etc.) for a region in an academic year.

    Yields: {ente_dsu, regione, ateneo, anno_accademico, tipo_intervento, n_interventi}
    """
    own_client = False
    if client is None:
        client = httpx2.AsyncClient()
        own_client = True

    try:
        csv_url, version = await get_latest_interventi_csv_url(client)
        logger.info(f"Fetching latest USTAT DSU interventi (version {version}): {csv_url}")

        csv_data = await download_interventi_csv(csv_url, client)
        csv_data.seek(0)

        # USTAT CSVs use semicolon as delimiter and ISO-8859-1 encoding
        reader = csv.DictReader(io.TextIOWrapper(csv_data, encoding="iso-8859-1"), delimiter=";")
        for row in reader:
            if row:
                yield dict(row)
    finally:
        if own_client and client is not None:
            await client.aclose()


async def main() -> None:
    """Test client: list datasets and fetch a few sample records."""
    async with httpx2.AsyncClient() as client:
        print("Available DSU datasets:")
        datasets = await list_available_datasets(client)
        for version, pkg_id in sorted(datasets.items(), reverse=True):
            aa = DATASET_VERSIONS.get(version, "unknown")
            print(f"  {version} (a.a. {aa}): {pkg_id}")

        print("\nFetching latest 'Numero di interventi' CSV:")
        csv_url, version = await get_latest_interventi_csv_url(client)
        print(f"  Version: {version}")
        print(f"  URL: {csv_url}")

        print("\nSample records:")
        count = 0
        async for record in fetch_interventi(client):
            print(f"  {record}")
            count += 1
            if count >= 3:
                break


class USTATClient:
    """Async context manager for USTAT DSU scholarship data.

    Wraps the raw fetch functions to match the ingestion framework's
    AnyClient interface (get_data_csv, search_dataflows).
    """

    def __init__(self) -> None:
        self._client: httpx2.AsyncClient | None = None

    async def __aenter__(self) -> USTATClient:
        self._client = httpx2.AsyncClient()
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get_data_csv(
        self, dataflow_id: str, key: str | None = None, start_period: str | None = None
    ) -> bytes:
        """Fetch CSV data for a USTAT dataset.

        Args:
            dataflow_id: USTAT dataset package ID (e.g.,
                "diritto-allo-studio-universitario-dsu-regionale")
            key: Unused (USTAT CKAN doesn't support server-side filtering)
            start_period: Unused

        Returns: UTF-8 encoded CSV bytes from the latest "Numero di interventi" resource
        """
        if self._client is None:
            raise RuntimeError("Client not initialized (use 'async with' context)")
        if dataflow_id != DATASET_ID:
            raise ValueError(f"Unknown USTAT dataset: {dataflow_id!r}")
        csv_url, version = await get_latest_interventi_csv_url(self._client)
        logger.info(f"Fetching USTAT DSU v{version} from {csv_url}")
        csv_bytes = await download_interventi_csv(csv_url, self._client)
        # USTAT CSVs are ISO-8859-1; convert to UTF-8 for downstream compatibility
        csv_text = csv_bytes.getvalue().decode("iso-8859-1")
        return csv_text.encode("utf-8")

    async def search_dataflows(self, keyword: str) -> list[Any]:
        """Search for USTAT dataflows (minimal stub for discover command).

        USTAT CKAN API doesn't expose a full dataflow search, so we just
        return the DSU dataset if the keyword matches.
        """
        if self._client is None:
            raise RuntimeError("Client not initialized (use 'async with' context)")
        if keyword.lower() in ["dsu", "diritto", "studio", "borse", "scholarship"]:
            # Return a minimal stub matching the Dataflow interface
            return [{"flow_id": DATASET_ID, "version": "1.0", "name": "DSU Scholarships"}]
        return []


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
