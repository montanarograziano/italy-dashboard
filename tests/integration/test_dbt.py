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

    # region picker lists regions only; provinces live in their own dropdown,
    # cascading from the selected region by NUTS code prefix
    assert "Milano" not in options["region"] and "Italy" not in options["region"]
    assert q.mart_province_options(q.OFFENDERS_MART) == [q.ALL, "Milano", "Varese"]
    assert q.mart_province_options(q.OFFENDERS_MART, "Lombardia") == [q.ALL, "Milano", "Varese"]
    assert q.mart_province_options(q.OFFENDERS_MART, "Lazio") == [q.ALL]
    prov = q.mart_trend(
        q.OFFENDERS_MART, {**off_sel, "region": "Milano", "_region_scope": "province"}
    )
    assert prov and all(r["value"] > 0 for r in prov)

    # breakdown accepts an explicit year
    years = q.mart_years(q.OFFENDERS_MART)
    assert len(years) > 1
    older = q.mart_breakdown(q.OFFENDERS_MART, "crime", off_sel, year=years[-1])
    assert older and all(r["name"] != "total" for r in older)

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
    rates_mart = data_dir / "marts" / "mart_offender_rates.parquet"
    assert rates_mart.exists()
    rates = q.offender_rates(q.ALL, q.ALL)
    assert rates and any(r["s1"] for r in rates)

    # regression: rates must EXCLUDE the hidden TOT crime row. Summing it
    # together with the detail crimes doubles every year in which ISTAT
    # published it (2007-2022) and fakes a 2022->2023 cliff in the chart.
    assert "crime_is_total" in pl.read_parquet(rates_mart).columns
    year = next(r["period"] for r in rates if r["s1"])
    row2 = con.execute(
        f"""
        SELECT SUM(CASE WHEN NOT crime_is_total THEN offenders END),
               SUM(offenders),
               ANY_VALUE(population)
        FROM read_parquet('{rates_mart}')
        WHERE citizenship_code = 'ITL' AND region_code = 'IT' AND year = ?
        """,
        [year],
    ).fetchone()
    assert row2 is not None
    details_only, with_tot, pop_itl = row2
    assert details_only is not None and with_tot is not None and pop_itl
    assert details_only < with_tot  # TOT present in the mart, but flagged
    shown = next(r["s1"] for r in rates if r["period"] == year)
    assert shown == round(1000.0 * details_only / pop_itl, 2)
