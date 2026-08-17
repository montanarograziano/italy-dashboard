"""Reflex state: one substate per page, all reading the local DuckDB snapshot."""

from __future__ import annotations

from typing import Any, ClassVar, TypedDict, cast

import reflex as rx

from italy_dashboard import queries as q
from italy_dashboard.translations import EN, IT, SPLIT_LABEL_TO_KEY, SPLIT_LABELS

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


def _coverage_text(
    lang: str,
    capitals: str,
    capitals_total: str,
    regions: str,
    regions_total: str,
    year_start: str,
    year_end: str,
) -> str:
    """Format the "Coverage: N of M capitals, ..." line for one language.

    The numbers come from `queries.climate_coverage()` and are language
    invariant; only the sentence template (`translations.EN`/`IT`) varies.
    Reflex Vars cannot be `.format()`-ed the way a plain Python string can, so
    this runs inside a `@rx.var` computed property (backend, plain values),
    not inside a page's render tree.
    """
    template = IT["climate_coverage"] if lang == "it" else EN["climate_coverage"]
    return template.format(
        capitals=capitals,
        capitals_total=capitals_total,
        regions=regions,
        regions_total=regions_total,
        year_start=year_start,
        year_end=year_end,
    )


def _format_translation(lang: str, key: str, /, **values: str) -> str:
    """One translated template filled in for a language.

    Same constraint as `_coverage_text` above: Reflex Vars cannot be
    `.format()`-ed, so every templated label has to resolve in a backend
    `@rx.var` over plain values, never in a page's render tree. Extra `values`
    are tolerated (`str.format` ignores what a template does not reference), so
    callers can pass one bundle of substitutions to several related keys.
    """
    table = IT if lang == "it" else EN
    return table[key].format(**values)


class AppState(rx.State):
    """Shared: language, data availability, region list.

    `has_loaded` is deliberately NOT declared here even though it looks
    "shared" like `data_ready`/`regions`. Reflex mounts exactly ONE AppState
    node per browser session, with every page state (ClimateState, CrimeState,
    ...) as a sibling child of it; a field declared here is the SAME storage
    slot no matter which page's `load()` last wrote it. `data_ready` is safe
    to share that way because it reflects a session-invariant fact (does
    data/ exist at all) that stays correct once any page has checked it. A
    "have I loaded" flag is the opposite: it needs to be False again on every
    NOT-yet-visited page, even after some OTHER page in the same session has
    already finished loading — otherwise navigating from a loaded page to a
    fresh one would show that fresh page's still-default `mart_ready=False`
    as "loaded and empty" (the error callout) for the brief window before its
    OWN `load()` completes, reintroducing the exact flash this fix removes,
    just moved from first paint to every subsequent first-visit. So
    `has_loaded` is declared separately on each concrete page state below,
    each set True at the END of that state's own `load()`, and threaded into
    `components.shell()` explicitly rather than read off AppState.
    """

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
    # See AppState's docstring: page-scoped, not inherited, so a not-yet-
    # visited page never inherits "loaded" from a page visited earlier.
    has_loaded: bool = False

    @rx.event
    def load(self):
        self.load_shared()
        k = q.kpis()
        self.kpi_crime = k["crime"]
        self.kpi_population = k["population"]
        self.kpi_unemployment = k["unemployment"]
        self.kpi_inflation = k["inflation"]
        self.has_loaded = True


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
    has_loaded: bool = False  # see AppState's docstring: page-scoped, not inherited

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
        if self.mart_ready:
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
        self.has_loaded = True

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
    has_loaded: bool = False  # see AppState's docstring: page-scoped, not inherited

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
        if self.mart_ready:
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
            # Indicators (reported vs arrested, ...) are alternative counts of
            # the same people: summing them double-counts. Default to the
            # first concrete indicator instead of "All" when there are several.
            if len(self.indicator_options) > 2 and self.indicator == q.ALL:
                self.indicator = self.indicator_options[1]
            self.latest_year = q.mart_latest_year(q.OFFENDERS_MART)
            self._refresh()
        self.has_loaded = True

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
    has_loaded: bool = False  # see AppState's docstring: page-scoped, not inherited

    @rx.event
    def load(self):
        self.load_shared()
        self._refresh()
        self.has_loaded = True

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
    has_loaded: bool = False  # see AppState's docstring: page-scoped, not inherited

    @rx.event
    def load(self):
        self.load_shared()
        self._refresh()
        self.has_loaded = True

    @rx.event
    def set_region_filter(self, value: str):
        self.region = value
        self._refresh()

    def _refresh(self):
        self.series = q.unemployment_series(self.region)


class EconomyState(AppState):
    inflation: list[Row] = []
    has_loaded: bool = False  # see AppState's docstring: page-scoped, not inherited

    @rx.event
    def load(self):
        self.load_shared()
        self.inflation = q.inflation_series()
        self.has_loaded = True


class ClimateState(AppState):
    """Climate explorer over the mart_climate_* marts, at three scopes.

    `region` and `city` cascade exactly like CrimeState's region/province
    (see queries.mart_province_options): picking a city narrows to CITY
    scope; leaving `city` at `q.ALL` shows whichever `region` is selected —
    `q.ITALIA` by default, the broadest level of the hierarchy. Unlike the
    crime marts' "All" dimension handling, Italia needs no special-case SQL:
    mart_climate_region already carries it as a plain region row (see
    queries.ITALIA), so `region` alone decides between city-scope queries
    (mart_climate_annual) and region-scope queries (mart_climate_region).
    """

    region_options: list[str] = []
    region: str = q.ITALIA
    city_options: list[str] = []
    city: str = q.ALL
    annual: list[Row] = []
    stripes: list[Row] = []
    ranking: list[Row] = []
    stripes_grid: list[GridItem] = []
    thresholds: list[Row] = []
    distribution: list[Row] = []
    mart_ready: bool = False
    has_loaded: bool = False  # see AppState's docstring: page-scoped, not inherited

    # Coverage: how much of Italy mart_climate_annual actually has data for
    # (see queries.climate_coverage). Populated even when the mart is empty,
    # so the totals (from the seed) always show.
    capitals_included: str = "0"
    capitals_total: str = "0"
    regions_included: str = "0"
    regions_total: str = "0"
    year_start: str = "—"
    year_end: str = "—"

    # Distribution-card windows, derived per city (see
    # queries.climate_distribution_windows). Held as strings because they only
    # ever reach the UI as label text, and "—" reads as "this city has no
    # drawable split" in a way that a 0 would not.
    dist_early_lo: str = "—"
    dist_early_hi: str = "—"
    dist_late_lo: str = "—"
    dist_late_hi: str = "—"

    def _dist_window_values(self) -> dict[str, str]:
        return {
            "early_lo": self.dist_early_lo,
            "early_hi": self.dist_early_hi,
            "late_lo": self.dist_late_lo,
            "late_hi": self.dist_late_hi,
        }

    @rx.var
    def distribution_sub(self) -> str:
        return _format_translation(self.lang, "distribution_sub", **self._dist_window_values())

    @rx.var
    def dist_early_label(self) -> str:
        return _format_translation(self.lang, "dist_early", **self._dist_window_values())

    @rx.var
    def dist_late_label(self) -> str:
        return _format_translation(self.lang, "dist_late", **self._dist_window_values())

    @rx.var
    def coverage_text(self) -> str:
        return _coverage_text(
            self.lang,
            self.capitals_included,
            self.capitals_total,
            self.regions_included,
            self.regions_total,
            self.year_start,
            self.year_end,
        )

    @rx.var
    def is_city_scope(self) -> bool:
        """Whether a single city, rather than a region or Italia, is
        selected. Used by the distribution card (city-only: see
        queries.climate_distribution_windows's docstring) to show an
        explanatory line instead of its em-dash placeholder when the scope
        is too broad for a daily histogram to exist at all.
        """
        return self.city != q.ALL

    @rx.var
    def highlighted_city(self) -> str:
        """The city to call out in the cross-city ranking/grid, or "" (never
        a real city name) when nothing should be highlighted.

        Only CITY scope has a single entity to point at; region and Italia
        scope each select many cities at once, so nothing is emphasised
        there — see `components.h_bar_chart`/`small_multiples`'s own
        docstrings for how an empty string disables their highlight.
        """
        return self.city if self.is_city_scope else ""

    @rx.var
    def city_outside_ranking_note(self) -> str:
        """ "{city} is not among the top 20..." when a city is selected but
        absent from `ranking`, else "" (nothing to say).

        `climate_stripes_grid`'s top 12 is a strict subset of `ranking`'s top
        20 (both order by the same warming rate), so a city outside the
        ranking entirely gets NO visual acknowledgement anywhere on the page:
        neither the ranking's outline nor the grid's ring. Without this note
        that reads as a broken feature; with it, it reads as "not in the top
        20" — a real, distinguishable state, not a bug.
        """
        if not self.is_city_scope:
            return ""
        if any(r["name"] == self.city for r in self.ranking):
            return ""
        return _format_translation(self.lang, "city_outside_ranking", city=self.city)

    @rx.var
    def selected_scope_title(self) -> str:
        """The translated "Selected scope: {name}" heading, for whichever
        entity the "selected scope" cards below are showing: the city if one
        is picked, else the region (Italia by default). Templated because
        the entity name is a runtime value — see `_format_translation`'s
        docstring for why this cannot be a plain f-string over a Reflex Var.
        """
        name = self.city if self.city != q.ALL else self.region
        return _format_translation(self.lang, "selected_scope_title", name=name)

    @rx.event
    def load(self):
        self.load_shared()
        # BOTH marts, not just climate_ready(): the default scope is now
        # Italia (region scope), so an older snapshot that has
        # mart_climate_annual but predates mart_climate_region would
        # otherwise report ready, collapse region_options to just ["Italia"],
        # and silently render every "Selected scope" card empty with no
        # callout — the only way out being to pick a city by hand. Gating on
        # both is an all-or-nothing trade-off (it also hides the four
        # city-capable cards on that same old snapshot, even though they
        # would work), accepted deliberately: a page that claims ready and
        # renders nothing is worse than one that honestly says it isn't.
        self.mart_ready = q.climate_ready() and q.climate_region_ready()
        coverage = q.climate_coverage()
        self.capitals_included = coverage["capitals"]
        self.capitals_total = coverage["capitals_total"]
        self.regions_included = coverage["regions"]
        self.regions_total = coverage["regions_total"]
        self.year_start = coverage["year_start"]
        self.year_end = coverage["year_end"]
        if self.mart_ready:
            self.region_options = q.climate_region_options()
            if self.region not in self.region_options:
                self.region = q.ITALIA
            self.city_options = q.climate_city_options(self.region)
            if self.city not in self.city_options:
                self.city = q.ALL
            self.ranking = q.warming_rate_ranking(top_n=20)
            # `climate_stripes_grid` returns `list[Row]` (the flat, broadly-
            # used alias); `GridItem` narrows the shape for Reflex's benefit
            # only, at this one boundary. The runtime values already conform
            # (`{"city": str, "rows": list[Row]}`); this is a static-typing
            # reconciliation, not a runtime coercion.
            self.stripes_grid = cast(list[GridItem], q.climate_stripes_grid(limit=12))
            self._refresh()
        self.has_loaded = True

    @rx.event
    def set_region(self, value: str):
        self.region = value
        self.city = q.ALL  # city cascades from region: broaden back out
        self.city_options = q.climate_city_options(value)
        self._refresh()

    @rx.event
    def set_city(self, value: str):
        self.city = value
        self._refresh()

    def _refresh(self):
        if self.city != q.ALL:
            self.annual = q.climate_annual_series(self.city)
            self.stripes = q.climate_stripes(self.city)
            self.thresholds = q.climate_threshold_days(self.city)
            # Resolved once and passed down: the card labels and the
            # histogram must describe the SAME two windows, and a second
            # lookup is a second chance for them to disagree.
            windows = q.climate_distribution_windows(self.city)
            self.distribution = q.climate_distribution(self.city, windows)
            self.dist_early_lo, self.dist_early_hi, self.dist_late_lo, self.dist_late_hi = (
                [str(year) for year in windows] if windows else ["—"] * 4
            )
        else:
            self.annual = q.climate_region_annual_series(self.region)
            self.stripes = q.climate_region_stripes(self.region)
            self.thresholds = q.climate_region_threshold_days(self.region)
            # Region/Italia scope has no drawable distribution:
            # mart_climate_region holds yearly aggregates only, never the
            # daily readings the histogram needs (see
            # queries.climate_distribution's docstring). This sets the
            # card's EXISTING empty state (the same one a city with under
            # two complete years already gets) rather than querying with a
            # region name, which would just silently reach the same empty
            # result through capital_city matching nothing.
            self.distribution = []
            self.dist_early_lo = self.dist_early_hi = self.dist_late_lo = self.dist_late_hi = "—"


class ClimateCrimeState(AppState):
    """Region x year panel: summer heat against violent offending."""

    raw_points: list[Row] = []
    panel_points: list[Row] = []
    stat_raw: str = "—"
    stat_panel: str = "—"
    stat_n: str = "0"
    mart_ready: bool = False
    has_loaded: bool = False  # see AppState's docstring: page-scoped, not inherited

    # Coverage: see ClimateState. This page's whole argument is that the raw
    # scatter recovers a north-south confound; with partial, mostly-northern
    # coverage that confound may not appear, so this is surfaced prominently
    # rather than as a footnote (see cc_coverage_note in translations.py).
    capitals_included: str = "0"
    capitals_total: str = "0"
    regions_included: str = "0"
    regions_total: str = "0"
    year_start: str = "—"
    year_end: str = "—"

    @rx.var
    def coverage_text(self) -> str:
        return _coverage_text(
            self.lang,
            self.capitals_included,
            self.capitals_total,
            self.regions_included,
            self.regions_total,
            self.year_start,
            self.year_end,
        )

    @rx.event
    def load(self):
        self.load_shared()
        self.mart_ready = q.crime_climate_ready()
        coverage = q.climate_coverage()
        self.capitals_included = coverage["capitals"]
        self.capitals_total = coverage["capitals_total"]
        self.regions_included = coverage["regions"]
        self.regions_total = coverage["regions_total"]
        self.year_start = coverage["year_start"]
        self.year_end = coverage["year_end"]
        if self.mart_ready:
            scatter = q.crime_climate_scatter()
            self.raw_points = scatter["raw"]
            self.panel_points = scatter["panel"]
            stats = q.crime_climate_stats()
            self.stat_raw = stats["raw"]
            self.stat_panel = stats["panel"]
            self.stat_n = stats["n"]
        self.has_loaded = True
