import reflex as rx

from italy_dashboard import theme
from italy_dashboard.components import card, data_table, line_chart, region_select, shell
from italy_dashboard.i18n import t
from italy_dashboard.state import PopulationState


def population_page() -> rx.Component:
    return shell(
        rx.hstack(
            rx.heading(t("population_title"), size="6", color=theme.INK_PRIMARY),
            rx.spacer(),
            region_select(PopulationState.region, PopulationState.set_region_filter),
            width="100%",
            align="center",
        ),
        # Residents (millions) and foreign share (%) are different scales:
        # two charts, never a dual axis.
        card(
            t("residents_title"),
            t("residents_sub"),
            line_chart(
                PopulationState.residents,
                [("value", t("residents"), theme.SERIES_1)],
            ),
            data_table(
                PopulationState.residents,
                [("period", t("year")), ("value", t("residents"))],
            ),
        ),
        card(
            t("foreign_share_title"),
            t("foreign_share_sub"),
            line_chart(
                PopulationState.foreign_share,
                [("value", t("share_label"), theme.SERIES_2)],
            ),
            data_table(
                PopulationState.foreign_share,
                [("period", t("year")), ("value", t("share_label"))],
            ),
        ),
    )
