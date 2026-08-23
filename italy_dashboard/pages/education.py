import reflex as rx

from italy_dashboard import theme
from italy_dashboard.components import card, data_gate, data_table, h_bar_chart, shell
from italy_dashboard.i18n import t
from italy_dashboard.state import EducationState


def education_page() -> rx.Component:
    return shell(
        rx.heading(t("education_title"), size="6", color=theme.ink_primary()),
        data_gate(
            EducationState.has_loaded,
            EducationState.dsu_ready,
            card(
                t("dsu_ranking_title"),
                t("dsu_ranking_sub"),
                h_bar_chart(
                    EducationState.dsu_ranking,
                    "value",
                    "name",
                    theme.series(1),
                ),
                data_table(
                    EducationState.dsu_ranking,
                    [("name", t("region")), ("value", t("scholarships_granted"))],
                ),
            ),
            rx.text(t("no_mart"), color=theme.ink_muted()),
        ),
        has_loaded=EducationState.has_loaded,
    )
