"""Integration: mart_climate_region's anomaly guard and national 'IT' row.

Unlike test_dbt.py's full-project build, this constructs a small, HAND-PICKED
weather snapshot rather than reusing ingestion.sample_data's synthetic
generator: the generator gives every capital the same 1981-2024 year range,
so it can never exercise a region with fewer than 25 years inside a baseline
window. That gap has to be constructed on purpose (see the module docstring
in mart_climate_region.sql: "a handful of years would produce a
confident-looking anomaly that is really just noise dressed up as a 30-year
normal" -- a claim worth testing against an actual partial series, not just
trusting the SQL).

`--select +mart_climate_region` builds only the model and its ancestors
(the province_capitals seed, stg_weather, mart_climate_daily), so this does
not need the other ISTAT datasets' raw files to exist. The two crime/climate
coverage tests are excluded because their OTHER ref (mart_offenders /
mart_crime_climate) is outside that selection and would error on a missing
source, not because they are wrong.
"""

from __future__ import annotations

import os
import subprocess
from datetime import date
from pathlib import Path

import polars as pl
import pytest

pytestmark = pytest.mark.integration

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Three provinces, three regions:
#   ITC11 (Piemonte / ITC1) and ITE43 (Lazio / ITE4) each cover the full
#   1981-2010 baseline window (30 years) -> the guard must pass for both.
#   ITF33 (Campania / ITF3) covers only 1981-2000 (20 years) -> fewer than
#   25 years inside the window, so the guard must return NULL for it.
# t_mean is a deterministic linear function of the year so the expected
# baseline/anomaly can be recomputed independently in Python below, rather
# than hard-coded.
PIEMONTE = ("ITC11", "ITC1", 1981, 2010, lambda y: 10.0 + 0.05 * (y - 1981))
LAZIO = ("ITE43", "ITE4", 1981, 2010, lambda y: 15.0 + 0.03 * (y - 1981))
CAMPANIA = ("ITF33", "ITF3", 1981, 2000, lambda y: 18.0 + 0.07 * (y - 1981))
PROVINCES = [PIEMONTE, LAZIO, CAMPANIA]

EXCLUDED_TESTS = [
    "assert_crime_climate_covers_available_climate",
    "assert_offender_regions_in_capitals_vocabulary",
]


@pytest.fixture(scope="module")
def region_mart(tmp_path_factory: pytest.TempPathFactory) -> pl.DataFrame:
    data_dir = tmp_path_factory.mktemp("climate_guard_data")
    (data_dir / "marts").mkdir(parents=True)

    rows = []
    for province_code, _region_code, start, end, t_mean_fn in PROVINCES:
        for year in range(start, end + 1):
            t_mean = t_mean_fn(year)
            rows.append(
                {
                    "province_code": province_code,
                    "date": date(year, 7, 1),
                    "t_min": t_mean - 5.0,
                    "t_mean": t_mean,
                    "t_max": t_mean + 5.0,
                }
            )
    pl.DataFrame(
        rows,
        schema={
            "province_code": pl.Utf8,
            "date": pl.Date,
            "t_min": pl.Float64,
            "t_mean": pl.Float64,
            "t_max": pl.Float64,
        },
    ).write_parquet(data_dir / "weather_daily.parquet")

    result = subprocess.run(
        [
            "uv",
            "run",
            "dbt",
            "build",
            "--select",
            "+mart_climate_region",
            "--exclude",
            *EXCLUDED_TESTS,
            "--project-dir",
            "dbt",
            "--profiles-dir",
            "dbt",
        ],
        cwd=PROJECT_ROOT,
        env={**os.environ, "ITALY_DATA_DIR": str(data_dir)},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    return pl.read_parquet(data_dir / "marts" / "mart_climate_region.parquet")


def test_grain_is_one_row_per_region_and_year(region_mart: pl.DataFrame) -> None:
    dupes = region_mart.group_by(["region_code", "year"]).len().filter(pl.col("len") > 1)
    assert dupes.height == 0, dupes


def test_exactly_one_national_row_per_year_with_data(region_mart: pl.DataFrame) -> None:
    regional_years = set(region_mart.filter(pl.col("region_code") != "IT")["year"])
    national_years = region_mart.filter(pl.col("region_code") == "IT")["year"].to_list()
    assert sorted(national_years) == sorted(regional_years)
    assert len(national_years) == len(set(national_years))  # no year appears twice


def test_short_region_series_gets_null_anomaly_not_a_partial_average(
    region_mart: pl.DataFrame,
) -> None:
    # Campania has only 20 years inside 1981-2010 (< 25): the guard must
    # withhold the anomaly rather than average whatever 20 years exist.
    campania = region_mart.filter(pl.col("region_code") == "ITF3")
    assert campania.height == 20
    assert campania["anomaly_1981_2010"].null_count() == 20
    assert campania["anomaly_1971_2000"].null_count() == 20  # 0 years in that window too
    # t_mean itself is real data, only the anomaly is withheld
    assert campania["t_mean"].null_count() == 0


def test_full_region_series_gets_a_real_anomaly(region_mart: pl.DataFrame) -> None:
    # Piemonte and Lazio each have the full 30 years inside 1981-2010 (>= 25):
    # the guard must pass and every row gets a non-null anomaly.
    for region_code in ("ITC1", "ITE4"):
        region = region_mart.filter(pl.col("region_code") == region_code)
        assert region.height == 30
        assert region["anomaly_1981_2010"].null_count() == 0


def test_national_t_mean_matches_independent_unweighted_mean_of_capitals(
    region_mart: pl.DataFrame,
) -> None:
    # Recompute the national t_mean straight from the province formulas
    # (independent of the mart's own SQL) and compare, for a year all three
    # capitals share.
    year = 1990
    expected = round(sum(fn(year) for *_ignored, fn in [PIEMONTE, LAZIO, CAMPANIA]) / 3, 2)
    actual = region_mart.filter((pl.col("region_code") == "IT") & (pl.col("year") == str(year)))[
        "t_mean"
    ].item()
    assert actual == pytest.approx(expected, abs=0.01)


def test_national_anomaly_comes_from_the_national_series_not_from_regions(
    region_mart: pl.DataFrame,
) -> None:
    """The national anomaly must be computed from the national t_mean series,
    not by averaging the regions' own anomalies. Campania's warmer capital is
    part of the national mean every year it has data (1981-2000), but its
    OWN regional anomaly is NULL (guard fails), so a "mean of the regions'
    anomalies" would silently drop Campania's contribution to Italy's level.
    This proves the mart does not do that: the true national anomaly and the
    naive mean-of-available-regional-anomalies differ by a wide margin.
    """
    year = 1990

    # True national series, recomputed independently in Python.
    def national_t_mean(y: int) -> float:
        values = [fn(y) for _p, _r, start, end, fn in PROVINCES if start <= y <= end]
        return sum(values) / len(values)

    baseline_years = range(1981, 2011)
    expected_baseline = sum(national_t_mean(y) for y in baseline_years) / len(baseline_years)
    expected_anomaly = round(national_t_mean(year) - expected_baseline, 2)

    actual_row = region_mart.filter((pl.col("region_code") == "IT") & (pl.col("year") == str(year)))
    actual_anomaly = actual_row["anomaly_1981_2010"].item()
    assert actual_anomaly == pytest.approx(expected_anomaly, abs=0.01)

    # The naive (wrong) alternative: averaging the two regions that HAVE a
    # non-null anomaly that year (Campania's is NULL and would be dropped).
    piemonte_anomaly = region_mart.filter(
        (pl.col("region_code") == "ITC1") & (pl.col("year") == str(year))
    )["anomaly_1981_2010"].item()
    lazio_anomaly = region_mart.filter(
        (pl.col("region_code") == "ITE4") & (pl.col("year") == str(year))
    )["anomaly_1981_2010"].item()
    naive_mean_of_regions = (piemonte_anomaly + lazio_anomaly) / 2

    assert actual_anomaly != pytest.approx(naive_mean_of_regions, abs=0.05)


def test_it_row_not_double_counted_into_a_real_region(region_mart: pl.DataFrame) -> None:
    # The national row's own code must never coincide with a real region code
    # emitted by the per-province aggregation, or the two would merge.
    real_region_codes = {code for _p, code, *_rest in PROVINCES}
    assert "IT" not in real_region_codes
    assert region_mart.filter(pl.col("region_code") == "IT")["region_name"].unique().to_list() == [
        "Italia"
    ]
