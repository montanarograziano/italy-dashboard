"""Integration: the dbt project builds mart_crime from a synthetic raw CSV."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import polars as pl
import pytest

from ingestion.sample_data import generate_all
from italy_dashboard import queries as q

pytestmark = pytest.mark.integration

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def test_dbt_builds_crime_mart_from_raw_csv(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    generate_all(data_dir, seed=7)  # raw CSVs + normalized parquet snapshots
    (data_dir / "marts").mkdir(parents=True)

    result = subprocess.run(
        ["uv", "run", "dbt", "build", "--project-dir", "dbt", "--profiles-dir", "dbt"],
        cwd=PROJECT_ROOT,
        env={**os.environ, "ITALY_DATA_DIR": str(data_dir)},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    mart = data_dir / "marts" / "mart_crime.parquet"
    assert mart.exists()
    df = pl.read_parquet(mart)
    assert df["region_name"].n_unique() == 13  # 12 regions + Italy total
    assert df["sex_name"].n_unique() == 3
    assert df["age_name"].n_unique() == 5

    # And the dashboard query layer can slice it.
    monkeypatch.setattr(q, "DATA_DIR", data_dir)
    monkeypatch.setattr(q, "MARTS_DIR", data_dir / "marts")
    assert q.crime_mart_ready()
    sel = dict.fromkeys(["region", "offence", "sex", "age"], q.ALL)
    assert q.crime_trend(sel)
    rows, labels = q.crime_trend_pivot(sel, "sex")
    assert labels == ["males", "females"]
    assert rows and {"period", "s1", "s2"} <= set(rows[0])

    # Idempotency: a second build over the same inputs must not error,
    # duplicate, or change any mart (pure overwrites, no appends).
    counts_before = {
        p.name: pl.read_parquet(p).height for p in (data_dir / "marts").glob("*.parquet")
    }
    result2 = subprocess.run(
        ["uv", "run", "dbt", "build", "--project-dir", "dbt", "--profiles-dir", "dbt"],
        cwd=PROJECT_ROOT,
        env={**os.environ, "ITALY_DATA_DIR": str(data_dir)},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result2.returncode == 0, result2.stdout + result2.stderr
    counts_after = {
        p.name: pl.read_parquet(p).height for p in (data_dir / "marts").glob("*.parquet")
    }
    assert counts_after == counts_before

    # --- offenders mart: citizenship dimension, hidden totals, rates ---
    assert (data_dir / "marts" / "mart_offenders.parquet").exists()
    off_sel = dict.fromkeys(q.OFFENDERS_MART[1], q.ALL)
    options = q.mart_options(q.OFFENDERS_MART)
    assert options["citizenship"] == [q.ALL, "foreign", "italian"]
    # the hidden 'TOT: total' crime row must be flagged, never listed or summed
    assert "total" not in options["crime"]
    _, cit_labels = q.mart_trend_pivot(q.OFFENDERS_MART, off_sel, "citizenship")
    assert cit_labels == ["italian", "foreign"]

    # summing crime details must EXCLUDE the hidden grand-total row:
    # trend(all) == sum of the five real crime types, not double it
    import duckdb

    mart = data_dir / "marts" / "mart_offenders.parquet"
    con = duckdb.connect()
    row = con.execute(
        f"""
        SELECT SUM(CASE WHEN NOT crime_is_total THEN value END),
               SUM(value)
        FROM read_parquet('{mart}')
        WHERE region_is_total AND sex_is_total AND age_is_total AND citizenship_is_total
          AND year = '2023'
        """
    ).fetchone()
    assert row is not None
    real_sum, with_tot = row
    assert real_sum is not None and with_tot is not None
    assert real_sum < with_tot  # the TOT row exists but is flagged out

    # rates mart still joins population correctly
    assert (data_dir / "marts" / "mart_offender_rates.parquet").exists()
    rates = q.offender_rates(q.ALL, q.ALL)
    assert rates and any(r["s1"] for r in rates)
