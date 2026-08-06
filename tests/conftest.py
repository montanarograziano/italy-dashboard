"""Shared fixtures: isolated data dirs and a DuckDB built from synthetic data."""

from __future__ import annotations

from pathlib import Path

import pytest

from ingestion import fetch
from ingestion.sample_data import generate_all
from italy_dashboard import queries


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the ingestion layer to a temp data directory."""
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setattr(fetch, "DATA_DIR", d)
    monkeypatch.setattr(fetch, "RAW_DIR", d / "raw")
    return d


@pytest.fixture
def sample_db(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Full synthetic snapshot (parquet files), wired into the query layer."""
    generate_all(data_dir, seed=1234)
    monkeypatch.setattr(queries, "DATA_DIR", data_dir)
    monkeypatch.setattr(queries, "MARTS_DIR", data_dir / "marts")
    return data_dir


@pytest.fixture
def missing_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the query layer at a directory with no snapshot."""
    d = tmp_path / "nope"
    d.mkdir()
    monkeypatch.setattr(queries, "DATA_DIR", d)
    monkeypatch.setattr(queries, "MARTS_DIR", d / "marts")
    return d
