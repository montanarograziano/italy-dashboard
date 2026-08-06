from typing import Any

import reflex as rx

from italy_dashboard import theme
from italy_dashboard.components import (
    card,
    data_table,
    h_bar_chart,
    line_chart,
    scatter_chart,
    shell,
    stat_tile,
)
from italy_dashboard.i18n import t
from italy_dashboard.state import CrimeState, OffendersState


def _labeled_select(
    label: str | rx.Var,
    options: rx.Var | list[str],
    value: rx.Var | str,
    on_change: Any,
    disabled: rx.Var | bool = False,
) -> rx.Component:
    return rx.vstack(
        rx.text(label, color=theme.INK_SECONDARY, font_size="0.8em"),
        rx.select(options, value=value, on_change=on_change, disabled=disabled, width="160px"),
        spacing="1",
    )


def _trend_chart(state: type[CrimeState] | type[OffendersState], single_label: rx.Var):
    """One compiled chart per series count; the split dimension picks at runtime."""
    return rx.match(
        state.series_count,
        (1, line_chart(state.trend_rows, [("s1", state.series_label_1, theme.SERIES_1)])),
        (
            2,
            line_chart(
                state.trend_rows,
                [
                    ("s1", state.series_label_1, theme.SERIES_1),
                    ("s2", state.series_label_2, theme.SERIES_2),
                ],
            ),
        ),
        (
            3,
            line_chart(
                state.trend_rows,
                [
                    ("s1", state.series_label_1, theme.SERIES_1),
                    ("s2", state.series_label_2, theme.SERIES_2),
                    ("s3", state.series_label_3, theme.SERIES_3),
                ],
            ),
        ),
        line_chart(state.trend_rows, [("value", single_label, theme.SERIES_1)]),
    )


def _no_mart_callout() -> rx.Component:
    return rx.callout(t("no_mart"), icon="database", color_scheme="orange", width="100%")


# ------------------------------------------------------------- offenders tab


def _offenders_filter_bar() -> rx.Component:
    s = OffendersState
    return rx.vstack(
        rx.flex(
            _labeled_select(
                t("region"),
                s.region_options,
                s.region,
                s.set_region_filter,
                disabled=s.split_by == "Region",
            ),
            _labeled_select(
                t("crime_dim"),
                s.crime_options,
                s.crime,
                s.set_crime_filter,
                disabled=s.split_by == "Crime",
            ),
            _labeled_select(
                t("citizenship"),
                s.citizenship_options,
                s.citizenship,
                s.set_citizenship_filter,
                disabled=s.split_by == "Citizenship",
            ),
            _labeled_select(
                t("sex"),
                s.sex_options,
                s.sex,
                s.set_sex_filter,
                disabled=s.split_by == "Sex",
            ),
            _labeled_select(
                t("age"),
                s.age_options,
                s.age,
                s.set_age_filter,
                disabled=s.split_by == "Age",
            ),
            _labeled_select(
                t("indicator"), s.indicator_options, s.indicator, s.set_indicator_filter
            ),
            _labeled_select(t("split_by"), s.split_label_options, s.split_by_label, s.set_split_by),
            wrap="wrap",
            gap="1em",
            width="100%",
        ),
        rx.button(
            t("reset_filters"),
            on_click=s.reset_filters,
            variant="ghost",
            size="1",
            color=theme.INK_SECONDARY,
            cursor="pointer",
        ),
        align="start",
        spacing="3",
        width="100%",
    )


def _offenders_kpis() -> rx.Component:
    s = OffendersState
    return rx.flex(
        stat_tile(t("kpi_total_offenders"), s.kpi_total, t("kpi_total_offenders_note")),
        stat_tile(t("kpi_yoy"), s.kpi_yoy, t("kpi_yoy_note")),
        stat_tile(t("kpi_foreign_share"), s.kpi_share, t("kpi_foreign_share_note")),
        stat_tile(t("kpi_rate_ratio"), s.kpi_ratio, t("kpi_rate_ratio_note")),
        wrap="wrap",
        gap="1em",
        width="100%",
    )


def _offenders_tab() -> rx.Component:
    s = OffendersState
    return rx.cond(
        s.mart_ready,
        rx.vstack(
            card(t("explore"), t("explore_offenders_sub"), _offenders_filter_bar()),
            _offenders_kpis(),
            card(
                t("offenders_over_time"),
                t("annual_totals_sub"),
                _trend_chart(OffendersState, t("offenders")),
                rx.cond(
                    s.series_count == 0,
                    data_table(s.trend_rows, [("period", t("year")), ("value", t("offenders"))]),
                    rx.fragment(),
                ),
            ),
            card(
                t("rates_title"),
                t("rates_sub"),
                line_chart(
                    s.rates_rows,
                    [
                        ("s1", t("italians"), theme.SERIES_1),
                        ("s2", t("foreigners"), theme.SERIES_2),
                    ],
                ),
                data_table(
                    s.rates_rows,
                    [
                        ("period", t("year")),
                        ("s1", t("italians")),
                        ("s2", t("foreigners")),
                    ],
                ),
            ),
            card(
                t("share_title"),
                t("share_sub"),
                line_chart(
                    s.share_rows,
                    [("value", t("share_label"), theme.SERIES_2)],
                ),
                data_table(s.share_rows, [("period", t("year")), ("value", t("share_label"))]),
            ),
            card(
                t("by_crime_type"),
                t("latest_year_sub"),
                h_bar_chart(
                    s.by_crime,
                    data_key="value",
                    y_key="name",
                    color=theme.SERIES_1,
                    height=420,
                ),
                data_table(s.by_crime, [("name", t("crime_type")), ("value", t("offenders"))]),
            ),
            _income_card(),
            rx.text(t("method_note"), color=theme.INK_MUTED, font_size="0.8em"),
            spacing="5",
            width="100%",
        ),
        _no_mart_callout(),
    )


def _income_card() -> rx.Component:
    s = OffendersState
    return card(
        t("income_title"),
        t("income_sub"),
        rx.cond(
            s.income_ready,
            rx.vstack(
                rx.hstack(
                    _labeled_select(t("year"), s.income_years, s.income_year, s.set_income_year),
                    rx.spacer(),
                    rx.vstack(
                        rx.text(t("corr_italians"), color=theme.INK_SECONDARY, font_size="0.8em"),
                        rx.text(s.corr_itl, font_weight="600", color=theme.INK_PRIMARY),
                        spacing="1",
                    ),
                    rx.vstack(
                        rx.text(t("corr_foreigners"), color=theme.INK_SECONDARY, font_size="0.8em"),
                        rx.text(s.corr_frg, font_weight="600", color=theme.INK_PRIMARY),
                        spacing="1",
                    ),
                    width="100%",
                    align="end",
                    spacing="6",
                ),
                scatter_chart(
                    [
                        (s.income_itl, t("italians"), theme.SERIES_1),
                        (s.income_frg, t("foreigners"), theme.SERIES_2),
                    ],
                    x_key="income",
                    y_key="rate",
                    x_label=t("income_axis"),
                    y_label=t("rate_axis"),
                ),
                rx.text(t("income_caveat"), color=theme.INK_MUTED, font_size="0.75em"),
                spacing="4",
                width="100%",
            ),
            rx.callout(t("income_missing"), icon="info", color_scheme="blue", width="100%"),
        ),
    )


# ----------------------------------------------------------- convictions tab


def _convictions_filter_bar() -> rx.Component:
    s = CrimeState
    return rx.flex(
        _labeled_select(
            t("region"),
            s.region_options,
            s.region,
            s.set_region_filter,
            disabled=s.split_by == "Region",
        ),
        _labeled_select(
            t("offence_dim"),
            s.offence_options,
            s.offence,
            s.set_offence_filter,
            disabled=s.split_by == "Offence",
        ),
        _labeled_select(
            t("sex"),
            s.sex_options,
            s.sex,
            s.set_sex_filter,
            disabled=s.split_by == "Sex",
        ),
        _labeled_select(
            t("age"),
            s.age_options,
            s.age,
            s.set_age_filter,
            disabled=s.split_by == "Age",
        ),
        _labeled_select(t("split_by"), s.split_label_options, s.split_by_label, s.set_split_by),
        wrap="wrap",
        gap="1em",
        width="100%",
    )


def _convictions_tab() -> rx.Component:
    s = CrimeState
    return rx.cond(
        s.mart_ready,
        rx.vstack(
            card(t("explore"), t("explore_convictions_sub"), _convictions_filter_bar()),
            card(
                t("convictions_over_time"),
                t("annual_totals_sub"),
                _trend_chart(CrimeState, t("convictions")),
                rx.cond(
                    s.series_count == 0,
                    data_table(s.trend_rows, [("period", t("year")), ("value", t("convictions"))]),
                    rx.fragment(),
                ),
            ),
            card(
                t("by_offence_type"),
                t("latest_year_sub"),
                h_bar_chart(
                    s.by_offence,
                    data_key="value",
                    y_key="name",
                    color=theme.SERIES_1,
                    height=420,
                ),
                data_table(
                    s.by_offence, [("name", t("offence_type")), ("value", t("convictions"))]
                ),
            ),
            spacing="5",
            width="100%",
        ),
        _no_mart_callout(),
    )


def crime_page() -> rx.Component:
    return shell(
        rx.heading(t("crime_title"), size="6", color=theme.INK_PRIMARY),
        rx.tabs.root(
            rx.tabs.list(
                rx.tabs.trigger(t("tab_offenders"), value="offenders"),
                rx.tabs.trigger(t("tab_convictions"), value="convictions"),
            ),
            rx.tabs.content(rx.box(_offenders_tab(), padding_top="1em"), value="offenders"),
            rx.tabs.content(rx.box(_convictions_tab(), padding_top="1em"), value="convictions"),
            default_value="offenders",
            width="100%",
        ),
    )
