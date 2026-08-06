"""Integration tests: the full offline pipeline, and a deselected live API check.

fetch (mocked API) -> raw CSV -> normalized Parquet -> DuckDB views -> query layer
"""

from __future__ import annotations

import httpx2
import polars as pl
import pytest

from ingestion import fetch
from ingestion.fetch import DatasetConfig, load_registry
from ingestion.sdmx_client import IstatClient
from italy_dashboard import queries as q

pytestmark = pytest.mark.integration

# Mirrors the real SDMX-CSV `labels=both` format: combined "ID: Label" headers
# and combined "code: label" cell values.
FAKE_ISTAT_CSV = (
    '"DATAFLOW","REF_AREA: Territorio","TIPO_REATO: Tipo di delitto",'
    '"TIME_PERIOD: Periodo","OBS_VALUE: Valore"\n'
    '"IT1:73_58(1.2)","ITC4: Lombardia","FURTO: Furti",2022,190000\n'
    '"IT1:73_58(1.2)","ITC4: Lombardia","FURTO: Furti",2023,181000\n'
    '"IT1:73_58(1.2)","ITI4: Lazio","FURTO: Furti",2022,150000\n'
    '"IT1:73_58(1.2)","ITI4: Lazio","FURTO: Furti",2023,155000\n'
    '"IT1:73_58(1.2)","ITC4: Lombardia","RAPINA: Rapine",2023,4100\n'
)


async def test_fetch_dataset_end_to_end_with_mocked_api(data_dir, monkeypatch):
    """fetch_dataset writes raw CSV and a correctly normalized Parquet."""

    async def handler(request: httpx2.Request) -> httpx2.Response:
        assert "/data/73_58/" in request.url.path
        return httpx2.Response(200, text=FAKE_ISTAT_CSV)

    cfg = load_registry().datasets["crime_reported"]
    assert isinstance(cfg, DatasetConfig)

    async with IstatClient(transport=httpx2.MockTransport(handler)) as client:
        await fetch.fetch_dataset(client, "crime_reported", cfg)

    raw = fetch.RAW_DIR / "crime_reported.csv"
    assert raw.exists()

    df = pl.read_parquet(data_dir / "crime_reported.parquet")
    assert df.height == 5
    assert set(df["territory_name"].unique()) == {"Lombardia", "Lazio"}
    assert (
        df.filter((pl.col("period") == "2023") & (pl.col("category") == "FURTO"))["value"].sum()
        == 336000
    )


async def test_pipeline_feeds_the_dashboard_query_layer(data_dir, monkeypatch):
    """After fetch + rebuild_db, the app's query layer sees the data."""

    async def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, text=FAKE_ISTAT_CSV)

    cfg = load_registry().datasets["crime_reported"]
    async with IstatClient(transport=httpx2.MockTransport(handler)) as client:
        await fetch.fetch_dataset(client, "crime_reported", cfg)

    monkeypatch.setattr(q, "DATA_DIR", data_dir)
    monkeypatch.setattr(q, "MARTS_DIR", data_dir / "marts")
    assert q.db_ready()
    assert q.region_names(view="crime_reported") == [q.NATIONAL, "Lazio", "Lombardia"]

    df = pl.read_parquet(data_dir / "crime_reported.parquet")
    assert int(df.filter(pl.col("period") == "2023")["value"].sum()) == 340100


def test_snapshot_is_usable_after_partial_refresh(data_dir, monkeypatch):
    """Only some datasets present -> the query layer still works (Docker/host
    portability: views are built in-memory from whatever parquet exists)."""
    from ingestion.sample_data import generate_all

    generate_all(data_dir, seed=1)
    (data_dir / "economy_inflation.parquet").unlink()  # simulate a failed dataset

    monkeypatch.setattr(q, "DATA_DIR", data_dir)
    assert q.db_ready()
    assert q.region_names(view="crime_reported")  # present datasets work
    assert q.inflation_series() == []  # missing dataset degrades to empty


@pytest.mark.live
async def test_live_istat_dataflow_list():
    """Hits the real ISTAT API. Run explicitly with: pytest -m live"""
    async with IstatClient() as client:
        flows = await client.list_dataflows()
    assert len(flows) > 100
