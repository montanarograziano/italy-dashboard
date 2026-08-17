import reflex as rx

from italy_dashboard import theme
from italy_dashboard.components import shell, stat_tile
from italy_dashboard.i18n import t
from italy_dashboard.state import HomeState


def home_page() -> rx.Component:
    return shell(
        rx.heading(t("home_title"), size="6", color=theme.ink_primary()),
        rx.text(t("home_subtitle"), color=theme.ink_secondary()),
        rx.flex(
            stat_tile(t("kpi_crime"), HomeState.kpi_crime, t("kpi_crime_note")),
            stat_tile(t("kpi_population"), HomeState.kpi_population, t("kpi_population_note")),
            stat_tile(
                t("kpi_unemployment"), HomeState.kpi_unemployment, t("kpi_unemployment_note")
            ),
            stat_tile(t("kpi_inflation"), HomeState.kpi_inflation, t("kpi_inflation_note")),
            wrap="wrap",
            gap="1em",
            width="100%",
        ),
        has_loaded=HomeState.has_loaded,
    )
