"""Unit tests for the bulk CDS fetcher: point extraction, cache, gates, all offline.

cdsapi.Client is never constructed for real: every test that needs a "client"
passes a small fake object exposing only `.retrieve(name, request, target)`,
which is all ingestion.cds ever calls on it. xarray is a real dependency here
(installed via the `cds` extra) so extraction runs against genuine NetCDF
files built by the fixtures below, not against mocked xarray internals.

The `cds` extra is NOT installed by a plain `uv sync`, and `just check` runs
pytest without it, so this whole module skips rather than failing collection
when xarray/cdsapi/numpy are absent.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from ingestion import cds
from ingestion.cds import CDSError
from ingestion.weather import Capital, WeatherError, null_rate

np = pytest.importorskip("numpy", reason="needs the `cds` extra: uv sync --extra cds")
xr = pytest.importorskip("xarray", reason="needs the `cds` extra: uv sync --extra cds")
pytest.importorskip("cdsapi", reason="needs the `cds` extra: uv sync --extra cds")

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


def complete_plan(year: int) -> cds.YearPlan:
    """A plan covering a whole, fully published calendar year."""
    return cds.YearPlan(year, tuple(range(1, 13)), date(year, 12, 31))


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
# Publication lag: never request a day ERA5-Land cannot have published.
# --------------------------------------------------------------------------


def test_last_available_day_uses_the_same_lag_as_the_open_meteo_path():
    from ingestion.weather import PUBLICATION_LAG_DAYS

    today = date(2026, 8, 15)
    assert cds.last_available_day(today) == today - timedelta(days=PUBLICATION_LAG_DAYS)


def test_requested_days_for_the_current_year_stop_at_the_publication_lag_boundary():
    """The bug that stopped the backfill: a run in 2026 asked CDS for all of
    2026, including days that do not exist yet."""
    boundary = cds.last_available_day(date(2026, 8, 15))
    assert boundary == date(2026, 8, 8)

    plan = cds.plan_year(2026, boundary)
    assert plan is not None
    assert plan.is_partial
    assert plan.months == tuple(range(1, 8))  # January..July, all fully ended
    assert plan.last_day == date(2026, 7, 31)

    days = cds.requested_days(plan)
    assert max(days) <= boundary
    assert days[-1] == date(2026, 7, 31)
    assert date(2026, 8, 9) not in days  # nothing past the boundary
    assert date(2026, 12, 31) not in days  # nothing in the future at all


def test_plan_year_covers_a_past_year_whole():
    plan = cds.plan_year(2020, cds.last_available_day(date(2026, 8, 15)))
    assert plan is not None
    assert not plan.is_partial
    assert plan.months == tuple(range(1, 13))
    assert plan.last_day == date(2020, 12, 31)
    assert len(cds.requested_days(plan)) == 366  # a leap year, every day


def test_plan_year_is_none_before_the_first_month_of_that_year_is_complete():
    """Early January: the new year has no complete month, so it must not be requested."""
    assert cds.plan_year(2026, cds.last_available_day(date(2026, 1, 20))) is None


def test_plan_year_includes_a_month_that_ended_exactly_on_the_boundary():
    assert cds.plan_year(2026, date(2026, 1, 31)) == cds.YearPlan(2026, (1,), date(2026, 1, 31))


# --------------------------------------------------------------------------
# Chunk caching: keyed by (year, statistic, coverage), resumable.
# --------------------------------------------------------------------------


def test_chunk_path_is_keyed_by_year_and_statistic(tmp_path):
    a = cds._chunk_path(tmp_path, complete_plan(1950), "daily_mean")
    b = cds._chunk_path(tmp_path, complete_plan(1950), "daily_minimum")
    c = cds._chunk_path(tmp_path, complete_plan(1951), "daily_mean")
    assert a.name == "1950_daily_mean.nc"
    assert len({a, b, c}) == 3


def test_chunk_path_for_a_partial_year_names_the_day_it_stops_at(tmp_path):
    """A truncated current year must not be cached as if it were the whole year."""
    through_july = cds.plan_year(2026, cds.last_available_day(date(2026, 8, 15)))
    through_august = cds.plan_year(2026, cds.last_available_day(date(2026, 9, 15)))
    assert through_july is not None and through_august is not None

    july_path = cds._chunk_path(tmp_path, through_july, "daily_mean")
    august_path = cds._chunk_path(tmp_path, through_august, "daily_mean")

    assert july_path.name == "2026_daily_mean_through_20260731.nc"
    assert august_path.name == "2026_daily_mean_through_20260831.nc"
    assert july_path != august_path  # next month's run cannot reuse this month's chunk


class FakeCDSClient:
    """Stands in for cdsapi.Client(): records calls, writes a synthetic chunk."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.targets: list[str] = []

    def retrieve(self, name: str, request: dict, target: str) -> None:
        self.calls.append((name, request))
        self.targets.append(target)
        write_synthetic_chunk(Path(target), ["2020-01-01"], [45.0], [9.0], 280.0)


def test_download_chunk_skips_a_cached_chunk(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    plan = complete_plan(2020)
    cached = cds._chunk_path(raw_dir, plan, "daily_mean")
    write_synthetic_chunk(cached, ["2020-01-01"], [45.0], [9.0], 280.0)

    client = FakeCDSClient()
    out = cds.download_chunk(client, raw_dir, plan, "daily_mean", cds.ITALY_BBOX)

    assert out == cached
    assert client.calls == []  # never asked the network for a file already on disk


def test_download_chunk_reuses_a_cached_partial_current_year(tmp_path):
    """A rerun of the current year must not re-pay three queued requests: the
    cache key already encodes exactly how far the cached chunk reaches."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    plan = cds.plan_year(2026, cds.last_available_day(date(2026, 8, 15)))
    assert plan is not None
    cached = cds._chunk_path(raw_dir, plan, "daily_mean")
    write_synthetic_chunk(cached, ["2026-01-01"], [45.0], [9.0], 280.0)

    client = FakeCDSClient()
    out = cds.download_chunk(client, raw_dir, plan, "daily_mean", cds.ITALY_BBOX)

    assert out == cached
    assert client.calls == []


def test_download_chunk_refetches_the_current_year_once_more_data_exists(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    july = cds.plan_year(2026, cds.last_available_day(date(2026, 8, 15)))
    august = cds.plan_year(2026, cds.last_available_day(date(2026, 9, 15)))
    assert july is not None and august is not None
    write_synthetic_chunk(
        cds._chunk_path(raw_dir, july, "daily_mean"), ["2026-01-01"], [45.0], [9.0], 280.0
    )

    client = FakeCDSClient()
    out = cds.download_chunk(client, raw_dir, august, "daily_mean", cds.ITALY_BBOX)

    assert len(client.calls) == 1
    assert out.name == "2026_daily_mean_through_20260831.nc"


def test_download_chunk_downloads_when_missing_and_leaves_no_tmp_file(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    client = FakeCDSClient()

    out = cds.download_chunk(client, raw_dir, complete_plan(2019), "daily_mean", cds.ITALY_BBOX)

    assert len(client.calls) == 1
    name, request = client.calls[0]
    assert name == cds.CDS_DATASET_ID
    assert request["daily_statistic"] == "daily_mean"
    assert request["area"] == list(cds.ITALY_BBOX)
    assert out.exists()
    assert not list(raw_dir.glob("*.tmp"))


def test_download_chunk_writes_to_a_tmp_file_and_renames_it_into_place(tmp_path):
    """The rename is what makes the cache trustworthy: an interrupted download
    must never leave a truncated file under the final name."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    client = FakeCDSClient()

    out = cds.download_chunk(client, raw_dir, complete_plan(2019), "daily_mean", cds.ITALY_BBOX)

    written_to = Path(client.targets[0])
    assert written_to.name == out.name + ".tmp"  # cdsapi wrote to the .tmp path
    assert written_to != out
    assert not written_to.exists()  # renamed, not copied
    assert out.exists()


def test_download_chunk_leaves_no_final_file_when_the_request_fails(tmp_path):
    """A failed download must not leave anything a later run would treat as cached."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    class HalfWritingClient:
        def retrieve(self, name: str, request: dict, target: str) -> None:
            Path(target).write_bytes(b"partial")  # a truncated download
            raise RuntimeError("connection reset")

    with pytest.raises(CDSError):
        cds.download_chunk(
            HalfWritingClient(), raw_dir, complete_plan(2019), "daily_mean", cds.ITALY_BBOX
        )

    assert not cds._chunk_path(raw_dir, complete_plan(2019), "daily_mean").exists()
    assert not list(raw_dir.glob("*"))


# --------------------------------------------------------------------------
# Download failures: actionable errors, not raw cdsapi tracebacks.
# --------------------------------------------------------------------------


def test_download_chunk_wraps_a_request_failure_with_a_resume_hint(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    class FailingClient:
        def retrieve(self, name: str, request: dict, target: str) -> None:
            raise RuntimeError("403 Client Error: required licences not accepted")

    with pytest.raises(CDSError) as excinfo:
        cds.download_chunk(
            FailingClient(), raw_dir, complete_plan(1977), "daily_minimum", cds.ITALY_BBOX
        )

    message = str(excinfo.value)
    assert "1977" in message and "daily_minimum" in message  # which chunk died
    assert "403" in message  # the underlying cause survives
    assert str(raw_dir) in message  # where the completed chunks are
    assert "re-running the same command resumes" in message


def test_download_chunk_deletes_and_refetches_an_unreadable_cached_chunk(tmp_path):
    """A corrupt .nc would otherwise stay cached forever, failing every run identically."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    plan = complete_plan(2020)
    corrupt = cds._chunk_path(raw_dir, plan, "daily_mean")
    corrupt.write_bytes(b"not a netcdf file at all")

    client = FakeCDSClient()
    out = cds.download_chunk(client, raw_dir, plan, "daily_mean", cds.ITALY_BBOX)

    assert len(client.calls) == 1  # re-downloaded rather than reused
    assert out == corrupt
    with xr.open_dataset(out) as ds:  # and the replacement is readable
        assert list(ds.data_vars) == ["t2m"]


def test_download_chunk_raises_when_the_fresh_download_is_also_unreadable(tmp_path):
    """Second failure is not a stale cache: stop, name the file, tell the operator."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    plan = complete_plan(2020)
    cds._chunk_path(raw_dir, plan, "daily_mean").write_bytes(b"not a netcdf file")

    class GarbageClient:
        def __init__(self):
            self.calls = 0

        def retrieve(self, name: str, request: dict, target: str) -> None:
            self.calls += 1
            Path(target).write_bytes(b"still not a netcdf file")

    client = GarbageClient()
    with pytest.raises(CDSError) as excinfo:
        cds.download_chunk(client, raw_dir, plan, "daily_mean", cds.ITALY_BBOX)

    assert client.calls == 1  # re-downloaded exactly once, not in a loop
    message = str(excinfo.value)
    assert "2020_daily_mean.nc" in message
    assert "Remove" in message


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

    rows = cds.extract_year_rows(paths, [MILANO], 2020)

    assert len(rows) == 2
    assert list(rows[0]) == cds.WEATHER_COLUMNS
    assert rows[0] == {
        "province_code": "ITC45",
        "date": date(2020, 1, 1),
        "t_min": 0.0,
        "t_mean": 10.0,
        "t_max": 20.0,
        "precip_sum": None,
    }
    assert rows[1]["date"] == date(2020, 1, 2)


def test_extract_year_rows_preserves_nan_as_none(tmp_path):
    lats, lons, dates = [45.0], [9.0], ["2020-01-01"]
    paths = {}
    for statistic in ("daily_mean", "daily_minimum", "daily_maximum"):
        path = tmp_path / f"{statistic}.nc"
        write_synthetic_chunk(path, dates, lats, lons, None)
        paths[statistic] = path

    rows = cds.extract_year_rows(paths, [Capital("ITX00", "X", 45.0, 9.0)], 2020)

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
        cds.extract_year_rows(paths, [ROMA], 2020)


def test_cds_error_is_a_weather_error():
    """CDSError must be catchable wherever WeatherError already is."""
    assert issubclass(CDSError, WeatherError)


def test_verify_row_schema_raises_when_the_shared_schema_moves(monkeypatch):
    """A real raise, not an `assert`: `python -O` strips asserts, and a silent
    column reorder would swap values between t_min and t_max everywhere."""
    cds.verify_row_schema()  # the real schema must pass

    monkeypatch.setattr(
        cds, "WEATHER_COLUMNS", ["province_code", "date", "t_max", "t_mean", "t_min"]
    )
    with pytest.raises(CDSError, match="no longer matches the shared weather_daily schema"):
        cds.verify_row_schema()


# --------------------------------------------------------------------------
# Time-axis alignment: the three statistics are three independent downloads.
# --------------------------------------------------------------------------


def write_axis_chunks(tmp_path: Path, dates_by_statistic: dict[str, list[str]]) -> dict[str, Path]:
    """One chunk per statistic, each over its own dates, at Milano's cell.
    Values increase by 1 K per day so a mispairing is visible in the numbers."""
    paths: dict[str, Path] = {}
    base = {"daily_mean": 283.15, "daily_minimum": 273.15, "daily_maximum": 293.15}
    for statistic, dates in dates_by_statistic.items():
        path = tmp_path / f"{statistic}.nc"
        values = np.array([base[statistic] + i for i in range(len(dates))]).reshape(
            len(dates), 1, 1
        )
        write_synthetic_chunk(path, dates, [45.4642], [9.19], values)
        paths[statistic] = path
    return paths


def test_extract_year_rows_raises_when_the_statistics_cover_shifted_days(tmp_path):
    """Same day count, different days: the old code paired them positionally and
    silently attached each day's minimum and maximum to the previous day's mean."""
    paths = write_axis_chunks(
        tmp_path,
        {
            "daily_mean": ["2020-01-01", "2020-01-02", "2020-01-03"],
            "daily_minimum": ["2020-01-02", "2020-01-03", "2020-01-04"],
            "daily_maximum": ["2020-01-02", "2020-01-03", "2020-01-04"],
        },
    )

    with pytest.raises(CDSError) as excinfo:
        cds.extract_year_rows(paths, [MILANO], 2020)

    message = str(excinfo.value)
    assert "[2020]" in message
    assert "daily_mean" in message and "daily_minimum" in message
    assert "2020-01-01" in message and "2020-01-02" in message  # the first divergence


def test_extract_year_rows_raises_when_a_statistic_is_shorter_than_the_mean(tmp_path):
    """The old code raised a bare IndexError here, with no year and no remedy."""
    paths = write_axis_chunks(
        tmp_path,
        {
            "daily_mean": ["2020-01-01", "2020-01-02", "2020-01-03"],
            "daily_minimum": ["2020-01-01", "2020-01-02"],
            "daily_maximum": ["2020-01-01", "2020-01-02", "2020-01-03"],
        },
    )

    with pytest.raises(CDSError) as excinfo:
        cds.extract_year_rows(paths, [MILANO], 2020)

    message = str(excinfo.value)
    assert "3 days" in message and "2 days" in message
    assert "daily_minimum" in message


def test_extract_year_rows_raises_when_the_mean_is_shorter_than_the_others(tmp_path):
    """The other direction: the old code silently dropped the extra days."""
    paths = write_axis_chunks(
        tmp_path,
        {
            "daily_mean": ["2020-01-01", "2020-01-02"],
            "daily_minimum": ["2020-01-01", "2020-01-02", "2020-01-03"],
            "daily_maximum": ["2020-01-01", "2020-01-02", "2020-01-03"],
        },
    )

    with pytest.raises(CDSError) as excinfo:
        cds.extract_year_rows(paths, [MILANO], 2020)

    assert "2 days" in str(excinfo.value) and "3 days" in str(excinfo.value)


def test_extract_year_rows_accepts_identical_time_axes(tmp_path):
    dates = ["2020-01-01", "2020-01-02", "2020-01-03"]
    paths = write_axis_chunks(tmp_path, dict.fromkeys(cds.STATISTICS, dates))

    rows = cds.extract_year_rows(paths, [MILANO], 2020)

    assert [r["date"] for r in rows] == [date(2020, 1, d) for d in (1, 2, 3)]
    # Day 2 must carry day 2's minimum (273.15 + 1 K -> 1.0 C), not day 1's.
    assert rows[1]["t_min"] == pytest.approx(1.0)


# --------------------------------------------------------------------------
# Null gate: every temperature column, not just t_mean.
# --------------------------------------------------------------------------


def test_null_rates_agrees_with_the_shared_null_rate_for_t_mean():
    """Pins the equivalence with ingestion.weather.null_rate, which the
    Open-Meteo path uses, so the two gates cannot drift apart."""
    rows = [
        {"province_code": "X", "date": date(2020, 1, 1), "t_min": 1.0, "t_mean": 2.0, "t_max": 3.0},
        {
            "province_code": "X",
            "date": date(2020, 1, 2),
            "t_min": None,
            "t_mean": None,
            "t_max": 3.0,
        },
        {
            "province_code": "X",
            "date": date(2020, 1, 3),
            "t_min": None,
            "t_mean": 2.0,
            "t_max": 3.0,
        },
        {"province_code": "X", "date": date(2020, 1, 4), "t_min": 1.0, "t_mean": 2.0, "t_max": 3.0},
    ]

    rates = cds.null_rates(rows)

    assert rates["t_mean"] == null_rate(rows) == 0.25
    assert rates["t_min"] == 0.5
    assert rates["t_max"] == 0.0


def test_null_rates_treats_no_rows_as_fully_null():
    assert cds.null_rates([]) == {"t_max": 1.0, "t_mean": 1.0, "t_min": 1.0}


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


GRID_LATS = [46.0, 45.4642, 45.0, 41.8933, 41.0]
GRID_LONS = [9.0, 9.19, 9.5, 12.4829, 13.0]
CAPITAL_CELLS = {"ITC45": (45.4642, 9.19), "ITE43": (41.8933, 12.4829)}
DEFAULT_KELVIN = 283.15  # 10 C everywhere unless a test overrides a cell


class WholeItalyFakeClient:
    """Fake CDS client whose retrieve() writes a grid wide enough to cover
    every capital in the temp seed, for the requested year.

    `kelvin_by_capital` maps province_code -> {daily_statistic: kelvin or None},
    where None writes NaN into that capital's own cell: that is how a test
    simulates an ocean cell (all three statistics) or a single failed
    per-statistic download (one of them). `null_mean_days` NaNs whole days of
    the daily_mean chunk, for the row filter.
    """

    def __init__(
        self,
        kelvin_by_capital: dict[str, dict[str, float | None]] | None = None,
        day_count: int = 2,
        null_mean_days: tuple[int, ...] = (),
    ):
        self.calls: list[tuple[str, dict]] = []
        self.kelvin_by_capital = kelvin_by_capital or {}
        self.day_count = day_count
        self.null_mean_days = null_mean_days

    def retrieve(self, name: str, request: dict, target: str) -> None:
        self.calls.append((name, request))
        statistic = request["daily_statistic"]
        first = date(int(request["year"][0]), int(request["month"][0]), 1)
        dates = [(first + timedelta(days=i)).isoformat() for i in range(self.day_count)]
        data = np.full((len(dates), len(GRID_LATS), len(GRID_LONS)), DEFAULT_KELVIN)
        for code, by_statistic in self.kelvin_by_capital.items():
            if statistic not in by_statistic:
                continue
            lat, lon = CAPITAL_CELLS[code]
            value = by_statistic[statistic]
            data[:, GRID_LATS.index(lat), GRID_LONS.index(lon)] = np.nan if value is None else value
        if statistic == "daily_mean":
            for day in self.null_mean_days:
                data[day, :, :] = np.nan
        write_synthetic_chunk(Path(target), dates, GRID_LATS, GRID_LONS, data)


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
    ocean = {"ITC45": dict.fromkeys(cds.STATISTICS, None)}  # Milano's cell is all-NaN
    client = WholeItalyFakeClient(kelvin_by_capital=ocean)
    patch_seed_and_client(monkeypatch, tmp_path, client)

    rc = cds.cmd_refresh(2020, 2020, data_dir=tmp_path)

    assert rc == 1
    assert not (tmp_path / cds.SNAPSHOT_NAME).exists()


def test_cmd_refresh_blocks_write_when_only_the_minimum_column_is_null(
    tmp_path, monkeypatch, caplog
):
    """The three statistics are independent downloads: an empty daily_minimum
    used to sail through a t_mean-only gate and publish a snapshot with no
    minimum temperatures at all."""
    client = WholeItalyFakeClient(kelvin_by_capital={"ITC45": {"daily_minimum": None}})
    patch_seed_and_client(monkeypatch, tmp_path, client)

    with caplog.at_level("ERROR"):
        rc = cds.cmd_refresh(2020, 2020, data_dir=tmp_path)

    assert rc == 1
    assert not (tmp_path / cds.SNAPSHOT_NAME).exists()
    logged = caplog.text
    assert "ITC45" in logged  # which city
    assert "t_min" in logged  # which column
    assert "daily_minimum" in logged  # and which chunks to delete
    assert "ITC45.t_min" in logged  # the summary names the pair
    assert "t_mean" not in logged.split("Refusing")[-1]  # the healthy columns are not blamed


def test_cmd_refresh_drops_days_whose_mean_is_null_but_keeps_the_city(tmp_path, monkeypatch):
    """One missing day out of 200 is under MAX_NULL_RATE, so the run succeeds —
    but that day must not reach the snapshot as a null-mean row."""
    client = WholeItalyFakeClient(day_count=200, null_mean_days=(5,))
    patch_seed_and_client(monkeypatch, tmp_path, client)

    rc = cds.cmd_refresh(2020, 2020, data_dir=tmp_path)

    assert rc == 0
    df = pl.read_parquet(tmp_path / cds.SNAPSHOT_NAME)
    assert df.height == 2 * 199  # two cities, 200 days each, one day dropped
    assert date(2020, 1, 6) not in df["date"].to_list()  # index 5 from 2020-01-01
    assert date(2020, 1, 7) in df["date"].to_list()
    assert df["t_mean"].null_count() == 0


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


def test_cmd_refresh_requests_only_published_months_of_the_current_year(tmp_path, monkeypatch):
    """The finding that stopped the backfill: a 2026 run asked for all of 2026."""
    client = WholeItalyFakeClient()
    patch_seed_and_client(monkeypatch, tmp_path, client)

    rc = cds.cmd_refresh(2026, 2026, data_dir=tmp_path, today=date(2026, 8, 15))

    assert rc == 0
    assert len(client.calls) == 3
    for _, request in client.calls:
        assert request["year"] == ["2026"]
        assert request["month"] == ["01", "02", "03", "04", "05", "06", "07"]
    cached = sorted(p.name for p in (tmp_path / "raw" / "cds").glob("*.nc"))
    assert cached == [
        "2026_daily_maximum_through_20260731.nc",
        "2026_daily_mean_through_20260731.nc",
        "2026_daily_minimum_through_20260731.nc",
    ]


def test_cmd_refresh_defaults_the_end_year_to_the_last_published_one(tmp_path, monkeypatch):
    """Early January 2026: the newest fully published month is November 2025."""
    client = WholeItalyFakeClient()
    patch_seed_and_client(monkeypatch, tmp_path, client)
    monkeypatch.setattr(cds, "START_YEAR", 2025)

    rc = cds.cmd_refresh(data_dir=tmp_path, today=date(2026, 1, 3))

    assert rc == 0
    assert {request["year"][0] for _, request in client.calls} == {"2025"}
    assert client.calls[0][1]["month"][-1] == "11"  # December 2025 is not published yet


def test_cmd_refresh_clamps_an_end_year_in_the_future(tmp_path, monkeypatch):
    client = WholeItalyFakeClient()
    patch_seed_and_client(monkeypatch, tmp_path, client)

    rc = cds.cmd_refresh(2027, 2030, data_dir=tmp_path, today=date(2026, 8, 15))

    assert rc == 2  # nothing left to request once clamped to 2026
    assert client.calls == []


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
# CLI argument parsing.
# --------------------------------------------------------------------------


def test_main_prints_usage_without_a_refresh_argument(capsys):
    rc = cds.main([])
    assert rc == 2
    assert "python -m ingestion.cds" in capsys.readouterr().out


def test_main_rejects_a_single_year_argument(capsys):
    rc = cds.main(["refresh", "1950"])
    assert rc == 2


# --------------------------------------------------------------------------
# ARCO point time-series path: request shape, decading, aggregation, and the
# cmd_refresh_timeseries orchestration. All offline via a fake client that
# writes synthetic hourly NetCDF files.
# --------------------------------------------------------------------------


def write_synthetic_point_chunk(
    path: Path,
    dates: list[str],
    latitude: float,
    longitude: float,
    kelvin: float | None,
    precip_metres: float | None,
) -> None:
    """A minimal hourly point NetCDF shaped like the ARCO time-series response:
    one time coordinate, a single (scalar) latitude/longitude, and the two
    data variables t2m and tp."""
    shape = (len(dates),)
    t2m = np.full(shape, np.nan) if kelvin is None else np.full(shape, kelvin)
    tp = np.full(shape, np.nan) if precip_metres is None else np.full(shape, precip_metres)
    ds = xr.Dataset(
        {"t2m": (("valid_time",), t2m), "tp": (("valid_time",), tp)},
        coords={
            "valid_time": np.array(dates, dtype="datetime64[ns]"),
            "latitude": np.array([latitude]),
            "longitude": np.array([longitude]),
        },
    )
    ds.to_netcdf(path)


class FakeTimeseriesClient:
    """Fake CDS client whose retrieve() writes a synthetic hourly point NetCDF.

    `kelvin` and `precip_metres` feed every returned file; `null` simulates an
    all-missing cell (ocean), for the null gate. Records each call's dataset
    name and request so tests can assert the ARCO request shape.
    """

    def __init__(self, kelvin: float | None = 283.15, precip_metres: float | None = 0.001):
        self.calls: list[tuple[str, dict]] = []
        self.kelvin = kelvin
        self.precip_metres = precip_metres

    def retrieve(self, name: str, request: dict, target: str) -> None:
        self.calls.append((name, request))
        start, end = request["date"][0].split("/")
        start_d = date.fromisoformat(start)
        end_d = date.fromisoformat(end)
        dates = []
        cursor = start_d
        while cursor <= end_d:
            dates.append(cursor.isoformat())
            cursor += timedelta(days=1)
        lat = request["location"]["latitude"]
        lon = request["location"]["longitude"]
        write_synthetic_point_chunk(Path(target), dates, lat, lon, self.kelvin, self.precip_metres)


def patch_timeseries_seed_and_client(monkeypatch, tmp_path: Path, client) -> None:
    from ingestion.weather import load_capitals as real_load_capitals

    seed = write_seed(tmp_path)
    monkeypatch.setattr(cds, "load_capitals", lambda: real_load_capitals(seed))
    monkeypatch.setattr(cds, "_new_client", lambda: client)


def test_timeseries_request_uses_location_point_not_area():
    """The whole point of the ARCO path: one coordinate per request, so the
    server returns a single grid cell instead of a whole area grid."""
    request = cds._timeseries_request(
        MILANO, date(2020, 1, 1), date(2020, 12, 31), ("2m_temperature",)
    )
    assert request["location"] == {"longitude": 9.19, "latitude": 45.4642}
    assert "area" not in request  # must NOT be the bulk area form
    assert request["date"] == ["2020-01-01/2020-12-31"]
    assert request["data_format"] == "netcdf"
    assert request["variable"] == ["2m_temperature"]


def test_timeseries_decade_chunks_split_a_range_into_decades():
    chunks = cds._timeseries_decade_chunks(date(1950, 1, 2), date(2020, 12, 31))
    assert chunks[0] == (date(1950, 1, 2), date(1959, 12, 31))
    assert chunks[1] == (date(1960, 1, 1), date(1969, 12, 31))
    assert chunks[-1] == (date(2020, 1, 1), date(2020, 12, 31))


def test_aggregate_point_to_daily_builds_min_mean_max_and_precip(tmp_path):
    # Two days, each with two hours: 10 C and 20 C -> min 10, mean 15, max 20.
    dates = ["2020-01-01T00:00", "2020-01-01T12:00", "2020-01-02T00:00", "2020-01-02T12:00"]
    path = tmp_path / "milano_2020.nc"
    write_synthetic_point_chunk(path, dates, 45.4642, 9.19, kelvin=283.15, precip_metres=0.001)

    rows = cds._aggregate_point_to_daily(path, "ITC45")

    assert len(rows) == 2
    assert list(rows[0]) == cds.WEATHER_COLUMNS
    assert rows[0]["t_min"] == 10.0
    assert rows[0]["t_mean"] == 10.0
    assert rows[0]["t_max"] == 10.0
    assert rows[0]["precip_sum"] == 2.0  # 2 hourly 0.001 m -> 1000 * 0.002


def test_aggregate_point_to_daily_converts_metres_to_millimetres(tmp_path):
    # 1 mm of precip across the day (0.0005 m twice) -> precip_sum 1.0 mm.
    dates = ["2020-01-01T00:00", "2020-01-01T12:00"]
    path = tmp_path / "milano.nc"
    write_synthetic_point_chunk(path, dates, 45.4642, 9.19, kelvin=283.15, precip_metres=0.0005)
    rows = cds._aggregate_point_to_daily(path, "ITC45")
    assert rows[0]["precip_sum"] == 1.0


def test_aggregate_point_to_daily_keeps_missing_hours_as_none(tmp_path):
    dates = ["2020-01-01T00:00", "2020-01-01T12:00"]
    path = tmp_path / "milano.nc"
    write_synthetic_point_chunk(path, dates, 45.4642, 9.19, kelvin=None, precip_metres=None)
    rows = cds._aggregate_point_to_daily(path, "ITC45")
    assert rows[0]["t_mean"] is None
    assert rows[0]["t_min"] is None
    assert rows[0]["t_max"] is None
    assert rows[0]["precip_sum"] is None


def write_synthetic_point_zip(
    path: Path,
    dates: list[str],
    latitude: float,
    longitude: float,
    kelvin: float | None,
    precip_metres: float | None,
) -> None:
    """A ZIP archive shaped like the REAL Copernicus ARCO time-series response:
    one NetCDF member per requested variable (a 2m-temperature member exposing
    ``t2m``, a total-precipitation member exposing ``tp``). This is the exact
    byte layout ``_read_arco_arrays`` has to decompress and read, so a change
    on the CDS side (or a regression here) is caught offline. Members are
    written to real temp paths (netCDF4 engine), like the rest of this module.
    """
    import zipfile

    def member(dates_: list[str], var: str, values: Any, member_path: Path) -> bytes:
        ds = xr.Dataset(
            {var: (("valid_time",), np.asarray(values, dtype=float))},
            coords={
                "valid_time": np.array(dates_, dtype="datetime64[ns]"),
                "latitude": np.array([latitude]),
                "longitude": np.array([longitude]),
            },
        )
        ds.to_netcdf(member_path)
        return member_path.read_bytes()

    shape = (len(dates),)
    t2m = np.full(shape, np.nan) if kelvin is None else np.full(shape, kelvin)
    tp = np.full(shape, np.nan) if precip_metres is None else np.full(shape, precip_metres)
    with tempfile.TemporaryDirectory(prefix="arco_fixture_") as tmp_dir:
        t2m_nc = Path(tmp_dir) / "t2m.nc"
        tp_nc = Path(tmp_dir) / "tp.nc"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(
                "reanalysis-era5-land-timeseries-sfc-2m-temperatureaudvgq65.nc",
                member(dates, "t2m", t2m, t2m_nc),
            )
            z.writestr(
                "reanalysis-era5-land-timeseries-sfc-pressure-precipitationtcpducsu.nc",
                member(dates, "tp", tp, tp_nc),
            )


def test_aggregate_point_to_daily_reads_the_real_zip_response(tmp_path):
    """The CDS ARCO response is a ZIP of one NetCDF per variable, not a single
    NetCDF. This is the byte format the live test against the real API showed,
    and the fix that makes `refresh-timeseries` work at all."""
    dates = ["2020-01-01T00:00", "2020-01-01T12:00", "2020-01-02T00:00", "2020-01-02T12:00"]
    path = tmp_path / "torino_2020.nc"
    write_synthetic_point_zip(path, dates, 45.0705, 7.6868, kelvin=283.15, precip_metres=0.001)

    rows = cds._aggregate_point_to_daily(path, "ITC11")

    assert len(rows) == 2
    assert list(rows[0]) == cds.WEATHER_COLUMNS
    assert rows[0]["t_min"] == 10.0
    assert rows[0]["t_mean"] == 10.0
    assert rows[0]["t_max"] == 10.0
    assert rows[0]["precip_sum"] == 2.0  # 2 hourly 0.001 m -> 1000 * 0.002


def test_timeseries_cache_path_is_keyed_by_coordinate_and_coverage(tmp_path):
    a = cds._timeseries_cache_path(tmp_path, MILANO, date(1950, 1, 2))
    b = cds._timeseries_cache_path(tmp_path, MILANO, date(1960, 1, 1))
    c = cds._timeseries_cache_path(tmp_path, ROMA, date(1950, 1, 2))
    assert a.name == "ITC45_45.4642_9.1900_1950.nc"
    assert len({a, b, c}) == 3  # different coordinate OR coverage -> different key


def test_timeseries_cache_skips_a_cached_decade(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    client = FakeTimeseriesClient()
    cache = cds._timeseries_cache_path(raw_dir, MILANO, date(2020, 1, 1))
    write_synthetic_point_chunk(cache, ["2020-01-01"], 45.4642, 9.19, 283.15, 0.001)

    rows = cds._fetch_capital_timeseries(
        client, MILANO, date(2020, 1, 1), date(2020, 1, 1), raw_dir
    )

    assert client.calls == []  # never hit the network for a cached decade
    assert rows[0]["province_code"] == "ITC45"
    assert rows[0]["date"] == date(2020, 1, 1)


def test_cmd_refresh_timeseries_full_run_writes_the_shared_snapshot(tmp_path, monkeypatch):
    client = FakeTimeseriesClient()
    patch_timeseries_seed_and_client(monkeypatch, tmp_path, client)

    rc = cds.cmd_refresh_timeseries(2020, 2020, data_dir=tmp_path, today=date(2020, 12, 31))

    assert rc == 0
    df = pl.read_parquet(tmp_path / cds.SNAPSHOT_NAME)
    assert df.columns == cds.WEATHER_COLUMNS
    assert set(df["province_code"].to_list()) == {"ITC45", "ITE43"}
    # One request per capital, each for the single year range.
    assert len(client.calls) == 2
    for name, request in client.calls:
        assert name == cds.TIMESERIES_DATASET_ID
        assert "location" in request


def test_cmd_refresh_timeseries_blocks_write_when_a_capital_is_all_null(tmp_path, monkeypatch):
    client = FakeTimeseriesClient(kelvin=None, precip_metres=None)
    patch_timeseries_seed_and_client(monkeypatch, tmp_path, client)

    rc = cds.cmd_refresh_timeseries(2020, 2020, data_dir=tmp_path, today=date(2020, 12, 31))

    assert rc == 1
    assert not (tmp_path / cds.SNAPSHOT_NAME).exists()


def test_cmd_refresh_timeseries_partial_range_preserves_other_years(tmp_path, monkeypatch):
    from ingestion.weather import write_snapshot as real_write_snapshot

    existing_rows = [
        {
            "province_code": "ITC45",
            "date": date(2015, 6, 1),
            "t_min": 1.0,
            "t_mean": 2.0,
            "t_max": 3.0,
            "precip_sum": None,
        }
    ]
    real_write_snapshot(existing_rows, tmp_path)
    client = FakeTimeseriesClient()
    patch_timeseries_seed_and_client(monkeypatch, tmp_path, client)

    rc = cds.cmd_refresh_timeseries(2020, 2020, data_dir=tmp_path, today=date(2020, 12, 31))

    assert rc == 0
    df = pl.read_parquet(tmp_path / cds.SNAPSHOT_NAME)
    assert date(2015, 6, 1) in df["date"].to_list()  # 2015 survives
    assert date(2020, 1, 1) in df["date"].to_list()  # 2020 added


def test_cmd_refresh_timeseries_rejects_a_backwards_range(tmp_path, monkeypatch):
    client = FakeTimeseriesClient()
    patch_timeseries_seed_and_client(monkeypatch, tmp_path, client)

    rc = cds.cmd_refresh_timeseries(2020, 2010, data_dir=tmp_path)

    assert rc == 2
    assert client.calls == []


def test_cmd_refresh_timeseries_surfaces_an_error_and_writes_nothing(tmp_path, monkeypatch, caplog):
    class FailingTimeseriesClient:
        def retrieve(self, name: str, request: dict, target: str) -> None:
            raise RuntimeError("403 Client Error: required licences not accepted")

    client = FailingTimeseriesClient()
    patch_timeseries_seed_and_client(monkeypatch, tmp_path, client)

    with caplog.at_level("ERROR"):
        rc = cds.cmd_refresh_timeseries(2020, 2020, data_dir=tmp_path, today=date(2020, 12, 31))

    assert rc == 1
    assert not (tmp_path / cds.SNAPSHOT_NAME).exists()
    assert "403" in caplog.text
    assert "NOT written" in caplog.text


def test_retrieve_arco_retries_on_the_queue_limited_error(monkeypatch, tmp_path):
    """A live 4-worker run was rejected with "Number queued requests for this
    dataset is temporarily limited". The retry helper must pause and retry
    that specific rejection (the queue drains in seconds), not fail the
    whole city or hammer it with immediate retries which hit the same door."""
    monkeypatch.setattr(cds, "QUEUE_LIMIT_BACKOFF_S", 0.0)
    sleep_calls: list[float] = []
    monkeypatch.setattr("time.sleep", lambda s: sleep_calls.append(s))

    class QueueLimitedClient:
        def __init__(self):
            self.calls = 0

        def retrieve(self, name: str, request: dict, target: str) -> None:
            self.calls += 1
            if self.calls < 3:
                raise RuntimeError(
                    "HTTPError('400 Client Error: Bad Request ... The job has been "
                    "rejected\nNumber queued requests for this dataset is temporarily "
                    "limited. Please configure your scripts accordingly')"
                )
            Path(target).write_bytes(b"ok")

    client = QueueLimitedClient()
    out = tmp_path / "chunk.nc"
    cds._retrieve_arco_with_retry(client, {"variable": ["2m_temperature"]}, out, "label")

    assert client.calls == 3  # two rejections, then success
    assert len(sleep_calls) == 2  # one backoff between each retry
    assert out.exists()  # the successful download landed on the target


def test_retrieve_arco_does_not_retry_a_non_queue_error(tmp_path):
    """A 403 (licence not accepted) is a genuine bad request, not a queue
    squeeze: retrying it is guaranteed to fail the same way, so it must raise
    immediately rather than burn the retry budget."""

    class LicenceClient:
        def retrieve(self, name: str, request: dict, target: str) -> None:
            raise RuntimeError("403 Client Error: required licences not accepted")

    out = tmp_path / "chunk.nc"
    with pytest.raises(RuntimeError, match="403"):
        cds._retrieve_arco_with_retry(LicenceClient(), {}, out, "label")
    assert not out.exists()  # a failed request leaves nothing to look cached


def test_is_queue_limit_error_matches_only_the_specific_phrase():
    assert (
        cds._is_queue_limit_error(
            RuntimeError("Number queued requests for this dataset is temporarily limited")
        )
        is True
    )
    assert cds._is_queue_limit_error(RuntimeError("403 required licences")) is False
    assert cds._is_queue_limit_error(RuntimeError("something else")) is False


def test_main_dispatches_refresh_timeseries_with_two_years(monkeypatch):
    calls: list[tuple] = []

    def fake_cmd_refresh_timeseries(start_year=None, end_year=None, **kwargs):
        calls.append((start_year, end_year))
        return 0

    monkeypatch.setattr(cds, "cmd_refresh_timeseries", fake_cmd_refresh_timeseries)
    rc = cds.main(["refresh-timeseries", "1950", "1960"])

    assert rc == 0
    assert calls == [(1950, 1960)]


def test_main_dispatches_refresh_timeseries_with_no_args(monkeypatch):
    calls: list[tuple] = []

    def fake_cmd_refresh_timeseries(**kwargs):
        calls.append(kwargs)
        return 0

    monkeypatch.setattr(cds, "cmd_refresh_timeseries", fake_cmd_refresh_timeseries)
    rc = cds.main(["refresh-timeseries"])

    assert rc == 0
    assert calls == [{}]


def test_main_prints_usage_for_unknown_command(capsys):
    rc = cds.main(["bogus-command"])
    assert rc == 2
    assert "python -m ingestion.cds" in capsys.readouterr().out
