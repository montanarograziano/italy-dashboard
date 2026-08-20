"""Unit tests for weather chunking, parsing, the null gate and the snapshot."""

from __future__ import annotations

import csv
import json
import logging
from datetime import date, timedelta
from itertools import pairwise
from pathlib import Path

import polars as pl
import pytest

from ingestion import weather
from ingestion.openmeteo import OpenMeteoClient, OpenMeteoError
from ingestion.weather import Capital, WeatherError


def write_seed(tmp_path: Path) -> Path:
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


def test_load_capitals_reads_codes_and_coordinates(tmp_path):
    caps = weather.load_capitals(write_seed(tmp_path))
    assert [c.province_code for c in caps] == ["ITC45", "ITE43"]
    assert caps[0] == Capital("ITC45", "Milano", 45.4642, 9.19)


def test_decade_chunks_cover_the_range_without_gaps_or_overlap():
    chunks = weather.decade_chunks(date(1950, 1, 1), date(1971, 6, 15))
    assert chunks[0] == (date(1950, 1, 1), date(1959, 12, 31))
    assert chunks[1] == (date(1960, 1, 1), date(1969, 12, 31))
    assert chunks[-1] == (date(1970, 1, 1), date(1971, 6, 15))
    for (_, prev_end), (next_start, _) in pairwise(chunks):
        assert (next_start - prev_end).days == 1


def test_decade_chunks_handles_a_range_inside_one_decade():
    assert weather.decade_chunks(date(2021, 3, 1), date(2024, 5, 2)) == [
        (date(2021, 3, 1), date(2024, 5, 2))
    ]


def test_payload_to_rows_pairs_dates_with_values():
    payload = {
        "time": ["1950-01-01", "1950-01-02"],
        "t_max": [11.4, 12.0],
        "t_min": [2.1, 3.0],
        "t_mean": [6.5, 7.2],
    }
    rows = weather.payload_to_rows("ITE43", payload)
    assert rows[0] == {
        "province_code": "ITE43",
        "date": date(1950, 1, 1),
        "t_min": 2.1,
        "t_mean": 6.5,
        "t_max": 11.4,
        "precip_sum": None,
    }
    assert len(rows) == 2


def test_payload_to_rows_defaults_missing_precip_to_none_for_legacy_cache():
    """Raw cache written before precip_sum existed has no such key at all;
    it must still normalize (temperature-only), not error."""
    payload = {
        "time": ["1950-01-01"],
        "t_max": [11.4],
        "t_min": [2.1],
        "t_mean": [6.5],
    }
    rows = weather.payload_to_rows("ITE43", payload)
    assert rows[0]["precip_sum"] is None


def test_payload_to_rows_parses_precip_when_present():
    payload = {
        "time": ["1950-01-01", "1950-01-02"],
        "t_max": [11.4, 12.0],
        "t_min": [2.1, 3.0],
        "t_mean": [6.5, 7.2],
        "precip_sum": [0.0, 4.5],
    }
    rows = weather.payload_to_rows("ITE43", payload)
    assert [r["precip_sum"] for r in rows] == [0.0, 4.5]


def test_payload_to_rows_rejects_a_ragged_precip_array():
    payload = {
        "time": ["1950-01-01", "1950-01-02"],
        "t_max": [1.0, 1.0],
        "t_min": [0.0, 0.0],
        "t_mean": [0.5, 0.5],
        "precip_sum": [1.0],
    }
    with pytest.raises(WeatherError, match="precip_sum length mismatch"):
        weather.payload_to_rows("ITE43", payload)


def test_payload_to_rows_rejects_ragged_arrays():
    payload = {
        "time": ["1950-01-01", "1950-01-02"],
        "t_max": [1.0],
        "t_min": [0.0],
        "t_mean": [0.5],
    }
    with pytest.raises(WeatherError, match="length mismatch"):
        weather.payload_to_rows("ITE43", payload)


def test_null_rate_counts_days_with_a_missing_mean():
    rows = [
        {"province_code": "X", "date": date(1950, 1, 1), "t_min": 1.0, "t_mean": 2.0, "t_max": 3.0},
        {
            "province_code": "X",
            "date": date(1950, 1, 2),
            "t_min": None,
            "t_mean": None,
            "t_max": None,
        },
    ]
    assert weather.null_rate(rows) == 0.5
    assert weather.null_rate([]) == 1.0


def test_write_snapshot_produces_the_expected_schema(tmp_path):
    rows = [
        {
            "province_code": "ITE43",
            "date": date(1950, 1, 1),
            "t_min": 2.1,
            "t_mean": 6.5,
            "t_max": 11.4,
        }
    ]
    out = weather.write_snapshot(rows, tmp_path)
    assert out == tmp_path / "weather_daily.parquet"
    df = pl.read_parquet(out)
    assert df.columns == weather.WEATHER_COLUMNS
    assert df.height == 1
    assert df["t_mean"].dtype == pl.Float64
    assert df["date"].dtype == pl.Date


def test_write_snapshot_is_atomic_and_leaves_no_tmp_file(tmp_path):
    rows = [
        {
            "province_code": "ITE43",
            "date": date(1950, 1, 1),
            "t_min": 2.1,
            "t_mean": 6.5,
            "t_max": 11.4,
        }
    ]
    weather.write_snapshot(rows, tmp_path)
    assert not list(tmp_path.glob("*.tmp"))


def test_placeholder_snapshot_has_the_same_schema_and_no_rows(tmp_path):
    out = weather.ensure_weather_placeholder(tmp_path)
    df = pl.read_parquet(out)
    assert df.columns == weather.WEATHER_COLUMNS
    assert df.height == 0


def test_placeholder_never_overwrites_a_real_snapshot(tmp_path):
    rows = [
        {
            "province_code": "ITE43",
            "date": date(1950, 1, 1),
            "t_min": 2.1,
            "t_mean": 6.5,
            "t_max": 11.4,
        }
    ]
    weather.write_snapshot(rows, tmp_path)
    weather.ensure_weather_placeholder(tmp_path)
    assert pl.read_parquet(tmp_path / "weather_daily.parquet").height == 1


# --------------------------------------------------------------------------
# cmd_refresh: the null gate and the single-city merge, fully offline.
#
# OpenMeteoClient is imported by name into ingestion.weather's module
# namespace, so it can be swapped for a fake async context manager without
# touching any production signature. The fake is keyed by (lat, lon) so each
# capital in the temp seed gets its own canned response regardless of which
# decade chunk is being requested.
# --------------------------------------------------------------------------


def clean_payload(dates: list[str], t_mean: float = 10.0) -> dict:
    return {
        "time": dates,
        "t_min": [t_mean - 5] * len(dates),
        "t_mean": [t_mean] * len(dates),
        "t_max": [t_mean + 5] * len(dates),
    }


def all_null_payload(dates: list[str]) -> dict:
    return {
        "time": dates,
        "t_min": [None] * len(dates),
        "t_mean": [None] * len(dates),
        "t_max": [None] * len(dates),
    }


def make_fake_client(responses: dict[tuple[float, float], dict]) -> type:
    """A class standing in for OpenMeteoClient, returning canned payloads by coordinate."""

    class FakeOpenMeteoClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def daily_temperatures(self, lat, lon, start, end):
            return responses[(lat, lon)]

    return FakeOpenMeteoClient


def patch_capitals_and_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, responses: dict[tuple[float, float], dict]
) -> None:
    """Point cmd_refresh at the temp seed and a fake client, with no real network delay."""
    seed = write_seed(tmp_path)
    real_load_capitals = weather.load_capitals
    monkeypatch.setattr(weather, "load_capitals", lambda: real_load_capitals(seed))
    monkeypatch.setattr(weather, "OpenMeteoClient", make_fake_client(responses))
    monkeypatch.setattr(weather, "REQUEST_DELAY_S", 0)


MILANO_COORD = (45.4642, 9.19)
ROMA_COORD = (41.8933, 12.4829)


async def test_cmd_refresh_full_writes_every_city(tmp_path, monkeypatch):
    responses = {
        MILANO_COORD: clean_payload(["2020-01-01", "2020-01-02"]),
        ROMA_COORD: clean_payload(["2020-01-01", "2020-01-02"]),
    }
    patch_capitals_and_client(monkeypatch, tmp_path, responses)

    rc = await weather.cmd_refresh(None, data_dir=tmp_path)

    assert rc == 0
    df = pl.read_parquet(tmp_path / weather.SNAPSHOT_NAME)
    assert set(df["province_code"].to_list()) == {"ITC45", "ITE43"}


async def test_cmd_refresh_blocks_write_when_a_city_exceeds_the_null_limit(tmp_path, monkeypatch):
    responses = {
        MILANO_COORD: all_null_payload(["2020-01-01", "2020-01-02"]),  # ITC45: fails the gate
        ROMA_COORD: clean_payload(["2020-01-01", "2020-01-02"]),  # ITE43: clean
    }
    patch_capitals_and_client(monkeypatch, tmp_path, responses)

    rc = await weather.cmd_refresh(None, data_dir=tmp_path)

    assert rc == 1
    # A tainted city must block the write entirely: no partial/wrong snapshot,
    # not even for the clean city, since there was nothing on disk before.
    assert not (tmp_path / weather.SNAPSHOT_NAME).exists()


async def test_cmd_refresh_single_city_merges_into_existing_snapshot(tmp_path, monkeypatch):
    existing_rows = [
        {
            "province_code": "ITC45",
            "date": date(2019, 1, 1),
            "t_min": 1.0,
            "t_mean": 2.0,
            "t_max": 3.0,
        },
        {
            "province_code": "ITE43",
            "date": date(2019, 1, 1),
            "t_min": 4.0,
            "t_mean": 5.0,
            "t_max": 6.0,
        },
    ]
    weather.write_snapshot(existing_rows, tmp_path)

    # Only ITC45 gets refetched, with a new date and a new value.
    responses = {MILANO_COORD: clean_payload(["2020-06-01"], t_mean=99.0)}
    patch_capitals_and_client(monkeypatch, tmp_path, responses)

    rc = await weather.cmd_refresh("ITC45", data_dir=tmp_path)

    assert rc == 0
    df = pl.read_parquet(tmp_path / weather.SNAPSHOT_NAME)

    # ITE43 must survive untouched: a single-city refresh must not destroy it.
    roma = df.filter(pl.col("province_code") == "ITE43")
    assert roma.to_dicts() == [
        {
            "province_code": "ITE43",
            "date": date(2019, 1, 1),
            "t_min": 4.0,
            "t_mean": 5.0,
            "t_max": 6.0,
            "precip_sum": None,
        }
    ]

    # ITC45's stale 2019 row must be gone, replaced by the refetched value.
    milano = df.filter(pl.col("province_code") == "ITC45")
    assert date(2019, 1, 1) not in milano["date"].to_list()
    assert set(milano["date"].to_list()) == {date(2020, 6, 1)}
    assert milano["t_mean"].to_list()[0] == 99.0


async def test_cmd_refresh_single_city_without_existing_snapshot(tmp_path, monkeypatch):
    responses = {MILANO_COORD: clean_payload(["2020-01-01"])}
    patch_capitals_and_client(monkeypatch, tmp_path, responses)

    rc = await weather.cmd_refresh("ITC45", data_dir=tmp_path)

    assert rc == 0
    df = pl.read_parquet(tmp_path / weather.SNAPSHOT_NAME)
    assert set(df["province_code"].to_list()) == {"ITC45"}


# --------------------------------------------------------------------------
# The raw cache: keyed by coordinate, and safe to resume from.
# --------------------------------------------------------------------------


class RecordingClient(OpenMeteoClient):
    """Fake client recording every chunk it is asked to download.

    Subclasses the real client (and never opens a connection) so it is a
    genuine stand-in wherever an OpenMeteoClient is expected. Returns the
    latitude as the temperature, so a value in the output identifies which
    coordinate produced it.
    """

    def __init__(self, fail_after: int | None = None):
        super().__init__()
        self.calls: list[tuple[float, float, int]] = []
        self._fail_after = fail_after

    async def __aenter__(self) -> RecordingClient:
        return self

    async def __aexit__(self, *exc_info) -> None:
        return None

    async def daily_temperatures(
        self, lat: float, lon: float, start: date, end: date
    ) -> dict[str, list]:
        if self._fail_after is not None and len(self.calls) >= self._fail_after:
            raise OpenMeteoError("HTTP 429: Daily API request limit exceeded")
        self.calls.append((lat, lon, start.year))
        return clean_payload([f"{start.year}-01-01"], t_mean=lat)


def test_cache_path_is_keyed_by_coordinates(tmp_path):
    """Two coordinates for the same province must not share a cache entry."""
    here = weather._cache_path(tmp_path, "ITC45", 45.4642, 9.19, date(1950, 1, 1))
    moved = weather._cache_path(tmp_path, "ITC45", 45.5000, 9.19, date(1950, 1, 1))
    assert here != moved
    assert here.name == "ITC45_45.4642_9.1900_1950.json"


async def test_moving_a_city_refetches_instead_of_replaying_the_old_point(tmp_path, monkeypatch):
    """The null gate tells operators to nudge a city inland and refetch it.

    If the cache ignored coordinates, that refetch would replay the OLD point's
    decades and download only the current one at the NEW point, splicing two
    locations into one series and faking a step change in the trend.
    """
    monkeypatch.setattr(weather, "REQUEST_DELAY_S", 0)
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    end = date(1965, 6, 30)  # two decade chunks: 1950s, plus a clipped 1960s
    original = Capital("ITC45", "Milano", 45.4642, 9.19)
    moved = Capital("ITC45", "Milano", 45.5000, 9.19)

    first = RecordingClient()
    await weather._fetch_capital(first, original, end, raw_dir)

    after_move = RecordingClient()
    rows = await weather._fetch_capital(after_move, moved, end, raw_dir)

    # Every decade came from the new coordinate: no cache hit on the old one.
    assert len(after_move.calls) == len(first.calls) == 2
    assert {r["t_mean"] for r in rows} == {45.5}

    # And the new coordinate's own cache IS reused on a re-run: only the
    # current (still-growing) decade is fetched again.
    resumed = RecordingClient()
    await weather._fetch_capital(resumed, moved, end, raw_dir)
    assert [c[2] for c in resumed.calls] == [1960]


async def test_an_aborted_run_keeps_its_cache_and_resumes(tmp_path, monkeypatch):
    """A rate limit mid-backfill must cost nothing but the current chunk.

    A full backfill exceeds the free tier's daily quota, so stopping partway is
    the normal path. Discarding the decades already downloaded would make a
    multi-day job impossible.
    """
    seed = write_seed(tmp_path)
    real_load_capitals = weather.load_capitals
    monkeypatch.setattr(weather, "load_capitals", lambda: real_load_capitals(seed))
    monkeypatch.setattr(weather, "REQUEST_DELAY_S", 0)

    aborted = RecordingClient(fail_after=3)
    monkeypatch.setattr(weather, "OpenMeteoClient", lambda: aborted)
    rc = await weather.cmd_refresh(None, data_dir=tmp_path)

    assert rc == 1
    # Nothing was published, but the three downloaded decades are on disk.
    assert not (tmp_path / weather.SNAPSHOT_NAME).exists()
    cached = sorted(p.name for p in (tmp_path / "raw" / "weather").glob("*.json"))
    assert len(cached) == 3
    assert not list((tmp_path / "raw" / "weather").glob("*.tmp"))

    resumed = RecordingClient()
    monkeypatch.setattr(weather, "OpenMeteoClient", lambda: resumed)
    rc = await weather.cmd_refresh(None, data_dir=tmp_path)

    assert rc == 0
    # The cached decades were not downloaded a second time.
    milano_decades = [year for lat, _, year in resumed.calls if lat == 45.4642]
    assert [c[2] for c in aborted.calls] == [1950, 1960, 1970]
    assert 1950 not in milano_decades and 1960 not in milano_decades
    assert set(pl.read_parquet(tmp_path / weather.SNAPSHOT_NAME)["province_code"]) == {
        "ITC45",
        "ITE43",
    }


# --------------------------------------------------------------------------
# cmd_normalize: assembling a snapshot from the raw cache alone, offline.
# --------------------------------------------------------------------------


def _expected_starts() -> list[date]:
    end = date.today() - timedelta(days=weather.PUBLICATION_LAG_DAYS)
    return [start for start, _ in weather.decade_chunks(weather.START_DATE, end)]


def _write_cache(raw_dir: Path, cap: Capital, start: date, payload: dict) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    cache = weather._cache_path(raw_dir, cap.province_code, cap.lat, cap.lon, start)
    cache.write_text(json.dumps(payload))


def _patch_capitals(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Capital, Capital]:
    seed = write_seed(tmp_path)
    real_load_capitals = weather.load_capitals
    monkeypatch.setattr(weather, "load_capitals", lambda: real_load_capitals(seed))
    return Capital("ITC45", "Milano", *MILANO_COORD), Capital("ITE43", "Roma", *ROMA_COORD)


def test_cmd_normalize_includes_a_city_with_every_decade_cached(tmp_path, monkeypatch):
    milano, roma = _patch_capitals(monkeypatch, tmp_path)
    raw_dir = tmp_path / "raw" / "weather"
    for start in _expected_starts():
        _write_cache(raw_dir, milano, start, clean_payload([f"{start.year}-06-01"]))
        _write_cache(raw_dir, roma, start, clean_payload([f"{start.year}-06-01"]))

    rc = weather.cmd_normalize(data_dir=tmp_path)

    assert rc == 0
    df = pl.read_parquet(tmp_path / weather.SNAPSHOT_NAME)
    assert set(df["province_code"].to_list()) == {"ITC45", "ITE43"}


def test_cmd_normalize_excludes_a_city_missing_one_decade(tmp_path, monkeypatch, caplog):
    milano, roma = _patch_capitals(monkeypatch, tmp_path)
    raw_dir = tmp_path / "raw" / "weather"
    starts = _expected_starts()
    for start in starts:
        _write_cache(raw_dir, roma, start, clean_payload([f"{start.year}-06-01"]))
    for start in starts[:-1]:  # Milano is missing its most recent decade chunk
        _write_cache(raw_dir, milano, start, clean_payload([f"{start.year}-06-01"]))

    with caplog.at_level(logging.INFO):
        rc = weather.cmd_normalize(data_dir=tmp_path)

    assert rc == 0
    df = pl.read_parquet(tmp_path / weather.SNAPSHOT_NAME)
    assert set(df["province_code"].to_list()) == {"ITE43"}
    assert "ITC45" in caplog.text  # the summary names the skipped city


def test_cmd_normalize_excludes_a_city_that_breaches_the_null_gate(tmp_path, monkeypatch, caplog):
    milano, roma = _patch_capitals(monkeypatch, tmp_path)
    raw_dir = tmp_path / "raw" / "weather"
    for start in _expected_starts():
        _write_cache(raw_dir, milano, start, all_null_payload([f"{start.year}-06-01"]))
        _write_cache(raw_dir, roma, start, clean_payload([f"{start.year}-06-01"]))

    with caplog.at_level(logging.INFO):
        rc = weather.cmd_normalize(data_dir=tmp_path)

    assert rc == 0
    df = pl.read_parquet(tmp_path / weather.SNAPSHOT_NAME)
    assert set(df["province_code"].to_list()) == {"ITE43"}
    assert "ITC45" in caplog.text  # the summary names the null-gated city


def test_cmd_normalize_empty_cache_returns_nonzero_and_writes_nothing(tmp_path, monkeypatch):
    _patch_capitals(monkeypatch, tmp_path)

    rc = weather.cmd_normalize(data_dir=tmp_path)

    assert rc == 1
    assert not (tmp_path / weather.SNAPSHOT_NAME).exists()


def test_cmd_normalize_snapshot_matches_weather_columns(tmp_path, monkeypatch):
    milano, _roma = _patch_capitals(monkeypatch, tmp_path)
    raw_dir = tmp_path / "raw" / "weather"
    for start in _expected_starts():
        _write_cache(raw_dir, milano, start, clean_payload([f"{start.year}-06-01"]))

    rc = weather.cmd_normalize(data_dir=tmp_path)

    assert rc == 0
    df = pl.read_parquet(tmp_path / weather.SNAPSHOT_NAME)
    assert df.columns == weather.WEATHER_COLUMNS
