"""Unit tests for the synthetic sample-data generator."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from ingestion.fetch import NORMALIZED_COLUMNS
from ingestion.sample_data import generate_all

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
    files = {p.stem for p in tmp_path.glob("*.parquet")}
    assert files == EXPECTED_DATASETS
    for p in tmp_path.glob("*.parquet"):
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
