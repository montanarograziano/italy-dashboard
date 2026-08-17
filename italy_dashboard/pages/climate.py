"""Climate page: warming trend, anomalies, per-city warming rate, thresholds."""

import reflex as rx

from italy_dashboard import theme
from italy_dashboard.components import (
    area_compare_chart,
    band_trend_chart,
    card,
    data_gate,
    data_table,
    h_bar_chart,
    line_chart,
    shell,
    small_multiples,
    stripe_chart,
)
from italy_dashboard.i18n import t
from italy_dashboard.state import ClimateState


def _scope_selects() -> rx.Component:
    """Italia -> region -> city cascade (see queries.mart_province_options
    for the pattern this mirrors, and ClimateState's own docstring for how
    `region`/`city` decide the scope). Picking a city narrows the "selected
    scope" cards below to that city; leaving city at `q.ALL` shows the
    picked region, or Italia by default.
    """
    return rx.hstack(
        rx.text(t("region"), color=theme.ink_secondary(), font_size="0.9em"),
        rx.select(
            ClimateState.region_options,
            value=ClimateState.region,
            on_change=ClimateState.set_region,
            width="200px",
        ),
        rx.text(t("city"), color=theme.ink_secondary(), font_size="0.9em"),
        rx.select(
            ClimateState.city_options,
            value=ClimateState.city,
            on_change=ClimateState.set_city,
            width="200px",
        ),
        align="center",
        spacing="3",
    )


def _section_heading(label: str | rx.Var) -> rx.Component:
    return rx.heading(label, size="5", color=theme.ink_primary(), margin_top="0.5em")


def _selected_scope_section() -> rx.Component:
    """Warming line, stripes, threshold days, distribution: everything the
    region/city cascade above actually filters (see ClimateState._refresh).
    """
    return rx.fragment(
        _section_heading(ClimateState.selected_scope_title),
        card(
            t("warming_title"),
            t("warming_sub"),
            band_trend_chart(
                ClimateState.annual,
                band_key="t_band",
                mean_key="t_mean",
                rolling_key="t_rolling",
                band_label=t("t_band"),
                mean_label=t("t_mean"),
                rolling_label=t("t_rolling"),
                color=theme.series(1),
            ),
            data_table(
                ClimateState.annual,
                [
                    ("period", t("year")),
                    ("t_min", t("t_min")),
                    ("t_mean", t("t_mean")),
                    ("t_max", t("t_max")),
                ],
            ),
        ),
        card(
            t("stripes_title"),
            t("stripes_sub"),
            stripe_chart(ClimateState.stripes),
            data_table(
                ClimateState.stripes,
                [("period", t("year")), ("anomaly", t("anomaly"))],
            ),
        ),
        card(
            t("thresholds_title"),
            t("thresholds_sub"),
            line_chart(
                ClimateState.thresholds,
                [
                    ("hot_days", t("hot_days"), theme.series(2)),
                    ("tropical_nights", t("tropical_nights"), theme.series(1)),
                    ("frost_days", t("frost_days"), theme.series(3)),
                ],
            ),
        ),
        card(
            t("distribution_title"),
            # Not `t(...)`: these three labels are templates filled with the
            # selected city's derived windows, so they resolve in
            # ClimateState rather than in the render tree. At region/Italia
            # scope ClimateState._refresh leaves `distribution` empty and
            # these windows at "—" — mart_climate_region has no daily rows to
            # draw a histogram from, so this card falls back to the same
            # empty state a too-short city record already gets, on purpose.
            ClimateState.distribution_sub,
            area_compare_chart(
                ClimateState.distribution,
                [
                    ("early", ClimateState.dist_early_label, theme.series(1)),
                    ("late", ClimateState.dist_late_label, theme.series(2)),
                ],
            ),
        ),
    )


def _across_italy_section() -> rx.Component:
    """The fastest-warming ranking and the small-multiples grid: CROSS-CITY
    by nature (filtering a ranking to one city would destroy the comparison
    it exists to show), so the region/city cascade above never filters
    these. At CITY scope they instead ACKNOWLEDGE the selection — the
    selected city's bar outlined, its panel ringed — via
    ClimateState.highlighted_city, which is "" (nothing highlighted) at
    region and Italia scope, where there is no single city to point at.
    """
    return rx.fragment(
        _section_heading(t("across_italy_section")),
        card(
            t("ranking_title"),
            t("ranking_sub"),
            h_bar_chart(
                ClimateState.ranking,
                "value",
                "name",
                theme.series(1),
                highlight=ClimateState.highlighted_city,
            ),
            data_table(
                ClimateState.ranking,
                [("name", t("city")), ("value", t("degrees_per_decade"))],
            ),
        ),
        card(
            t("grid_title"),
            t("grid_sub"),
            small_multiples(ClimateState.stripes_grid, highlight=ClimateState.highlighted_city),
        ),
    )


def climate_page() -> rx.Component:
    return shell(
        rx.hstack(
            rx.heading(t("climate_title"), size="6", color=theme.ink_primary()),
            rx.spacer(),
            _scope_selects(),
            width="100%",
            align="center",
        ),
        data_gate(
            ClimateState.has_loaded,
            ClimateState.mart_ready,
            rx.vstack(
                rx.text(
                    ClimateState.coverage_text,
                    color=theme.ink_secondary(),
                    font_size="0.9em",
                    font_weight="600",
                ),
                _selected_scope_section(),
                _across_italy_section(),
                spacing="5",
                width="100%",
            ),
            rx.callout(t("no_climate"), icon="triangle_alert", color_scheme="orange", width="100%"),
        ),
        has_loaded=ClimateState.has_loaded,
    )
