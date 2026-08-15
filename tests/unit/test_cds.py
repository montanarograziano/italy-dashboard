"""Unit tests for the bulk CDS fetcher: point extraction, cache, gates, all offline.

cdsapi.Client is never constructed for real: every test that needs a "client"
passes a small fake object exposing only `.retrieve(name, request, target)`,
which is all ingestion.cds ever calls on it. xarray is a real dependency here
(installed via the `cds` extra) so extraction runs against genuine NetCDF
files built by the fixtures below, not against mocked xarray internals.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl
import pytest
import xarray as xr

from ingestion import cds
from ingestion.cds import CDSError
from ingestion.weather import Capital, WeatherError

MILANO = Capital("ITC45", "Milano", 45.4642, 9.19)
ROMA = Capital("ITE43", "Roma", 41.8933, 12.4829)


def write_synthetic_chunk(
    path: Path,
    dates: list[str],
    lats: list[float],
    lons: list[float],
    kelvin_value: float | np.ndarray | None,
) -> None:
    """A minimal NetCDF shaped like a derived-era5-land-daily-statistics chunk:
    one data variable, a datetime64 time coordinate, and a latitude/longitude
    grid. `kelvin_value` is either a constant or a 3D array matching
    (time, lat, lon)."""
    shape = (len(dates), len(lats), len(lons))
    data = np.full(shape, np.nan) if kelvin_value is None else np.asarray(kelvin_value)
    if data.shape != shape:
        data = np.broadcast_to(np.asarray(kelvin_value, dtype=float), shape)
    ds = xr.Dataset(
        {"t2m": (("valid_time", "latitude", "longitude"), data)},
        coords={
            "valid_time": np.array(dates, dtype="datetime64[ns]"),
            "latitude": lats,
            "longitude": lons,
        },
    )
    ds.to_netcdf(path)


# --------------------------------------------------------------------------
# Bounding-box pre-flight.
# --------------------------------------------------------------------------


def test_every_real_capital_falls_inside_the_italy_bbox():
    """Guards the bbox itself against ever being narrowed below the real seed."""
    from ingestion.weather import load_capitals as real_load_capitals

    cds.verify_capitals_in_bbox(real_load_capitals())  # must not raise


def test_verify_capitals_in_bbox_raises_for_a_point_outside():
    outside = Capital("ITX00", "Nowhere", 60.0, 9.0)  # north of the bbox
    with pytest.raises(CDSError, match="outside the CDS area"):
        cds.verify_capitals_in_bbox([MILANO, outside])


# --------------------------------------------------------------------------
# Chunk caching: keyed by (year, statistic), resumable.
# --------------------------------------------------------------------------


def test_chunk_path_is_keyed_by_year_and_statistic(tmp_path):
    a = cds._chunk_path(tmp_path, 1950, "daily_mean")
    b = cds._chunk_path(tmp_path, 1950, "daily_minimum")
    c = cds._chunk_path(tmp_path, 1951, "daily_mean")
    assert a.name == "1950_daily_mean.nc"
    assert len({a, b, c}) == 3


def test_year_is_final_only_for_years_strictly_before_today():
    today = date(2026, 3, 1)
    assert cds._year_is_final(2025, today) is True
    assert cds._year_is_final(2026, today) is False


class FakeCDSClient:
    """Stands in for cdsapi.Client(): records calls, writes a synthetic chunk."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def retrieve(self, name: str, request: dict, target: str) -> None:
        self.calls.append((name, request))
        write_synthetic_chunk(Path(target), ["2020-01-01"], [45.0], [9.0], 280.0)


def test_download_chunk_skips_a_cached_final_year(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    cached = cds._chunk_path(raw_dir, 2020, "daily_mean")
    write_synthetic_chunk(cached, ["2020-01-01"], [45.0], [9.0], 280.0)

    client = FakeCDSClient()
    out = cds.download_chunk(client, raw_dir, 2020, "daily_mean", cds.ITALY_BBOX, date(2026, 1, 1))

    assert out == cached
    assert client.calls == []  # never asked the network for a file already on disk


def test_download_chunk_always_refetches_the_current_year(tmp_path):
    """The current year keeps growing, so its cache must never short-circuit a download."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    cached = cds._chunk_path(raw_dir, 2026, "daily_mean")
    write_synthetic_chunk(cached, ["2026-01-01"], [45.0], [9.0], 280.0)

    client = FakeCDSClient()
    cds.download_chunk(client, raw_dir, 2026, "daily_mean", cds.ITALY_BBOX, date(2026, 6, 1))

    assert len(client.calls) == 1


def test_download_chunk_downloads_when_missing_and_leaves_no_tmp_file(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    client = FakeCDSClient()

    out = cds.download_chunk(client, raw_dir, 2019, "daily_mean", cds.ITALY_BBOX, date(2026, 1, 1))

    assert len(client.calls) == 1
    name, request = client.calls[0]
    assert name == cds.CDS_DATASET_ID
    assert request["daily_statistic"] == "daily_mean"
    assert request["area"] == list(cds.ITALY_BBOX)
    assert out.exists()
    assert not list(raw_dir.glob("*.tmp"))


# --------------------------------------------------------------------------
# Point extraction: nearest-cell selection, Kelvin -> Celsius, row schema.
# --------------------------------------------------------------------------


def test_extract_year_rows_selects_nearest_cell_converts_kelvin_and_matches_schema(tmp_path):
    # A small Italy-ish grid: Milano's (45.4642, 9.19) is nearest to (45.5, 9.2).
    lats = [46.0, 45.5, 45.0]
    lons = [9.0, 9.2, 9.5]
    dates = ["2020-01-01", "2020-01-02"]

    paths = {}
    for statistic, kelvin in [
        ("daily_mean", 283.15),  # -> 10.0 C
        ("daily_minimum", 273.15),  # -> 0.0 C
        ("daily_maximum", 293.15),  # -> 20.0 C
    ]:
        path = tmp_path / f"{statistic}.nc"
        write_synthetic_chunk(path, dates, lats, lons, kelvin)
        paths[statistic] = path

    rows = cds.extract_year_rows(paths, [MILANO])

    assert len(rows) == 2
    assert list(rows[0]) == cds.WEATHER_COLUMNS
    assert rows[0] == {
        "province_code": "ITC45",
        "date": date(2020, 1, 1),
        "t_min": 0.0,
        "t_mean": 10.0,
        "t_max": 20.0,
    }
    assert rows[1]["date"] == date(2020, 1, 2)


def test_extract_year_rows_preserves_nan_as_none(tmp_path):
    lats, lons, dates = [45.0], [9.0], ["2020-01-01"]
    paths = {}
    for statistic in ("daily_mean", "daily_minimum", "daily_maximum"):
        path = tmp_path / f"{statistic}.nc"
        write_synthetic_chunk(path, dates, lats, lons, None)
        paths[statistic] = path

    rows = cds.extract_year_rows(paths, [Capital("ITX00", "X", 45.0, 9.0)])

    assert rows[0]["t_mean"] is None
    assert rows[0]["t_min"] is None
    assert rows[0]["t_max"] is None


def test_extract_year_rows_raises_when_nearest_cell_is_too_far(tmp_path):
    # Grid cells are all far from Roma; nearest is > MAX_CELL_DISTANCE_DEG away.
    lats, lons, dates = [46.0, 45.5], [9.0, 9.5], ["2020-01-01"]
    paths = {}
    for statistic in ("daily_mean", "daily_minimum", "daily_maximum"):
        path = tmp_path / f"{statistic}.nc"
        write_synthetic_chunk(path, dates, lats, lons, 280.0)
        paths[statistic] = path

    with pytest.raises(CDSError, match="beyond the"):
        cds.extract_year_rows(paths, [ROMA])


def test_cds_error_is_a_weather_error():
    """CDSError must be catchable wherever WeatherError already is."""
    assert issubclass(CDSError, WeatherError)


# --------------------------------------------------------------------------
# Missing optional dependencies: clear, actionable errors.
# --------------------------------------------------------------------------


def test_missing_cdsapi_gives_a_clear_actionable_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "cdsapi", None)  # forces ImportError on import
    with pytest.raises(CDSError, match="uv sync --extra cds"):
        cds._require_cdsapi()


def test_missing_xarray_gives_a_clear_actionable_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "xarray", None)
    with pytest.raises(CDSError, match="uv sync --extra cds"):
        cds._require_xarray()


# --------------------------------------------------------------------------
# cmd_refresh: end-to-end with a fake client, fully offline.
# --------------------------------------------------------------------------


def write_seed(tmp_path: Path) -> Path:
    import csv

    path = tmp_path / "province_capitals.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "province_code",
                "province_name",
                "capital_city",
                "region_code",
                "region_name",
                "lat",
                "lon",
            ]
        )
        w.writerow(["ITC45", "Milano", "Milano", "ITC4", "Lombardia", "45.4642", "9.19"])
        w.writerow(["ITE43", "Roma", "Roma", "ITE4", "Lazio", "41.8933", "12.4829"])
    return path


class WholeItalyFakeClient:
    """Fake CDS client whose retrieve() writes a grid wide enough to cover
    every capital in the temp seed, for the requested year."""

    def __init__(self, kelvin_by_capital: dict[str, float] | None = None):
        self.calls: list[tuple[str, dict]] = []
        self._kelvin_by_capital = kelvin_by_capital or {}

    def retrieve(self, name: str, request: dict, target: str) -> None:
        self.calls.append((name, request))
        year = request["year"][0]
        lats = [46.0, 45.4642, 45.0, 41.8933, 41.0]
        lons = [9.0, 9.19, 9.5, 12.4829, 13.0]
        dates = [f"{year}-01-01", f"{year}-01-02"]
        # Default a uniform value everywhere, unless a capital has an override
        # (used to simulate an all-null "ocean" capital for the gate test).
        default = 283.15
        data = np.full((len(dates), len(lats), len(lons)), default)
        write_synthetic_chunk(Path(target), dates, lats, lons, data)


def patch_seed_and_client(monkeypatch, tmp_path: Path, client) -> None:
    from ingestion.weather import load_capitals as real_load_capitals

    seed = write_seed(tmp_path)
    monkeypatch.setattr(cds, "load_capitals", lambda: real_load_capitals(seed))
    monkeypatch.setattr(cds, "_new_client", lambda: client)


def test_cmd_refresh_full_run_writes_the_shared_snapshot(tmp_path, monkeypatch):
    client = WholeItalyFakeClient()
    patch_seed_and_client(monkeypatch, tmp_path, client)

    rc = cds.cmd_refresh(2020, 2020, data_dir=tmp_path)

    assert rc == 0
    df = pl.read_parquet(tmp_path / cds.SNAPSHOT_NAME)
    assert df.columns == cds.WEATHER_COLUMNS
    assert set(df["province_code"].to_list()) == {"ITC45", "ITE43"}
    # 3 statistics requested per year (mean/min/max), once per year in range.
    assert len(client.calls) == 3


def test_cmd_refresh_blocks_write_when_a_capital_exceeds_the_null_limit(tmp_path, monkeypatch):
    class OceanFakeClient(WholeItalyFakeClient):
        def retrieve(self, name: str, request: dict, target: str) -> None:
            self.calls.append((name, request))
            year = request["year"][0]
            lats = [46.0, 45.4642, 45.0, 41.8933, 41.0]
            lons = [9.0, 9.19, 9.5, 12.4829, 13.0]
            dates = [f"{year}-01-01", f"{year}-01-02"]
            data = np.full((len(dates), len(lats), len(lons)), 283.15)
            # Milano's own cell (index 1, 1) is all-NaN: simulates an ocean cell.
            data[:, 1, 1] = np.nan
            write_synthetic_chunk(Path(target), dates, lats, lons, data)

    client = OceanFakeClient()
    patch_seed_and_client(monkeypatch, tmp_path, client)

    rc = cds.cmd_refresh(2020, 2020, data_dir=tmp_path)

    assert rc == 1
    assert not (tmp_path / cds.SNAPSHOT_NAME).exists()


def test_cmd_refresh_explicit_year_range_preserves_other_years(tmp_path, monkeypatch):
    from ingestion.weather import write_snapshot as real_write_snapshot

    existing_rows = [
        {
            "province_code": "ITC45",
            "date": date(2015, 6, 1),
            "t_min": 1.0,
            "t_mean": 2.0,
            "t_max": 3.0,
        },
        {
            "province_code": "ITE43",
            "date": date(2015, 6, 1),
            "t_min": 4.0,
            "t_mean": 5.0,
            "t_max": 6.0,
        },
    ]
    real_write_snapshot(existing_rows, tmp_path)

    client = WholeItalyFakeClient()
    patch_seed_and_client(monkeypatch, tmp_path, client)

    rc = cds.cmd_refresh(2020, 2020, data_dir=tmp_path)

    assert rc == 0
    df = pl.read_parquet(tmp_path / cds.SNAPSHOT_NAME)
    # 2015 rows for both cities must survive alongside the new 2020 rows.
    assert date(2015, 6, 1) in df.filter(pl.col("province_code") == "ITC45")["date"].to_list()
    assert date(2015, 6, 1) in df.filter(pl.col("province_code") == "ITE43")["date"].to_list()
    assert date(2020, 1, 1) in df["date"].to_list()


def test_cmd_refresh_rejects_a_backwards_year_range(tmp_path, monkeypatch):
    client = WholeItalyFakeClient()
    patch_seed_and_client(monkeypatch, tmp_path, client)

    rc = cds.cmd_refresh(2020, 2010, data_dir=tmp_path)

    assert rc == 2
    assert client.calls == []


# --------------------------------------------------------------------------
# CLI argument parsing.
# --------------------------------------------------------------------------


def test_main_prints_usage_without_a_refresh_argument(capsys):
    rc = cds.main([])
    assert rc == 2
    assert "python -m ingestion.cds" in capsys.readouterr().out


def test_main_rejects_a_single_year_argument(capsys):
    rc = cds.main(["refresh", "1950"])
    assert rc == 2
