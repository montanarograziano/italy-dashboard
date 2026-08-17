"""Unit tests for the DuckDB read layer, against a synthetic snapshot."""

from __future__ import annotations

import os
import time
from datetime import date, timedelta

import duckdb
import polars as pl
import pytest

from italy_dashboard import queries as q


@pytest.fixture
def crime_mart(sample_db, monkeypatch):
    """Small deterministic mart_crime.parquet in the temp marts dir."""
    marts = sample_db / "marts"
    marts.mkdir(exist_ok=True)
    rows = []
    # Mixed admin levels, like the real data: country, regions, one macro-area
    # aggregate, one province. Only the regions belong in the region picker.
    regions = [
        ("IT", "Italy", True, "country"),
        ("ITC4", "Lombardia", False, "region"),
        ("ITI4", "Lazio", False, "region"),
        ("ITC", "Nord-ovest", False, "area"),
        ("ITC45", "Milano", False, "province"),
    ]
    offences = [("THEFT", "theft"), ("FRAUD", "fraud")]  # no offence total row
    sexes = [("1", "males", False), ("2", "females", False), ("9", "total", True)]
    ages = [
        ("TOTAL", "total", True),
        ("Y18-24", "18-24 years", False),
        ("Y25-34", "25-34 years", False),
    ]
    for year in ("2022", "2023"):
        for rc, rn, rtot, rlvl in regions:
            for oc, on in offences:
                for sc, sn, stot in sexes:
                    for ac, an, atot in ages:
                        base = 100 if oc == "THEFT" else 40
                        v = base * (3 if rtot else 1) * (2 if stot else 1) * (2 if atot else 1)
                        rows.append(
                            {
                                "year": year,
                                "region_code": rc,
                                "region_name": rn,
                                "region_level": rlvl,
                                "offence_code": oc,
                                "offence_name": on,
                                "sex_code": sc,
                                "sex_name": sn,
                                "age_code": ac,
                                "age_name": an,
                                "region_is_total": rtot,
                                "offence_is_total": False,
                                "sex_is_total": stot,
                                "age_is_total": atot,
                                "value": float(v),
                            }
                        )
    pl.DataFrame(rows).write_parquet(marts / "mart_crime.parquet")
    return marts


ALL_SEL = {"region": q.ALL, "offence": q.ALL, "sex": q.ALL, "age": q.ALL}

# All fixtures come from tests/conftest.py: `sample_db` wires queries.DB_PATH
# to a temp DuckDB built from synthetic data; `missing_db` points at nothing.


def test_db_ready_reflects_file_existence(sample_db, missing_db_not_used=None):
    assert q.db_ready() is True


def test_everything_degrades_gracefully_without_db(missing_db):
    assert q.db_ready() is False
    assert q.region_names() == [q.NATIONAL]
    assert q.crime_trend(dict.fromkeys(["region", "offence", "sex", "age"], q.ALL)) == []
    assert q.kpis() == {
        "crime": "—",
        "population": "—",
        "unemployment": "—",
        "inflation": "—",
    }


def test_region_names_start_with_national_and_are_sorted(sample_db):
    names = q.region_names()
    assert names[0] == q.NATIONAL
    rest = names[1:]
    assert rest == sorted(rest)
    assert "Lombardia" in rest


def test_crime_options_exclude_totals_and_start_with_all(crime_mart):
    options = q.crime_options()
    # regions only: "Italy" (total), "Nord-ovest" (area) and "Milano"
    # (province) must all stay out of the region picker
    assert options["region"] == [q.ALL, "Lazio", "Lombardia"]
    assert options["sex"] == [q.ALL, "females", "males"]  # "total" excluded
    assert options["offence"] == [q.ALL, "fraud", "theft"]


def test_province_options_cascade_from_region(crime_mart):
    assert q.mart_province_options(q.CRIME_MART) == [q.ALL, "Milano"]
    assert q.mart_province_options(q.CRIME_MART, "Lombardia") == [q.ALL, "Milano"]
    assert q.mart_province_options(q.CRIME_MART, "Lazio") == [q.ALL]


def test_province_selection_pins_province_rows(crime_mart):
    rows = q.crime_trend({**ALL_SEL, "region": "Milano", "_region_scope": "province"})
    # province detail row: (100 + 40) * sex total 2 * age total 2 = 560
    assert rows[0]["value"] == 560


def test_split_by_region_uses_region_level_rows_only(crime_mart):
    _, labels = q.crime_trend_pivot(ALL_SEL, "region")
    # never macro-areas (Nord-ovest) or provinces (Milano) next to regions
    assert set(labels) == {"Lombardia", "Lazio"}


def test_breakdown_accepts_a_year(crime_mart):
    assert q.mart_years(q.CRIME_MART) == ["2023", "2022"]
    latest = q.crime_offence_breakdown(ALL_SEL)
    explicit = q.crime_offence_breakdown(ALL_SEL, year="2022")
    assert explicit and latest
    assert [r["name"] for r in explicit] == [r["name"] for r in latest]


def test_crime_trend_all_prefers_total_rows(crime_mart):
    # region/sex/age have total rows -> picked; offence has none -> summed.
    rows = q.crime_trend(ALL_SEL)
    # IT total x sex total x age total: theft 100*3*2*2 + fraud 40*3*2*2 = 1680
    assert rows == [
        {"period": "2022", "value": 1680},
        {"period": "2023", "value": 1680},
    ]


def test_crime_trend_specific_region_filters_rows(crime_mart):
    rows = q.crime_trend({**ALL_SEL, "region": "Lombardia"})
    # 100*2*2 + 40*2*2 (sex+age totals, region detail)
    assert rows[0]["value"] == 560


def test_crime_trend_pivot_split_by_sex(crime_mart):
    rows, labels = q.crime_trend_pivot(ALL_SEL, "sex")
    assert set(labels) == {"males", "females"}  # totals excluded
    assert rows[0]["s1"] == rows[0]["s2"]  # deterministic fixture: equal split
    assert {"period", "s1", "s2"} <= set(rows[0])


def test_crime_trend_pivot_caps_series_at_three(crime_mart):
    _, labels = q.crime_trend_pivot(ALL_SEL, "region")
    assert len(labels) <= 3


def test_crime_offence_breakdown_sorted_and_filtered(crime_mart):
    rows = q.crime_offence_breakdown(ALL_SEL)
    assert [r["name"] for r in rows] == ["theft", "fraud"]
    rows_lazio = q.crime_offence_breakdown({**ALL_SEL, "region": "Lazio"})
    assert rows_lazio[0]["value"] < rows[0]["value"]


def test_crime_mart_missing_degrades_gracefully(sample_db):
    assert q.crime_mart_ready() is False
    assert q.crime_options() == {
        "region": [q.ALL],
        "offence": [q.ALL],
        "sex": [q.ALL],
        "age": [q.ALL],
    }
    assert q.crime_trend(ALL_SEL) == []
    assert q.crime_trend_pivot(ALL_SEL, "sex") == ([], [])


def test_foreign_share_is_a_percentage(sample_db):
    rows = q.foreign_share_timeseries(q.NATIONAL)
    assert rows, "expected non-empty share series"
    assert all(0.0 < r["value"] < 100.0 for r in rows)


def test_unemployment_series_has_selected_and_national(sample_db):
    rows = q.unemployment_series("Sicilia")
    assert rows
    for r in rows:
        assert set(r) == {"period", "selected", "national"}
    # When the selection IS the national aggregate, both series coincide.
    nat = q.unemployment_series(q.NATIONAL)
    assert all(r["selected"] == r["national"] for r in nat)


def test_kpis_are_formatted_strings(sample_db):
    k = q.kpis()
    assert set(k) == {"crime", "population", "unemployment", "inflation"}
    assert k["population"].endswith("M")
    assert k["unemployment"].endswith("%")
    assert k["inflation"][0] in "+-"


@pytest.fixture
def offenders_mart(sample_db):
    """mart_offenders with a citizenship dimension, built like crime_mart."""
    marts = sample_db / "marts"
    marts.mkdir(exist_ok=True)
    rows = []
    for year in ("2022", "2023"):
        for rc, rn, rtot in [("IT", "Italy", True), ("ITC4", "Lombardia", False)]:
            for zc, zn, ztot in [
                ("TOTAL", "total", True),
                ("ITL", "italian", False),
                ("FRG", "foreign", False),
            ]:
                for cc, cn in [("THEFT", "theft"), ("DRUGS", "drugs")]:
                    v = 100.0 * (2 if rtot else 1) * (2 if ztot else (1.4 if zc == "ITL" else 0.6))
                    rows.append(
                        {
                            "year": year,
                            "region_code": rc,
                            "region_name": rn,
                            "region_level": "country" if rc == "IT" else "region",
                            "indicator_code": "AUTH",
                            "indicator_name": "alleged offenders",
                            "crime_code": cc,
                            "crime_name": cn,
                            "sex_code": "9",
                            "sex_name": "total",
                            "age_code": "TOTAL",
                            "age_name": "total",
                            "citizenship_code": zc,
                            "citizenship_name": zn,
                            "region_is_total": rtot,
                            "indicator_is_total": False,
                            "crime_is_total": False,
                            "sex_is_total": True,
                            "age_is_total": True,
                            "citizenship_is_total": ztot,
                            "value": v,
                        }
                    )
    pl.DataFrame(rows).write_parquet(marts / "mart_offenders.parquet")
    return marts


OFF_SEL = dict.fromkeys(["region", "indicator", "crime", "sex", "age", "citizenship"], q.ALL)


def test_offenders_options_include_citizenship(offenders_mart):
    options = q.mart_options(q.OFFENDERS_MART)
    assert options["citizenship"] == [q.ALL, "foreign", "italian"]


def test_offenders_all_uses_citizenship_total_rows(offenders_mart):
    rows = q.mart_trend(q.OFFENDERS_MART, OFF_SEL)
    # IT total x citizenship total: 100*2*2 per crime x 2 crimes = 800
    assert rows[0]["value"] == 800


def test_offenders_split_by_citizenship(offenders_mart):
    rows, labels = q.mart_trend_pivot(q.OFFENDERS_MART, OFF_SEL, "citizenship")
    assert labels == ["italian", "foreign"]
    assert rows[0]["s1"] > rows[0]["s2"]  # italians > foreigners in fixture


def test_offenders_citizenship_filter(offenders_mart):
    rows = q.mart_trend(q.OFFENDERS_MART, {**OFF_SEL, "citizenship": "foreign"})
    # IT total x foreign share 0.6: 100*2*0.6*2 crimes = 240
    assert rows[0]["value"] == 240


@pytest.fixture
def offenders_mart_mixed_slices(sample_db):
    """Mimics real ISTAT publishing: early years only have marginal slices
    (sex XOR citizenship detail), recent years the full cross-product."""
    marts = sample_db / "marts"
    marts.mkdir(exist_ok=True)

    def row(year, rc, rt, sc, st, ac, at, zc, zt, v):
        return {
            "year": year,
            "region_code": rc,
            "region_name": "Italy" if rt else rc,
            "region_level": "country" if rc == "IT" else "region",
            "indicator_code": "AUTH",
            "indicator_name": "offenders",
            "crime_code": "THEFT",
            "crime_name": "theft",
            "sex_code": sc,
            "sex_name": {"1": "males", "2": "females", "9": "total"}[sc],
            "age_code": ac,
            "age_name": ac.lower(),
            "citizenship_code": zc,
            "citizenship_name": {"ITL": "italian", "FRG": "foreign", "TOTAL": "total"}[zc],
            "region_is_total": rt,
            "indicator_is_total": False,
            "crime_is_total": False,
            "sex_is_total": st,
            "age_is_total": at,
            "citizenship_is_total": zt,
            "value": float(v),
        }

    rows = []
    # 2008: sex-marginal (cit total) and citizenship-marginal (sex total) only
    rows += [
        row("2008", "IT", True, "1", False, "TOTAL", True, "TOTAL", True, 60),
        row("2008", "IT", True, "2", False, "TOTAL", True, "TOTAL", True, 40),
        row("2008", "IT", True, "9", True, "TOTAL", True, "ITL", False, 70),
        row("2008", "IT", True, "9", True, "TOTAL", True, "FRG", False, 30),
    ]
    # 2023: full cross-product including the all-totals row
    rows += [
        row("2023", "IT", True, "9", True, "TOTAL", True, "TOTAL", True, 90),
        row("2023", "IT", True, "1", False, "TOTAL", True, "TOTAL", True, 55),
        row("2023", "IT", True, "2", False, "TOTAL", True, "TOTAL", True, 35),
        row("2023", "IT", True, "9", True, "TOTAL", True, "ITL", False, 60),
        row("2023", "IT", True, "9", True, "TOTAL", True, "FRG", False, 30),
    ]
    pl.DataFrame(rows).write_parquet(marts / "mart_offenders.parquet")
    return marts


def test_all_survives_years_with_only_marginal_slices(offenders_mart_mixed_slices):
    """Regression: the naive 'all totals' combination only exists in recent
    years; the slice picker must find a combination covering ALL years."""
    rows = q.mart_trend(q.OFFENDERS_MART, OFF_SEL)
    assert [r["period"] for r in rows] == ["2008", "2023"]
    assert rows[0]["value"] == 100  # sex or citizenship marginal, both sum to 100


def test_split_uses_only_years_where_the_dimension_exists(offenders_mart_mixed_slices):
    rows, labels = q.mart_trend_pivot(q.OFFENDERS_MART, OFF_SEL, "citizenship")
    assert [r["period"] for r in rows] == ["2008", "2023"]
    assert set(labels) == {"italian", "foreign"}


def test_region_details_never_summed_for_all(offenders_mart_mixed_slices):
    # "All" region must sit on the IT total row (details mix admin levels).
    where, _ = q._mart_where(q.OFFENDERS_MART, OFF_SEL)
    assert "region_is_total" in where and "NOT region_is_total" not in where


@pytest.fixture
def rates_mart(sample_db):
    """Minimal mart_offender_rates: two years, IT + regions + hidden TOT row."""
    marts = sample_db / "marts"
    marts.mkdir(exist_ok=True)
    rows = []
    for year in ("2023", "2024"):
        for rc, rn in [("IT", "Italy"), ("ITC4", "Lombardia"), ("ITF3", "Campania")]:
            for cc, ct in [("THEFT", False), ("TOT", True)]:
                for zc, zn, zt in [
                    ("TOTAL", "total", True),
                    ("ITL", "italian", False),
                    ("FRG", "foreign", False),
                ]:
                    pop = {"TOTAL": 1_000_000, "ITL": 900_000, "FRG": 100_000}[zc]
                    offenders = (500 if rc == "ITC4" else 300) * (10 if rc == "IT" else 1)
                    rows.append(
                        {
                            "year": year,
                            "region_code": rc,
                            "region_name": rn,
                            "crime_code": cc,
                            "crime_name": "total" if ct else "theft",
                            "crime_is_total": ct,
                            "citizenship_code": zc,
                            "citizenship_name": zn,
                            "citizenship_is_total": zt,
                            "offenders": float(offenders),
                            "population": float(pop),
                            "rate_per_1000": 1000.0 * offenders / pop,
                        }
                    )
    pl.DataFrame(rows).write_parquet(marts / "mart_offender_rates.parquet")
    return marts


def test_region_rate_ranking_all_regions_sorted(rates_mart):
    rows = q.region_rate_ranking("2024", q.ALL, q.ALL)
    # IT excluded, all regions present, ranked by rate descending
    assert [r["name"] for r in rows] == ["Lombardia", "Campania"]
    assert rows[0]["value"] > rows[1]["value"]
    # hidden TOT crime row flagged out: rate = 500 / 1M * 1000, not doubled
    assert rows[0]["value"] == 0.5


def test_region_rate_ranking_respects_citizenship(rates_mart):
    rows = q.region_rate_ranking("2024", "foreign", q.ALL)
    # foreign offenders over the FOREIGN population: 500 / 100k * 1000
    assert rows[0]["value"] == 5.0


def test_region_rate_ranking_defaults_to_latest_year(rates_mart):
    assert q.region_rate_ranking(None, q.ALL, q.ALL) == q.region_rate_ranking("2024", q.ALL, q.ALL)


# ------------------------------------------------------------------ climate


def test_climate_not_ready_without_a_snapshot(missing_db):
    assert q.climate_ready() is False
    assert q.climate_cities() == []
    assert q.climate_annual_series("Roma") == []
    assert q.warming_rate_ranking() == []


def test_climate_cities_are_the_sample_capitals(climate_db):
    cities = q.climate_cities()
    assert len(cities) == 20
    assert cities == sorted(cities)
    assert "Roma" in cities and "Palermo" in cities


def test_climate_annual_series_has_min_mean_max_per_year(climate_db):
    rows = q.climate_annual_series("Roma")
    assert rows
    assert {"period", "t_mean", "t_min", "t_max", "t_band", "t_rolling"} == set(rows[0])
    assert [r["period"] for r in rows] == sorted(r["period"] for r in rows)
    assert all(r["t_min"] <= r["t_mean"] <= r["t_max"] for r in rows)


def test_t_band_pairs_min_and_max_in_that_order(climate_db):
    """`t_band` feeds a fill-between Area: [min, max], never [max, min]."""
    rows = q.climate_annual_series("Roma")
    assert rows
    for r in rows:
        assert list(r["t_band"]) == [r["t_min"], r["t_max"]]


@pytest.fixture
def short_rolling_mart(sample_db):
    """Eight complete years: shorter than the 10-year rolling window.

    Every `t_rolling` must be None here — there is no year in this series for
    which a full 10-year window (4 before, the year itself, 5 after) exists.
    """
    marts = sample_db / "marts"
    marts.mkdir(exist_ok=True)
    rows = [
        {
            "province_code": "IT998",
            "province_name": "Shortville",
            "capital_city": "Shortville",
            "region_code": "ITZ9",
            "region_name": "Testregion",
            "year": str(year),
            "t_mean": float(year - 2000),
            "t_min_mean": float(year - 2000) - 5.0,
            "t_max_mean": float(year - 2000) + 5.0,
            "days_observed": 365,
            "anomaly_1981_2010": 0.0,
        }
        for year in range(2000, 2008)  # 8 years: 2000..2007
    ]
    pl.DataFrame(rows).write_parquet(marts / "mart_climate_annual.parquet")
    return marts


def test_rolling_mean_is_null_everywhere_when_series_is_shorter_than_the_window(
    short_rolling_mart,
):
    rows = q.climate_annual_series("Shortville")
    assert len(rows) == 8
    assert all(r["t_rolling"] is None for r in rows)


@pytest.fixture
def long_rolling_mart(sample_db):
    """Twenty years, t_mean = year - 2000 (a plain arithmetic series).

    This makes the rolling mean's exact value predictable by hand: over any
    window of consecutive integers, the mean is the average of the first and
    last value in that window.
    """
    marts = sample_db / "marts"
    marts.mkdir(exist_ok=True)
    rows = [
        {
            "province_code": "IT997",
            "province_name": "Longville",
            "capital_city": "Longville",
            "region_code": "ITZ9",
            "region_name": "Testregion",
            "year": str(year),
            "t_mean": float(year - 2000),
            "t_min_mean": float(year - 2000) - 5.0,
            "t_max_mean": float(year - 2000) + 5.0,
            "days_observed": 365,
            "anomaly_1981_2010": 0.0,
        }
        for year in range(2000, 2020)  # 20 years: 2000..2019
    ]
    pl.DataFrame(rows).write_parquet(marts / "mart_climate_annual.parquet")
    return marts


def test_rolling_mean_edges_are_null_exactly_where_the_window_is_incomplete(long_rolling_mart):
    """4 years precede, 5 follow: the first 4 and last 5 years can't fill it.

    Asserts the EXACT boundary (years 2000-2003 and 2015-2019 null, 2004-2014
    populated), not just "some are null" — a rolling mean that silently
    shrinks its own window at the edges is the defect this test exists to
    catch.
    """
    rows = {r["period"]: r["t_rolling"] for r in q.climate_annual_series("Longville")}
    assert len(rows) == 20

    null_years = set(range(2000, 2004)) | set(range(2015, 2020))
    populated_years = set(range(2004, 2015))
    assert null_years | populated_years == set(range(2000, 2020))

    for year in null_years:
        assert rows[str(year)] is None, f"{year} should be null (incomplete window)"
    for year in populated_years:
        assert rows[str(year)] is not None, f"{year} should be populated (full window)"


def test_rolling_mean_is_centred_and_correct_on_a_synthetic_series(long_rolling_mart):
    """Year 2009 (index 9): window is 2005..2014 (4 before, self, 5 after).

    t_mean there is a straight line (t_mean = year - 2000), so the mean of a
    consecutive integer window is just the average of its endpoints:
    (5 + 14) / 2 = 9.5.
    """
    rows = {r["period"]: r["t_rolling"] for r in q.climate_annual_series("Longville")}
    assert rows["2009"] == 9.5


def test_warming_rate_ranking_is_sorted_descending(climate_db):
    rows = q.warming_rate_ranking(top_n=5)
    assert len(rows) == 5
    values = [r["value"] for r in rows]
    assert values == sorted(values, reverse=True)


def test_threshold_days_are_non_negative_integers(climate_db):
    rows = q.climate_threshold_days("Palermo")
    assert rows
    assert {"period", "hot_days", "tropical_nights", "frost_days"} == set(rows[0])
    assert all(r["hot_days"] >= 0 and r["frost_days"] >= 0 for r in rows)


def test_month_heatmap_has_twelve_month_columns(climate_db):
    rows = q.climate_month_heatmap("Milano")
    assert rows
    assert {"period", *[f"m{i}" for i in range(1, 13)]} == set(rows[0])


DISTRIBUTION_FIXTURE_YEARS = [
    # Warming by construction: the split lands between 1970 and 2000, so the
    # early years occupy buckets 20/22/24 and the late years 26/28/30, with no
    # bucket shared. That disjointness is what the assertions below key on.
    (1960, 20.0),
    (1965, 22.0),
    (1970, 24.0),
    (2000, 26.0),
    (2010, 28.0),
    (2020, 30.0),
]


@pytest.fixture
def climate_daily_mart(sample_db):
    """Minimal mart_climate_daily.parquet spanning both distribution windows.

    climate_db's synthetic weather series only covers 1981-2024 (see
    ingestion.sample_data.WEATHER_YEARS). That used to have ZERO overlap with a
    hardcoded early window of 1951-1980; now that the windows are derived per
    city from the record itself, a short series splits inside its own span
    instead of returning []. This fixture stays anyway, because it pins the
    bucketing/normalization logic to known values (bypassing dbt, like
    crime_mart/rates_mart above) rather than to whatever the sample generator
    happens to emit.

    Every year is written FULL (365 days at one temperature). Windows are
    derived only from years with at least MIN_DAYS_FOR_A_FULL_YEAR days, so a
    one-row-per-year fixture would produce no complete years and no windows at
    all — the same rule that keeps a partial running year out of the real chart.
    """
    marts = sample_db / "marts"
    marts.mkdir(exist_ok=True)
    pl.DataFrame(
        [
            {
                "province_code": "IT001",
                "province_name": "Torino",
                "capital_city": "Torino",
                "region_code": "ITC1",
                "region_name": "Piemonte",
                "obs_date": date(year, 1, 1) + timedelta(days=offset),
                "year": str(year),
                "month": (date(year, 1, 1) + timedelta(days=offset)).month,
                "t_min": t_max - 10.0,
                "t_mean": t_max - 5.0,
                "t_max": t_max,
            }
            for year, t_max in DISTRIBUTION_FIXTURE_YEARS
            for offset in range(365)
        ]
    ).write_parquet(marts / "mart_climate_daily.parquet")
    return marts


def test_distribution_buckets_are_ordered_and_comparable(climate_daily_mart):
    rows = q.climate_distribution("Torino")
    assert rows
    assert {"period", "early", "late"} == set(rows[0])
    assert [r["period"] for r in rows] == sorted(r["period"] for r in rows)
    # early-window days landed in the cooler buckets, late-window in the
    # warmer ones: each row is 100% one side, 0% the other.
    assert all((r["early"] > 0) != (r["late"] > 0) for r in rows)


def test_distribution_windows_split_the_record_with_no_gap(climate_daily_mart):
    """The two windows must be adjacent and cover every complete year.

    This is the whole point of deriving them: a gap between the windows reads
    to a viewer as missing data, and an overlap would double-count years.
    """
    windows = q.climate_distribution_windows("Torino")
    assert windows is not None
    early_lo, early_hi, late_lo, late_hi = windows
    years = [year for year, _ in DISTRIBUTION_FIXTURE_YEARS]
    assert (early_lo, late_hi) == (min(years), max(years))
    assert late_lo == early_hi + 1  # adjacent: no gap, no overlap
    assert early_lo <= early_hi  # neither window can come out empty
    assert late_lo <= late_hi
    assert all(early_lo <= year <= late_hi for year in years)


def test_distribution_windows_exclude_a_partial_trailing_year(climate_daily_mart):
    """A year holding only its summer would drag its window warm.

    Written as a REAL partial year appended to the fixture, because the failure
    it guards against is arithmetic, not a branch: 200 hot days averaged
    against 365 balanced ones shifts the late curve with nothing looking wrong.
    """
    existing = pl.read_parquet(climate_daily_mart / "mart_climate_daily.parquet")
    partial = (
        existing.filter(pl.col("year") == "2020")
        .head(200)
        .with_columns(
            pl.lit("2026").alias("year"),
            pl.col("obs_date").dt.offset_by("6y"),
        )
    )
    pl.concat([existing, partial]).write_parquet(climate_daily_mart / "mart_climate_daily.parquet")
    windows = q.climate_distribution_windows("Torino")
    assert windows is not None
    assert windows[3] == 2020  # late_hi, not the 2026 stub


def test_distribution_windows_are_none_below_two_complete_years(climate_daily_mart):
    """One year cannot be split in two, and must not be faked into a comparison."""
    existing = pl.read_parquet(climate_daily_mart / "mart_climate_daily.parquet")
    existing.filter(pl.col("year") == "1960").write_parquet(
        climate_daily_mart / "mart_climate_daily.parquet"
    )
    assert q.climate_distribution_windows("Torino") is None
    assert q.climate_distribution("Torino") == []


def test_crime_climate_scatter_returns_both_views(climate_db):
    out = q.crime_climate_scatter()
    assert set(out) == {"raw", "panel"}
    assert out["panel"]
    assert {"x", "y", "region", "year"} == set(out["panel"][0])


def test_crime_climate_stats_report_n_and_never_a_p_value(climate_db):
    stats = q.crime_climate_stats()
    assert set(stats) == {"raw", "panel", "n"}
    assert stats["n"].isdigit()
    # No significance claim is made anywhere: 21 clusters cannot support one.
    assert "p =" not in stats["panel"] and "p<" not in stats["panel"]


@pytest.fixture
def crime_climate_mart(sample_db):
    """Two regions whose ABSOLUTE and WITHIN-region temperatures disagree.

    A cool region with high offending and a hot region with low offending, and
    inside each region the warmer years are the higher-offending ones. So
    corr(ln_offenders, summer_tmax) is strongly NEGATIVE while
    corr(ln_offenders, summer_anomaly) is POSITIVE, and the two columns have
    no overlap in range (28-35 C against -0.5..+0.5). Reading the raw view off
    the wrong column cannot go unnoticed against this fixture.
    """
    marts = sample_db / "marts"
    marts.mkdir(exist_ok=True)
    rows = []
    for region, tmax0, ln0 in (("Cool region", 28.0, 10.0), ("Hot region", 34.0, 9.0)):
        for i, year in enumerate(("2020", "2021", "2022")):
            rows.append(
                {
                    "region_code": region[:4],
                    "region_name": region,
                    "year": year,
                    "summer_tmax": tmax0 + 0.5 * i,
                    "summer_anomaly": -0.5 + 0.5 * i,
                    "offenders": 1000,
                    "ln_offenders": ln0 + 0.1 * i,
                    "summer_anomaly_dm": -0.5 + 0.5 * i,
                    "ln_offenders_dm": 0.1 * i - 0.1,
                }
            )
    pl.DataFrame(rows).write_parquet(marts / "mart_crime_climate.parquet")
    return marts


def test_raw_scatter_plots_absolute_temperature_not_the_anomaly(crime_climate_mart):
    """The raw view must be a real cross-section.

    summer_anomaly is each region's deviation from its OWN baseline, so it has
    the between-region variation already removed: plotting it as the "naive
    cross-section" shows the confound the page exists to expose has vanished.
    """
    out = q.crime_climate_scatter()

    raw_x = sorted(p["x"] for p in out["raw"])
    panel_x = sorted(p["x"] for p in out["panel"])
    assert raw_x != panel_x  # the two views must not share an x variable

    # Absolute summer temperatures, not anomalies around zero.
    assert raw_x == [28.0, 28.5, 29.0, 34.0, 34.5, 35.0]
    assert all(x > 20 for x in raw_x)

    # The panel branch is untouched: it still plots the demeaned columns.
    assert panel_x == [-0.5, -0.5, 0.0, 0.0, 0.5, 0.5]


def test_raw_stats_are_computed_on_absolute_temperature(crime_climate_mart):
    """Same guard on the numbers under the charts.

    On this fixture the two candidate x variables give opposite signs, so a
    slope or r taken from summer_anomaly cannot pass as one from summer_tmax.
    """
    stats = q.crime_climate_stats()

    assert stats["n"] == "6"
    # corr(ln_offenders, summer_tmax) is negative here; the anomaly version
    # would be +1.00 and this assertion is what catches the swap.
    assert "r = -" in stats["raw"]
    assert "slope = -" in stats["raw"]
    # The panel line still reads off the demeaned columns (positive here).
    assert "r = +" in stats["panel"]


@pytest.fixture
def partial_year_annual_mart(sample_db):
    """Twelve flat complete years plus one hot, unfinished year.

    The complete years have an identical mean, so the warming rate over them
    is exactly zero. The partial year is 6 C warmer with 210 days of data,
    which is what a January-to-August year looks like on the real feed (the
    fetch always runs to today minus 7 days).
    """
    marts = sample_db / "marts"
    marts.mkdir(exist_ok=True)
    rows = [
        {
            "province_code": "IT999",
            "province_name": "Testville",
            "capital_city": "Testville",
            "region_code": "ITZ9",
            "region_name": "Testregion",
            "year": str(year),
            "t_mean": 15.0,
            "t_min_mean": 10.0,
            "t_max_mean": 20.0,
            "days_observed": 365,
            "anomaly_1981_2010": 0.0,
        }
        for year in range(2010, 2022)
    ]
    rows.append(
        {
            "province_code": "IT999",
            "province_name": "Testville",
            "capital_city": "Testville",
            "region_code": "ITZ9",
            "region_name": "Testregion",
            "year": "2022",
            "t_mean": 21.0,
            "t_min_mean": 16.0,
            "t_max_mean": 26.0,
            "days_observed": 210,
            "anomaly_1981_2010": 6.0,
        }
    )
    pl.DataFrame(rows).write_parquet(marts / "mart_climate_annual.parquet")
    return marts


def test_partial_years_are_excluded_from_every_climate_series(partial_year_annual_mart):
    """A year that is not over yet must not be plotted as if it were.

    Without the days_observed gate the unfinished year is a record-warm point
    on the line and on the stripes, and the last, highest-leverage point of the
    warming-rate regression.
    """
    years = [r["period"] for r in q.climate_annual_series("Testville")]
    assert "2022" not in years
    assert len(years) == 12

    stripe_years = [r["period"] for r in q.climate_stripes("Testville")]
    assert "2022" not in stripe_years

    ranking = q.warming_rate_ranking()
    assert ranking == [{"name": "Testville", "value": 0.0}]  # flat, not warming


def test_climate_stripes_carry_a_diverging_fill(climate_db):
    rows = q.climate_stripes("Roma")
    if not rows:
        pytest.skip("no anomalies in this fixture: the CLINO guard nulls them")
    assert {"period", "anomaly", "fill"} == set(rows[0])
    for r in rows:
        assert r["fill"].startswith("var(--div-")
    # colour must track the value: the warmest year cannot share the coldest's step
    warmest = max(rows, key=lambda r: r["anomaly"])
    coldest = min(rows, key=lambda r: r["anomaly"])
    if warmest["anomaly"] > coldest["anomaly"]:
        assert warmest["fill"] != coldest["fill"]


def test_climate_stripes_grid_returns_one_entry_per_city(climate_db):
    grid = q.climate_stripes_grid(limit=6)
    if not grid:
        pytest.skip("no anomalies in this fixture: the CLINO guard nulls them")
    assert len(grid) <= 6
    assert {"city", "rows"} == set(grid[0])
    assert all(r["fill"].startswith("var(--div-") for r in grid[0]["rows"])


# ------------------------------------------------------- climate coverage


def test_climate_coverage_reports_only_seed_totals_without_a_mart(missing_db):
    # Denominators come from dbt/seeds/province_capitals.csv (106 capitals,
    # 21 NUTS2 regions), never a hardcoded 106/21, so they still show up even
    # with no mart_climate_annual on disk at all.
    assert q.climate_coverage() == {
        "capitals": "0",
        "capitals_total": "106",
        "regions": "0",
        "regions_total": "21",
        "year_start": "—",
        "year_end": "—",
    }


def test_climate_coverage_counts_whats_actually_in_the_mart(climate_db):
    # climate_db's synthetic snapshot covers 20 of the 106 capitals (see
    # ingestion.sample_data.SAMPLE_CAPITALS), spanning 12 of the 21 regions.
    coverage = q.climate_coverage()
    assert coverage["capitals_total"] == "106"
    assert coverage["regions_total"] == "21"
    assert coverage["capitals"] == "20"
    assert coverage["regions"] == "12"
    assert coverage["year_start"] == "1981"
    assert coverage["year_end"] == "2024"


# ---------------------------------------------- connection & result caching
#
# `_query` used to open a fresh in-memory DuckDB connection and re-create
# every view on EVERY call (32 calls x 18 views = 576 CREATE VIEWs on one
# climate page load). These tests pin the fix: one shared connection reused
# across calls, its views built only once per on-disk snapshot, and query
# results cached and only invalidated when the snapshot's fingerprint
# (path, size, mtime per parquet file) actually changes.


class _SpyConnection:
    """Wraps a real DuckDB connection, logging every `execute()` call's SQL.

    A plain attribute assignment (`con.execute = ...`) fails: DuckDB's
    connection is a C-extension type whose methods are read-only. Wrapping it
    behind `__getattr__` is the only way to intercept `execute` without
    touching queries.py's own code.
    """

    def __init__(self, real: duckdb.DuckDBPyConnection, log: list[str]) -> None:
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_log", log)

    def execute(self, sql, *args, **kwargs):
        self._log.append(sql)
        return self._real.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_connection_is_reused_not_reopened_on_every_call(sample_db, monkeypatch):
    q._reset_query_cache()
    connect_calls: list[object] = []
    real_connect = duckdb.connect

    def counting_connect(*args, **kwargs):
        connect_calls.append(1)
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(duckdb, "connect", counting_connect)

    q.region_names()
    q.unemployment_series(q.NATIONAL)
    q.kpis()

    assert len(connect_calls) == 1


def test_views_are_created_once_per_snapshot_not_once_per_call(sample_db, monkeypatch):
    q._reset_query_cache()
    log: list[str] = []
    real_connect = duckdb.connect

    def spying_connect(*args, **kwargs):
        return _SpyConnection(real_connect(*args, **kwargs), log)

    monkeypatch.setattr(duckdb, "connect", spying_connect)

    q.region_names()
    created_after_first_call = sum(1 for sql in log if sql.startswith("CREATE VIEW"))
    assert created_after_first_call > 0  # the 18-ish views were built once

    q.region_names()
    q.unemployment_series(q.NATIONAL)
    created_after_more_calls = sum(1 for sql in log if sql.startswith("CREATE VIEW"))
    assert created_after_more_calls == created_after_first_call, (
        "later calls must not re-create views against an unchanged snapshot"
    )


def test_query_results_are_cached_across_calls(sample_db):
    q._reset_query_cache()
    sql = "SELECT DISTINCT territory_name FROM labor_unemployment ORDER BY territory_name"

    first = q._query(sql)
    second = q._query(sql)

    assert first is second, "identical (sql, params) must be served from the cache"


def test_query_cache_is_busted_when_the_snapshot_fingerprint_changes(sample_db):
    """The correctness guard the task calls out explicitly: a developer who
    reruns `just sample`/`just transform` rewrites parquet files IN PLACE, so
    the cache must key on more than the SQL text. Bumping just the mtime of
    one file (no schema/content change needed to prove the point) must force
    a fresh read rather than silently keep serving the previous run's list.
    """
    q._reset_query_cache()
    sql = "SELECT DISTINCT territory_name FROM labor_unemployment ORDER BY territory_name"
    first = q._query(sql)

    target = next(sample_db.glob("*.parquet"))
    future = time.time() + 5
    os.utime(target, (future, future))

    second = q._query(sql)
    assert second is not first, "a changed fingerprint must invalidate the cached result"
    assert second == first, "the underlying data didn't change, only its mtime"


def test_a_mart_appearing_after_a_prior_miss_is_picked_up_not_stuck_empty(sample_db):
    """`crime_trend` degrades to [] when mart_crime.parquet doesn't exist yet
    (see `_query`'s CatalogException branch). That miss must NOT be cached
    forever: once the mart is built (a real `just transform` outcome), the
    very next call must see it.
    """
    q._reset_query_cache()
    sel = dict.fromkeys(["region", "offence", "sex", "age"], q.ALL)
    assert q.crime_trend(sel) == []

    marts = sample_db / "marts"
    marts.mkdir(exist_ok=True)
    pl.DataFrame(
        [
            {
                "year": "2023",
                "region_code": "IT",
                "region_name": "Italy",
                "region_level": "country",
                "offence_code": "THEFT",
                "offence_name": "theft",
                "sex_code": "9",
                "sex_name": "total",
                "age_code": "TOTAL",
                "age_name": "total",
                "region_is_total": True,
                "offence_is_total": False,
                "sex_is_total": True,
                "age_is_total": True,
                "value": 42.0,
            }
        ]
    ).write_parquet(marts / "mart_crime.parquet")

    rows = q.crime_trend(sel)
    assert rows and rows[0]["value"] == 42
