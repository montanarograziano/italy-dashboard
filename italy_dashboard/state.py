"""Reflex state: one substate per page, all reading the local DuckDB snapshot."""

from __future__ import annotations

from typing import Any, ClassVar, TypedDict, cast

import reflex as rx

from italy_dashboard import queries as q
from italy_dashboard.translations import SPLIT_LABEL_TO_KEY, SPLIT_LABELS

Row = dict[str, Any]


class GridItem(TypedDict):
    """One small-multiples panel: a city and its stripe rows.

    Typed precisely rather than as the flat `Row` alias, because Reflex infers
    the inner type from this annotation. With `list[Row]` the `rows` field
    collapses to Any inside an rx.foreach lambda and the component raises
    ForeachVarError at render time.
    """

    city: str
    rows: list[Row]


class AppState(rx.State):
    """Shared: language, data availability, region list."""

    lang: str = rx.LocalStorage("en")
    data_ready: bool = False
    regions: list[str] = []

    @rx.event
    def set_language(self, value: str):
        self.lang = value

    @rx.event
    def load_shared(self):
        self.data_ready = q.db_ready()
        self.regions = q.region_names() if self.data_ready else []


class HomeState(AppState):
    kpi_crime: str = "—"
    kpi_population: str = "—"
    kpi_unemployment: str = "—"
    kpi_inflation: str = "—"

    @rx.event
    def load(self):
        self.load_shared()
        k = q.kpis()
        self.kpi_crime = k["crime"]
        self.kpi_population = k["population"]
        self.kpi_unemployment = k["unemployment"]
        self.kpi_inflation = k["inflation"]


class CrimeState(AppState):
    """Interactive crime explorer over the dbt mart (mart_crime)."""

    # filter options (loaded from the mart)
    region_options: list[str] = []
    province_options: list[str] = []
    offence_options: list[str] = []
    sex_options: list[str] = []
    age_options: list[str] = []
    year_options: list[str] = []

    # current selections
    region: str = q.ALL
    province: str = q.ALL
    offence: str = q.ALL
    sex: str = q.ALL
    age: str = q.ALL
    split_by: str = "None"
    breakdown_year: str = ""

    # chart data
    trend_rows: list[Row] = []
    series_count: int = 0
    series_label_1: str = ""
    series_label_2: str = ""
    series_label_3: str = ""
    by_offence: list[Row] = []
    by_region: list[Row] = []
    latest_year: str = "—"
    mart_ready: bool = False

    SPLIT_KEYS: ClassVar[list[str]] = ["None", "Sex", "Age", "Region", "Offence"]

    @rx.var
    def split_label_options(self) -> list[str]:
        return [SPLIT_LABELS[self.lang][k] for k in self.SPLIT_KEYS]

    @rx.var
    def split_by_label(self) -> str:
        return SPLIT_LABELS[self.lang].get(self.split_by, self.split_by)

    @rx.event
    def load(self):
        self.load_shared()
        self.mart_ready = q.crime_mart_ready()
        if not self.mart_ready:
            return
        options = q.crime_options()
        self.region_options = options["region"]
        self.province_options = q.mart_province_options(q.CRIME_MART, self.region)
        self.offence_options = options["offence"]
        self.sex_options = options["sex"]
        self.age_options = options["age"]
        self.year_options = q.mart_years(q.CRIME_MART)
        self.latest_year = q.crime_latest_year()
        if not self.breakdown_year and self.year_options:
            self.breakdown_year = self.year_options[0]
        self._refresh()

    @rx.event
    def set_region_filter(self, value: str):
        self.region = value
        self.province = q.ALL  # provinces cascade from the region
        self.province_options = q.mart_province_options(q.CRIME_MART, value)
        self._refresh()

    @rx.event
    def set_province_filter(self, value: str):
        self.province = value
        self._refresh()

    @rx.event
    def set_breakdown_year(self, value: str):
        self.breakdown_year = value
        self._refresh()

    @rx.event
    def set_offence_filter(self, value: str):
        self.offence = value
        self._refresh()

    @rx.event
    def set_sex_filter(self, value: str):
        self.sex = value
        self._refresh()

    @rx.event
    def set_age_filter(self, value: str):
        self.age = value
        self._refresh()

    @rx.event
    def set_split_by(self, value: str):
        self.split_by = SPLIT_LABEL_TO_KEY.get(value, "None")
        self._refresh()

    def _selections(self) -> dict[str, str]:
        # A selected province narrows harder than its region, so it wins the
        # single region dimension; the scope key disambiguates the name level.
        if self.province != q.ALL:
            region, scope = self.province, "province"
        else:
            region, scope = self.region, "region"
        return {
            "region": region,
            "_region_scope": scope,
            "offence": self.offence,
            "sex": self.sex,
            "age": self.age,
        }

    def _refresh(self):
        split = None if self.split_by == "None" else self.split_by.lower()
        rows, labels = q.crime_trend_pivot(self._selections(), split)
        self.trend_rows = rows
        self.series_count = len(labels)
        self.series_label_1 = labels[0] if len(labels) > 0 else ""
        self.series_label_2 = labels[1] if len(labels) > 1 else ""
        self.series_label_3 = labels[2] if len(labels) > 2 else ""
        self.by_offence = q.crime_offence_breakdown(
            self._selections(), top_n=10, year=self.breakdown_year or None
        )
        self.by_region = q.mart_breakdown(
            q.CRIME_MART,
            "region",
            self._selections(),
            top_n=25,
            year=self.breakdown_year or None,
        )


class OffendersState(AppState):
    """Interactive explorer over mart_offenders (police-reported offenders)."""

    region_options: list[str] = []
    province_options: list[str] = []
    indicator_options: list[str] = []
    crime_options: list[str] = []
    sex_options: list[str] = []
    age_options: list[str] = []
    citizenship_options: list[str] = []
    year_options: list[str] = []

    region: str = q.ALL
    province: str = q.ALL
    indicator: str = q.ALL
    crime: str = q.ALL
    sex: str = q.ALL
    age: str = q.ALL
    citizenship: str = q.ALL
    split_by: str = "None"
    breakdown_year: str = ""

    trend_rows: list[Row] = []
    series_count: int = 0
    series_label_1: str = ""
    series_label_2: str = ""
    series_label_3: str = ""
    by_crime: list[Row] = []
    latest_year: str = "—"
    mart_ready: bool = False

    kpi_total: str = "—"
    kpi_yoy: str = "—"
    kpi_share: str = "—"
    kpi_ratio: str = "—"
    rates_rows: list[Row] = []
    region_ranking: list[Row] = []
    share_rows: list[Row] = []
    income_years: list[str] = []
    income_year: str = ""
    income_itl: list[Row] = []
    income_frg: list[Row] = []
    corr_itl: str = "—"
    corr_frg: str = "—"
    income_ready: bool = False

    SPLIT_KEYS: ClassVar[list[str]] = [
        "None",
        "Citizenship",
        "Sex",
        "Age",
        "Region",
        "Crime",
    ]

    @rx.var
    def split_label_options(self) -> list[str]:
        return [SPLIT_LABELS[self.lang][k] for k in self.SPLIT_KEYS]

    @rx.var
    def split_by_label(self) -> str:
        return SPLIT_LABELS[self.lang].get(self.split_by, self.split_by)

    @rx.event
    def reset_filters(self):
        self.region = q.ALL
        self.province = q.ALL
        self.province_options = q.mart_province_options(q.OFFENDERS_MART, q.ALL)
        self.crime = q.ALL
        self.sex = q.ALL
        self.age = q.ALL
        self.citizenship = q.ALL
        self.split_by = "None"
        if len(self.indicator_options) > 2:
            self.indicator = self.indicator_options[1]
        else:
            self.indicator = q.ALL
        self._refresh()

    @rx.event
    def load(self):
        self.load_shared()
        self.mart_ready = q.mart_ready(q.OFFENDERS_MART)
        if not self.mart_ready:
            return
        options = q.mart_options(q.OFFENDERS_MART)
        self.region_options = options["region"]
        self.province_options = q.mart_province_options(q.OFFENDERS_MART, self.region)
        self.year_options = q.mart_years(q.OFFENDERS_MART)
        if not self.breakdown_year and self.year_options:
            self.breakdown_year = self.year_options[0]
        self.indicator_options = options["indicator"]
        self.crime_options = options["crime"]
        self.sex_options = options["sex"]
        self.age_options = options["age"]
        self.citizenship_options = options["citizenship"]
        # Indicators (reported vs arrested, ...) are alternative counts of the
        # same people: summing them double-counts. Default to the first
        # concrete indicator instead of "All" when there are several.
        if len(self.indicator_options) > 2 and self.indicator == q.ALL:
            self.indicator = self.indicator_options[1]
        self.latest_year = q.mart_latest_year(q.OFFENDERS_MART)
        self._refresh()

    @rx.event
    def set_region_filter(self, value: str):
        self.region = value
        self.province = q.ALL  # provinces cascade from the region
        self.province_options = q.mart_province_options(q.OFFENDERS_MART, value)
        self._refresh()

    @rx.event
    def set_province_filter(self, value: str):
        self.province = value
        self._refresh()

    @rx.event
    def set_breakdown_year(self, value: str):
        self.breakdown_year = value
        self._refresh()

    @rx.event
    def set_indicator_filter(self, value: str):
        self.indicator = value
        self._refresh()

    @rx.event
    def set_crime_filter(self, value: str):
        self.crime = value
        self._refresh()

    @rx.event
    def set_sex_filter(self, value: str):
        self.sex = value
        self._refresh()

    @rx.event
    def set_age_filter(self, value: str):
        self.age = value
        self._refresh()

    @rx.event
    def set_citizenship_filter(self, value: str):
        self.citizenship = value
        self._refresh()

    @rx.event
    def set_split_by(self, value: str):
        self.split_by = SPLIT_LABEL_TO_KEY.get(value, "None")
        self._refresh()

    def _selections(self) -> dict[str, str]:
        # A selected province narrows harder than its region, so it wins the
        # single region dimension; the scope key disambiguates the name level.
        if self.province != q.ALL:
            region, scope = self.province, "province"
        else:
            region, scope = self.region, "region"
        return {
            "region": region,
            "_region_scope": scope,
            "indicator": self.indicator,
            "crime": self.crime,
            "sex": self.sex,
            "age": self.age,
            "citizenship": self.citizenship,
        }

    def _refresh(self):
        split = None if self.split_by == "None" else self.split_by.lower()
        rows, labels = q.mart_trend_pivot(q.OFFENDERS_MART, self._selections(), split)
        self.trend_rows = rows
        self.series_count = len(labels)
        self.series_label_1 = labels[0] if len(labels) > 0 else ""
        self.series_label_2 = labels[1] if len(labels) > 1 else ""
        self.series_label_3 = labels[2] if len(labels) > 2 else ""
        self.by_crime = q.mart_breakdown(
            q.OFFENDERS_MART,
            "crime",
            self._selections(),
            top_n=10,
            year=self.breakdown_year or None,
        )
        # rates use resident-population denominators, which exist per region
        # (not per province): the rate card follows the region filter only
        self.rates_rows = q.offender_rates(self.region, self.crime)
        self.region_ranking = q.region_rate_ranking(
            self.breakdown_year or None, self.citizenship, self.crime
        )
        self.share_rows = q.offender_foreign_share(self._selections())
        kpis = q.offenders_kpis(self._selections())
        self.kpi_total = kpis["total"]
        self.kpi_yoy = kpis["yoy"]
        self.kpi_share = kpis["share"]
        self.kpi_ratio = kpis["rate_ratio"]
        self._refresh_income()

    @rx.event
    def set_income_year(self, value: str):
        self.income_year = value
        self._refresh_income()

    def _refresh_income(self):
        if not self.income_years:
            self.income_years = q.income_years()
        self.income_ready = bool(self.income_years)
        if not self.income_ready:
            return
        if self.income_year not in self.income_years:
            self.income_year = self.income_years[0]
        scatter = q.income_scatter(self.income_year)
        self.income_itl = scatter["ITL"]
        self.income_frg = scatter["FRG"]
        corr = q.income_correlations(self.income_year)
        self.corr_itl = corr["ITL"]
        self.corr_frg = corr["FRG"]


class PopulationState(AppState):
    region: str = q.NATIONAL
    residents: list[Row] = []
    foreign_share: list[Row] = []

    @rx.event
    def load(self):
        self.load_shared()
        self._refresh()

    @rx.event
    def set_region_filter(self, value: str):
        self.region = value
        self._refresh()

    def _refresh(self):
        self.residents = q.population_timeseries(self.region)
        self.foreign_share = q.foreign_share_timeseries(self.region)


class LaborState(AppState):
    region: str = q.NATIONAL
    series: list[Row] = []

    @rx.event
    def load(self):
        self.load_shared()
        self._refresh()

    @rx.event
    def set_region_filter(self, value: str):
        self.region = value
        self._refresh()

    def _refresh(self):
        self.series = q.unemployment_series(self.region)


class EconomyState(AppState):
    inflation: list[Row] = []

    @rx.event
    def load(self):
        self.load_shared()
        self.inflation = q.inflation_series()


class ClimateState(AppState):
    """Climate explorer over the mart_climate_* marts."""

    city_options: list[str] = []
    city: str = ""
    annual: list[Row] = []
    stripes: list[Row] = []
    ranking: list[Row] = []
    stripes_grid: list[GridItem] = []
    thresholds: list[Row] = []
    distribution: list[Row] = []
    mart_ready: bool = False

    @rx.event
    def load(self):
        self.load_shared()
        self.mart_ready = q.climate_ready()
        if not self.mart_ready:
            return
        self.city_options = q.climate_cities()
        # Roma is the default when present: a familiar reference point beats an
        # alphabetically-first city nobody has intuitions about.
        if self.city not in self.city_options:
            self.city = "Roma" if "Roma" in self.city_options else self.city_options[0]
        self.ranking = q.warming_rate_ranking(top_n=20)
        # `climate_stripes_grid` returns `list[Row]` (the flat, broadly-used
        # alias); `GridItem` narrows the shape for Reflex's benefit only, at
        # this one boundary. The runtime values already conform (`{"city":
        # str, "rows": list[Row]}`); this is a static-typing reconciliation,
        # not a runtime coercion.
        self.stripes_grid = cast(list[GridItem], q.climate_stripes_grid(limit=12))
        self._refresh()

    @rx.event
    def set_city(self, value: str):
        self.city = value
        self._refresh()

    def _refresh(self):
        self.annual = q.climate_annual_series(self.city)
        self.stripes = q.climate_stripes(self.city)
        self.thresholds = q.climate_threshold_days(self.city)
        self.distribution = q.climate_distribution(self.city)


class ClimateCrimeState(AppState):
    """Region x year panel: summer heat against violent offending."""

    raw_points: list[Row] = []
    panel_points: list[Row] = []
    stat_raw: str = "—"
    stat_panel: str = "—"
    stat_n: str = "0"
    mart_ready: bool = False

    @rx.event
    def load(self):
        self.load_shared()
        self.mart_ready = q.crime_climate_ready()
        if not self.mart_ready:
            return
        scatter = q.crime_climate_scatter()
        self.raw_points = scatter["raw"]
        self.panel_points = scatter["panel"]
        stats = q.crime_climate_stats()
        self.stat_raw = stats["raw"]
        self.stat_panel = stats["panel"]
        self.stat_n = stats["n"]
