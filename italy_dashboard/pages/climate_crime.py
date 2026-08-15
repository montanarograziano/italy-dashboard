"""Summer heat against violent crime: the naive view beside the panel view.

Both scatters are shown on purpose. The raw one largely recovers "the South is
hot and reports crime differently"; putting it next to the demeaned panel makes
the confound the lesson of the page rather than a footnote nobody reads.
"""

import reflex as rx

from italy_dashboard import theme
from italy_dashboard.components import card, scatter_chart, shell, stat_tile
from italy_dashboard.i18n import t
from italy_dashboard.state import ClimateCrimeState


def climate_crime_page() -> rx.Component:
    return shell(
        rx.heading(t("climate_crime_title"), size="6", color=theme.ink_primary()),
        rx.cond(
            ClimateCrimeState.mart_ready,
            rx.vstack(
                rx.hstack(
                    stat_tile(t("cc_stat_panel"), ClimateCrimeState.stat_panel, t("cc_y_panel")),
                    stat_tile(t("cc_stat_raw"), ClimateCrimeState.stat_raw, t("cc_y_raw")),
                    stat_tile(t("cc_stat_n"), ClimateCrimeState.stat_n, t("cc_obs_note")),
                    spacing="4",
                    width="100%",
                    wrap="wrap",
                ),
                card(
                    t("cc_panel_title"),
                    t("cc_panel_sub"),
                    scatter_chart(
                        [(ClimateCrimeState.panel_points, t("cc_panel_title"), theme.series(1))],
                        x_key="x",
                        y_key="y",
                        # Doubly-demeaned axes get their own labels: +0.3 here
                        # is not "0.3 C above the 1981-2010 normal", it is what
                        # is left after region and year effects are removed.
                        x_label=t("cc_x_panel"),
                        y_label=t("cc_y_panel"),
                        label_key="region",
                        label_name=t("region"),
                        zero_lines=True,
                    ),
                ),
                card(
                    t("cc_raw_title"),
                    t("cc_raw_sub"),
                    scatter_chart(
                        [(ClimateCrimeState.raw_points, t("cc_raw_title"), theme.series(2))],
                        x_key="x",
                        y_key="y",
                        x_label=t("cc_x_raw"),
                        y_label=t("cc_y_raw"),
                        label_key="region",
                        label_name=t("region"),
                    ),
                ),
                rx.callout(t("cc_caveat"), icon="info", color_scheme="gray", width="100%"),
                spacing="5",
                width="100%",
            ),
            rx.callout(
                t("no_climate_crime"),
                icon="triangle_alert",
                color_scheme="orange",
                width="100%",
            ),
        ),
    )
