"""Climate page: warming trend, anomalies, per-city warming rate, thresholds."""

import reflex as rx

from italy_dashboard import theme
from italy_dashboard.components import (
    area_compare_chart,
    band_trend_chart,
    card,
    data_table,
    h_bar_chart,
    line_chart,
    shell,
    small_multiples,
    stripe_chart,
)
from italy_dashboard.i18n import t
from italy_dashboard.state import ClimateState


def _city_select() -> rx.Component:
    return rx.hstack(
        rx.text(t("city"), color=theme.ink_secondary(), font_size="0.9em"),
        rx.select(
            ClimateState.city_options,
            value=ClimateState.city,
            on_change=ClimateState.set_city,
            width="260px",
        ),
        align="center",
        spacing="3",
    )


def climate_page() -> rx.Component:
    return shell(
        rx.hstack(
            rx.heading(t("climate_title"), size="6", color=theme.ink_primary()),
            rx.spacer(),
            _city_select(),
            width="100%",
            align="center",
        ),
        rx.cond(
            ClimateState.mart_ready,
            rx.vstack(
                rx.text(
                    ClimateState.coverage_text,
                    color=theme.ink_secondary(),
                    font_size="0.9em",
                    font_weight="600",
                ),
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
                    t("grid_title"),
                    t("grid_sub"),
                    small_multiples(ClimateState.stripes_grid),
                ),
                card(
                    t("ranking_title"),
                    t("ranking_sub"),
                    h_bar_chart(ClimateState.ranking, "value", "name", theme.series(1)),
                    data_table(
                        ClimateState.ranking,
                        [("name", t("city")), ("value", t("degrees_per_decade"))],
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
                    t("distribution_sub"),
                    area_compare_chart(
                        ClimateState.distribution,
                        [
                            ("early", t("dist_early"), theme.series(1)),
                            ("late", t("dist_late"), theme.series(2)),
                        ],
                    ),
                ),
                spacing="5",
                width="100%",
            ),
            rx.callout(t("no_climate"), icon="triangle_alert", color_scheme="orange", width="100%"),
        ),
    )
