"""Unit tests for the DuckDB read layer, against a synthetic snapshot."""

from __future__ import annotations

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
    assert {"period", "t_mean", "t_min", "t_max"} == set(rows[0])
    assert [r["period"] for r in rows] == sorted(r["period"] for r in rows)
    assert all(r["t_min"] <= r["t_mean"] <= r["t_max"] for r in rows)


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


@pytest.fixture
def climate_daily_mart(sample_db):
    """Minimal mart_climate_daily.parquet spanning both distribution windows.

    climate_db's synthetic weather series only covers 2006-2024 (see
    ingestion.sample_data.WEATHER_YEARS), which has ZERO overlap with
    EARLY_WINDOW (1951-1980). That makes climate_distribution("Torino")
    legitimately return [] against climate_db: the same short-series
    limitation already documented for the anomaly columns, not a bug to
    paper over. Real ERA5 data starts in 1950 and covers both windows.

    This fixture supplies rows in both windows directly (bypassing dbt, like
    crime_mart/rates_mart above) so the bucketing/normalization logic itself
    is still exercised by a real test.
    """
    marts = sample_db / "marts"
    marts.mkdir(exist_ok=True)
    rows = []
    # early window (1951-1980): cooler days -> lower buckets
    for year, t_max in [(1960, 20.0), (1965, 22.0), (1970, 24.0)]:
        rows.append((year, t_max))
    # late window (1996-2025): warmer days -> higher buckets
    for year, t_max in [(2000, 26.0), (2010, 28.0), (2020, 30.0)]:
        rows.append((year, t_max))
    pl.DataFrame(
        [
            {
                "province_code": "IT001",
                "province_name": "Torino",
                "capital_city": "Torino",
                "region_code": "ITC1",
                "region_name": "Piemonte",
                "obs_date": f"{year}-07-15",
                "year": str(year),
                "month": 7,
                "t_min": t_max - 10.0,
                "t_mean": t_max - 5.0,
                "t_max": t_max,
            }
            for year, t_max in rows
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
