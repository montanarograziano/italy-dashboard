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


@pytest.fixture(scope="session")
def _climate_snapshot(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Session-scoped: one synthetic snapshot, one `dbt build`, shared by every
    climate test.

    `dbt build` is a subprocess that takes real wall-clock time. Rebuilding it
    per-test (function scope) multiplies that cost by the number of climate
    tests for no benefit, since none of them mutate the snapshot. Session
    scope amortizes it to a single build for the whole run.

    `monkeypatch` is function-scoped by design (it undoes itself after each
    test) and cannot be requested from a session-scoped fixture, which is why
    this is split from `climate_db` below: this fixture only produces data on
    disk, the function-scoped one does the patching.
    """
    import os
    import subprocess

    root = Path(__file__).resolve().parent.parent
    data_dir = tmp_path_factory.mktemp("climate_data")
    generate_all(data_dir, seed=1234)
    (data_dir / "marts").mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["uv", "run", "dbt", "build", "--project-dir", "dbt", "--profiles-dir", "dbt"],
        cwd=root,
        env={**os.environ, "ITALY_DATA_DIR": str(data_dir)},
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return data_dir


@pytest.fixture
def climate_db(_climate_snapshot: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the query layer at the session's pre-built climate snapshot."""
    monkeypatch.setattr(queries, "DATA_DIR", _climate_snapshot)
    monkeypatch.setattr(queries, "MARTS_DIR", _climate_snapshot / "marts")
    return _climate_snapshot
