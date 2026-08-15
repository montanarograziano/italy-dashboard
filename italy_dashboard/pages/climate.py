"""Climate page: warming trend, anomalies, per-city warming rate, thresholds."""

import reflex as rx

from italy_dashboard import theme
from italy_dashboard.components import (
    card,
    data_table,
    h_bar_chart,
    line_chart,
    shell,
    stripe_chart,
)
from italy_dashboard.i18n import t
from italy_dashboard.state import ClimateState


def _city_select() -> rx.Component:
    return rx.hstack(
        rx.text(t("city"), color=theme.INK_SECONDARY, font_size="0.9em"),
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
            rx.heading(t("climate_title"), size="6", color=theme.INK_PRIMARY),
            rx.spacer(),
            _city_select(),
            width="100%",
            align="center",
        ),
        rx.cond(
            ClimateState.mart_ready,
            rx.vstack(
                card(
                    t("warming_title"),
                    t("warming_sub"),
                    line_chart(
                        ClimateState.annual,
                        [
                            ("t_max", t("t_max"), theme.SERIES_2),
                            ("t_mean", t("t_mean"), theme.SERIES_1),
                            ("t_min", t("t_min"), theme.SERIES_3),
                        ],
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
                    t("ranking_title"),
                    t("ranking_sub"),
                    h_bar_chart(ClimateState.ranking, "value", "name", theme.SERIES_1),
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
                            ("hot_days", t("hot_days"), theme.SERIES_2),
                            ("tropical_nights", t("tropical_nights"), theme.SERIES_1),
                            ("frost_days", t("frost_days"), theme.SERIES_3),
                        ],
                    ),
                ),
                card(
                    t("distribution_title"),
                    t("distribution_sub"),
                    line_chart(
                        ClimateState.distribution,
                        [
                            ("early", t("dist_early"), theme.SERIES_1),
                            ("late", t("dist_late"), theme.SERIES_2),
                        ],
                    ),
                ),
                spacing="5",
                width="100%",
            ),
            rx.callout(t("no_climate"), icon="triangle_alert", color_scheme="orange", width="100%"),
        ),
    )
