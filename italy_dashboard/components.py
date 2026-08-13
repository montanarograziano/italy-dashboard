"""Shared UI building blocks: page shell, cards, stat tiles, chart wrappers."""

from __future__ import annotations

from typing import Any

import reflex as rx

from italy_dashboard import theme
from italy_dashboard.i18n import t
from italy_dashboard.state import AppState

# Components accept either a live Reflex Var (state attribute) or a plain value.
ChartData = rx.Var | list[dict[str, Any]]

NAV_LINKS = [
    ("nav_home", "/"),
    ("nav_crime", "/crime"),
    ("nav_population", "/population"),
    ("nav_climate", "/climate"),
    ("nav_climate_crime", "/climate-crime"),
    ("nav_labor", "/labor"),
    ("nav_economy", "/economy"),
]


def _lang_toggle() -> rx.Component:
    def chip(code: str, label: str) -> rx.Component:
        return rx.text(
            label,
            on_click=AppState.set_language(code),
            cursor="pointer",
            font_size="0.85em",
            font_weight=rx.cond(AppState.lang == code, "700", "400"),
            color=rx.cond(AppState.lang == code, theme.INK_PRIMARY, theme.INK_MUTED),
        )

    return rx.hstack(
        chip("en", "EN"),
        rx.text("·", color=theme.INK_MUTED, font_size="0.85em"),
        chip("it", "IT"),
        spacing="2",
        align="center",
    )


def navbar() -> rx.Component:
    return rx.hstack(
        rx.heading("Italy Dashboard", size="5", color=theme.INK_PRIMARY),
        rx.spacer(),
        *[
            rx.link(
                t(key),
                href=href,
                color=theme.INK_SECONDARY,
                _hover={"color": theme.INK_PRIMARY},
                font_size="0.95em",
            )
            for key, href in NAV_LINKS
        ],
        _lang_toggle(),
        spacing="5",
        align="center",
        width="100%",
        padding="1em 1.5em",
        background=theme.SURFACE,
        border_bottom=f"1px solid {theme.BORDER}",
    )


def no_data_callout() -> rx.Component:
    return rx.callout(
        t("no_data"),
        icon="triangle_alert",
        color_scheme="orange",
        width="100%",
    )


def shell(*children: rx.Component) -> rx.Component:
    return rx.box(
        navbar(),
        rx.vstack(
            rx.cond(AppState.data_ready, rx.fragment(), no_data_callout()),
            *children,
            spacing="5",
            width="100%",
            max_width="1100px",
            margin="0 auto",
            padding="1.5em",
        ),
        background=theme.PAGE_BG,
        min_height="100vh",
        font_family=theme.FONT,
    )


def card(
    title: str | rx.Var, subtitle: str | rx.Var, *children: rx.Component | rx.Var
) -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.heading(title, size="4", color=theme.INK_PRIMARY),
            rx.text(subtitle, color=theme.INK_MUTED, font_size="0.85em"),
            *children,
            spacing="3",
            width="100%",
        ),
        background=theme.SURFACE,
        border=f"1px solid {theme.BORDER}",
        border_radius="10px",
        padding="1.25em",
        width="100%",
    )


def stat_tile(label: str | rx.Var, value: rx.Var | str, note: str | rx.Var) -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.text(label, color=theme.INK_SECONDARY, font_size="0.85em"),
            rx.heading(value, size="7", color=theme.INK_PRIMARY),
            rx.text(note, color=theme.INK_MUTED, font_size="0.75em"),
            spacing="1",
        ),
        background=theme.SURFACE,
        border=f"1px solid {theme.BORDER}",
        border_radius="10px",
        padding="1.25em",
        flex="1",
        min_width="200px",
    )


def region_select(value: rx.Var | str, on_change: Any) -> rx.Component:
    return rx.hstack(
        rx.text(t("region"), color=theme.INK_SECONDARY, font_size="0.9em"),
        rx.select(
            AppState.regions,
            value=value,
            on_change=on_change,
            width="260px",
        ),
        align="center",
        spacing="3",
    )


# ------------------------------------------------------------- charts


def _grid() -> rx.Component:
    return rx.recharts.cartesian_grid(stroke=theme.GRIDLINE, vertical=False, stroke_width=1)


def _x_axis(data_key: str = "period") -> rx.Component:
    return rx.recharts.x_axis(
        data_key=data_key,
        stroke=theme.AXIS,
        tick_line=False,
        custom_attrs={"fontSize": "12px", "fill": theme.INK_MUTED},
    )


def _y_axis() -> rx.Component:
    return rx.recharts.y_axis(
        stroke=theme.AXIS,
        axis_line=False,
        tick_line=False,
        custom_attrs={"fontSize": "12px", "fill": theme.INK_MUTED},
    )


def line_chart(
    data: ChartData,
    series: list[tuple[str, str | rx.Var, str]],  # (data_key, label, color)
    height: int = 300,
) -> rx.Component:
    """Line chart; legend shown only when there are >= 2 series."""
    lines = [
        rx.recharts.line(
            data_key=key,
            name=label,
            stroke=color,
            stroke_width=2,
            dot=False,
            type_="monotone",
        )
        for key, label, color in series
    ]
    children = [*lines, _x_axis(), _y_axis(), _grid(), rx.recharts.graphing_tooltip()]
    if len(series) >= 2:
        children.append(rx.recharts.legend())
    return rx.recharts.line_chart(
        *children,
        data=data,
        width="100%",
        height=height,
        margin={"top": 8, "right": 8, "bottom": 4, "left": 8},
    )


def bar_chart(
    data: ChartData,
    data_key: str,
    x_key: str,
    color: str,
    height: int = 300,
) -> rx.Component:
    return rx.recharts.bar_chart(
        rx.recharts.bar(
            data_key=data_key,
            fill=color,
            radius=[4, 4, 0, 0],  # rounded data-end, anchored to baseline
        ),
        _x_axis(x_key),
        _y_axis(),
        _grid(),
        rx.recharts.graphing_tooltip(),
        data=data,
        bar_category_gap="25%",
        width="100%",
        height=height,
        margin={"top": 8, "right": 8, "bottom": 4, "left": 8},
    )


def h_bar_chart(
    data: ChartData,
    data_key: str,
    y_key: str,
    color: str,
    height: int = 380,
) -> rx.Component:
    """Horizontal bars: readable labels for long category names."""
    return rx.recharts.bar_chart(
        rx.recharts.bar(data_key=data_key, fill=color, radius=[0, 4, 4, 0]),
        rx.recharts.x_axis(
            type_="number",
            stroke=theme.AXIS,
            axis_line=False,
            tick_line=False,
            custom_attrs={"fontSize": "12px", "fill": theme.INK_MUTED},
        ),
        rx.recharts.y_axis(
            data_key=y_key,
            type_="category",
            width=220,
            stroke=theme.AXIS,
            tick_line=False,
            custom_attrs={"fontSize": "12px", "fill": theme.INK_MUTED},
        ),
        rx.recharts.cartesian_grid(stroke=theme.GRIDLINE, horizontal=False, stroke_width=1),
        rx.recharts.graphing_tooltip(),
        data=data,
        layout="vertical",
        bar_category_gap="25%",
        width="100%",
        height=height,
        margin={"top": 8, "right": 16, "bottom": 4, "left": 8},
    )


def scatter_chart(
    series: list[tuple[rx.Var | list, str | rx.Var, str]],  # (data, label, color)
    x_key: str,
    y_key: str,
    x_label: str | rx.Var = "",
    y_label: str | rx.Var = "",
    height: int = 380,
    label_key: str | None = None,
    label_name: str | rx.Var = "",
) -> rx.Component:
    """Scatter with one series per group; tooltip shows the point's fields.

    `label_key` names a categorical field of each point (e.g. the region) to
    surface in the tooltip — recharts' ZAxis-with-fixed-range idiom, which
    adds the field to the tooltip without affecting dot size.
    """
    scatters = [
        rx.recharts.scatter(data=data, name=label, fill=color) for data, label, color in series
    ]
    extra_axes = (
        [
            rx.recharts.z_axis(
                data_key=label_key,
                range=[60, 60],
                name=label_name,
                # reflex's ZAxis wrapper has no `type` prop; anything else
                # (like type_=) silently lands in wrapperStyle and the axis
                # stays numeric, dropping the string field from the tooltip
                custom_attrs={"type": "category"},
            )
        ]
        if label_key
        else []
    )
    return rx.recharts.scatter_chart(
        *scatters,
        *extra_axes,
        rx.recharts.x_axis(
            data_key=x_key,
            type_="number",
            name=x_label,
            stroke=theme.AXIS,
            tick_line=False,
            domain=["auto", "auto"],
            custom_attrs={"fontSize": "12px", "fill": theme.INK_MUTED},
        ),
        rx.recharts.y_axis(
            data_key=y_key,
            type_="number",
            name=y_label,
            stroke=theme.AXIS,
            axis_line=False,
            tick_line=False,
            domain=["auto", "auto"],
            custom_attrs={"fontSize": "12px", "fill": theme.INK_MUTED},
        ),
        rx.recharts.cartesian_grid(stroke=theme.GRIDLINE, stroke_width=1),
        rx.recharts.graphing_tooltip(),
        rx.recharts.legend(),
        width="100%",
        height=height,
        margin={"top": 8, "right": 16, "bottom": 8, "left": 8},
    )


def data_table(data: ChartData, columns: list[tuple[str, str | rx.Var]]) -> rx.Component:
    """Accessible table view of the chart data (collapsed by default)."""
    return rx.accordion.root(
        rx.accordion.item(
            header=rx.text(t("view_table"), font_size="0.85em"),
            content=rx.table.root(
                rx.table.header(
                    rx.table.row(*[rx.table.column_header_cell(label) for _, label in columns])
                ),
                rx.table.body(
                    rx.foreach(
                        data,
                        lambda row: rx.table.row(*[rx.table.cell(row[key]) for key, _ in columns]),
                    )
                ),
                size="1",
                width="100%",
            ),
            value="table",
        ),
        collapsible=True,
        type="multiple",
        width="100%",
        variant="ghost",
    )
