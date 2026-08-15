import reflex as rx

from italy_dashboard import theme
from italy_dashboard.components import card, data_table, line_chart, region_select, shell
from italy_dashboard.i18n import t
from italy_dashboard.state import LaborState


def labor_page() -> rx.Component:
    return shell(
        rx.hstack(
            rx.heading(t("labor_title"), size="6", color=theme.ink_primary()),
            rx.spacer(),
            region_select(LaborState.region, LaborState.set_region_filter),
            width="100%",
            align="center",
        ),
        card(
            t("unemployment_title"),
            t("unemployment_sub"),
            line_chart(
                LaborState.series,
                [
                    ("selected", t("selected_region"), theme.series(1)),
                    ("national", t("national_avg"), theme.series(2)),
                ],
            ),
            data_table(
                LaborState.series,
                [
                    ("period", t("year")),
                    ("selected", t("selected_pct")),
                    ("national", t("national_pct")),
                ],
            ),
        ),
    )
