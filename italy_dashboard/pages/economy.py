import reflex as rx

from italy_dashboard import theme
from italy_dashboard.components import bar_chart, card, data_table, shell
from italy_dashboard.i18n import t
from italy_dashboard.state import EconomyState


def economy_page() -> rx.Component:
    return shell(
        rx.heading(t("economy_title"), size="6", color=theme.ink_primary()),
        card(
            t("inflation_title"),
            t("inflation_sub"),
            bar_chart(
                EconomyState.inflation,
                data_key="value",
                x_key="period",
                color=theme.series(1),
            ),
            data_table(
                EconomyState.inflation,
                [("period", t("year")), ("value", t("change_pct"))],
            ),
        ),
    )
