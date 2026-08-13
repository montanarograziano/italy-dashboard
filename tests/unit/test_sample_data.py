"""Unit tests for the synthetic sample-data generator."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from ingestion.fetch import NORMALIZED_COLUMNS
from ingestion.sample_data import generate_all
from ingestion.weather import SNAPSHOT_NAME

EXPECTED_DATASETS = {
    "crime_reported",
    "population_resident",
    "population_foreign",
    "labor_unemployment",
    "economy_inflation",
    "income_regional",
}


def test_generates_all_datasets_with_normalized_schema(tmp_path: Path):
    generate_all(tmp_path, seed=7)
    # weather_daily.parquet is generated alongside the six normalized
    # datasets but has its own (deliberately different) schema — excluded
    # here and covered separately by the weather-specific tests below.
    parquet_files = [p for p in tmp_path.glob("*.parquet") if p.name != SNAPSHOT_NAME]
    files = {p.stem for p in parquet_files}
    assert files == EXPECTED_DATASETS
    for p in parquet_files:
        df = pl.read_parquet(p)
        assert df.columns == NORMALIZED_COLUMNS, p.name
        assert df.height > 0, p.name
        assert df["value"].dtype == pl.Float64, p.name


def test_generation_is_deterministic_for_same_seed(tmp_path: Path):
    a_dir, b_dir = tmp_path / "a", tmp_path / "b"
    generate_all(a_dir, seed=42)
    generate_all(b_dir, seed=42)
    a = pl.read_parquet(a_dir / "crime_reported.parquet")
    b = pl.read_parquet(b_dir / "crime_reported.parquet")
    assert a.equals(b)


def test_counts_are_non_negative(tmp_path: Path):
    generate_all(tmp_path, seed=3)
    for name in ("crime_reported", "population_resident", "population_foreign"):
        df = pl.read_parquet(tmp_path / f"{name}.parquet")
        assert (df["value"] >= 0).all(), name


def test_sample_weather_covers_20_capitals_with_a_north_south_gradient(tmp_path):
    from ingestion import sample_data, weather

    out = sample_data.generate_weather_parquet(tmp_path, seed=99)
    df = pl.read_parquet(out)

    assert out.name == weather.SNAPSHOT_NAME
    assert df.columns == weather.WEATHER_COLUMNS
    assert df["province_code"].n_unique() == 20
    assert df["t_mean"].null_count() == 0
    # min <= mean <= max must hold on every day, or the marts are meaningless
    assert (df["t_min"] <= df["t_mean"]).all()
    assert (df["t_mean"] <= df["t_max"]).all()

    # Palermo must be warmer on average than Torino.
    means = df.group_by("province_code").agg(pl.col("t_mean").mean().alias("m"))
    by_code = dict(zip(means["province_code"], means["m"], strict=True))
    assert by_code["ITG12"] > by_code["ITC11"]


def test_generate_all_writes_the_weather_snapshot(tmp_path):
    from ingestion import sample_data, weather

    sample_data.generate_all(tmp_path, seed=99)
    assert (tmp_path / weather.SNAPSHOT_NAME).exists()


def test_sample_offenders_include_violent_crime_codes(tmp_path):
    from ingestion import sample_data

    out = sample_data.generate_raw_offenders_csv(tmp_path, seed=99)
    text = out.read_text()
    assert "INTENHOM: intentional homicides" in text
    assert "BLOWS: blows" in text
