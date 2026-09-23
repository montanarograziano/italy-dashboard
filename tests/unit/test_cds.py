"""Unit tests for the ARCO CDS fetcher: request shape, cache, aggregation, gates, all offline.

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
from ingestion.weather import WEATHER_COLUMNS, Capital, WeatherError

np = pytest.importorskip("numpy", reason="needs the `cds` extra: uv sync --extra cds")
xr = pytest.importorskip("xarray", reason="needs the `cds` extra: uv sync --extra cds")
pytest.importorskip("cdsapi", reason="needs the `cds` extra: uv sync --extra cds")

MILANO = Capital("ITC45", "Milano", 45.4642, 9.19)
ROMA = Capital("ITE43", "Roma", 41.8933, 12.4829)


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


def test_cds_error_is_a_weather_error():
    """CDSError must be catchable wherever WeatherError already is."""
    assert issubclass(CDSError, WeatherError)


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
    rc = cds.main(["refresh-timeseries", "1950"])
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
    assert list(rows[0]) == WEATHER_COLUMNS
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
    assert list(rows[0]) == WEATHER_COLUMNS
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


def test_timeseries_cache_skips_a_cached_closed_decade(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    client = FakeTimeseriesClient()
    cache = cds._timeseries_cache_path(raw_dir, MILANO, date(2010, 1, 1))
    write_synthetic_point_chunk(cache, ["2010-01-01"], 45.4642, 9.19, 283.15, 0.001)

    rows = cds._fetch_capital_timeseries(
        client, MILANO, date(2010, 1, 1), date(2020, 1, 1), raw_dir
    )

    requested = [request["date"][0] for _, request in client.calls]
    assert requested == ["2020-01-01/2020-01-01"]  # only the open decade
    assert rows[0]["province_code"] == "ITC45"
    assert rows[0]["date"] == date(2010, 1, 1)


def test_timeseries_cache_refetches_the_open_decade(tmp_path):
    """The current decade grows every day: replaying its cache would freeze
    the snapshot at the first backfill's end date forever."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    client = FakeTimeseriesClient(kelvin=293.15)
    cache = cds._timeseries_cache_path(raw_dir, MILANO, date(2020, 1, 1))
    write_synthetic_point_chunk(cache, ["2020-01-01"], 45.4642, 9.19, 283.15, 0.001)

    rows = cds._fetch_capital_timeseries(
        client, MILANO, date(2020, 1, 1), date(2020, 1, 2), raw_dir
    )

    assert [request["date"][0] for _, request in client.calls] == ["2020-01-01/2020-01-02"]
    assert [r["date"] for r in rows] == [date(2020, 1, 1), date(2020, 1, 2)]
    assert rows[0]["t_mean"] == pytest.approx(20.0)


def test_cmd_refresh_timeseries_clips_1950_to_the_first_published_day(tmp_path, monkeypatch):
    """The dataset starts 1950-01-02; asking for 1950-01-01 is rejected."""
    client = FakeTimeseriesClient()
    patch_timeseries_seed_and_client(monkeypatch, tmp_path, client)

    rc = cds.cmd_refresh_timeseries(1950, 1950, data_dir=tmp_path, today=date(2020, 12, 31))

    assert rc == 0
    assert {request["date"][0] for _, request in client.calls} == {"1950-01-02/1950-12-31"}


def test_cmd_refresh_timeseries_full_run_writes_the_shared_snapshot(tmp_path, monkeypatch):
    client = FakeTimeseriesClient()
    patch_timeseries_seed_and_client(monkeypatch, tmp_path, client)

    rc = cds.cmd_refresh_timeseries(2020, 2020, data_dir=tmp_path, today=date(2020, 12, 31))

    assert rc == 0
    df = pl.read_parquet(tmp_path / cds.SNAPSHOT_NAME)
    assert df.columns == WEATHER_COLUMNS
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
    calls: list[dict] = []

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
