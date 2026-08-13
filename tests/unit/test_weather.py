"""Unit tests for weather chunking, parsing, the null gate and the snapshot."""

from __future__ import annotations

import csv
from datetime import date
from itertools import pairwise
from pathlib import Path

import polars as pl
import pytest

from ingestion import weather
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
    }
    assert len(rows) == 2


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
