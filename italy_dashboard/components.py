"""Shared UI building blocks: page shell, cards, stat tiles, chart wrappers."""

from __future__ import annotations

from typing import Any

import reflex as rx

from italy_dashboard import palette, theme
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
        rx.color_mode.button(size="1"),
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
        rx.el.style(palette.diverging_css_vars()),
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
    # `CartesianGrid` has no `stroke_width` field (verified empirically via
    # `"stroke_width" in cartesian.CartesianGrid.get_fields()` -> False), so a
    # `stroke_width=` kwarg is silently swept into Reflex's generic
    # `wrapperStyle` fallback, a prop the real recharts `<CartesianGrid>` never
    # reads. It happened to be harmless because SVG's own default stroke width
    # is also 1, but it is inert: `custom_attrs={"strokeWidth": ...}` is the
    # form that actually reaches the component.
    return rx.recharts.cartesian_grid(
        stroke=theme.GRIDLINE, vertical=False, custom_attrs={"strokeWidth": 1}
    )


def _tooltip() -> rx.Component:
    """Tooltip wearing the surface and ink tokens.

    The default is a white box with a light border, which disappears against a
    dark surface. Styling it here means every chart inherits a correct one.

    `content_style` and `cursor` ARE declared fields on `GraphingTooltip`
    (verified empirically: `"content_style" in GraphingTooltip.get_fields()` is
    True, likewise `cursor`), so they reach recharts as real props directly —
    no `custom_attrs` fallback needed here, unlike `fill_opacity` on `Area` or
    `stroke_width` on `CartesianGrid` above.

    Uses the mode-aware accessors (`theme.surface()`, `theme.gridline()`,
    `theme.ink_primary()`, `theme.axis()`), not the bare light-mode constants:
    those accessors compile to `rx.color_mode_cond`, so the tooltip actually
    reacts to dark mode instead of staying pinned to light-mode colours.
    """
    return rx.recharts.graphing_tooltip(
        content_style={
            "background": theme.surface(),
            "border": f"1px solid {theme.gridline()}",
            "borderRadius": "8px",
            "fontSize": "12px",
            "color": theme.ink_primary(),
        },
        cursor={"stroke": theme.axis(), "strokeWidth": 1},
    )


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
    brush: bool = False,
) -> rx.Component:
    """Line chart; legend shown only when there are >= 2 series.

    `brush` is opt-in and off by default: it is a scrubber for long series and
    would be visual noise on the short ones most callers pass.
    """
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
    children = [*lines, _x_axis(), _y_axis(), _grid(), _tooltip()]
    if len(series) >= 2:
        children.append(rx.recharts.legend())
    if brush:
        children.append(
            rx.recharts.brush(
                data_key="period",
                height=24,
                stroke=theme.axis(),
                fill=theme.surface(),
            )
        )
    return rx.recharts.line_chart(
        *children,
        data=data,
        width="100%",
        height=height,
        margin={"top": 8, "right": 8, "bottom": 4, "left": 8},
    )


def area_compare_chart(
    data: ChartData,
    series: list[tuple[str, str | rx.Var, str]],  # (data_key, label, color)
    height: int = 300,
) -> rx.Component:
    """Two or more overlapping distributions as translucent areas.

    Areas beat lines for comparing distributions: the eye reads the shift in
    mass, not two thin squiggles. Fills stay translucent so the overlap region
    is visible rather than one series hiding another, and each area keeps a 2px
    stroke so its edge is legible where the fills coincide.

    Opacity is set via `custom_attrs={"fillOpacity": ...}`, not a `fill_opacity=`
    kwarg: `Area` (reflex_components_recharts.cartesian.Area) has no such field,
    so an unrecognized `fill_opacity` kwarg is silently swept into Reflex's
    generic style fallback (`Recharts._get_style` renders it as
    `wrapperStyle={"fillOpacity": ...}`), a prop the real recharts `<Area>`
    does not read. That version renders, and even reads back a "0.28" in the
    output, while shipping fully opaque areas in the browser.
    """
    areas = [
        rx.recharts.area(
            data_key=key,
            name=label,
            stroke=color,
            stroke_width=2,
            fill=color,
            custom_attrs={"fillOpacity": 0.28},
            type_="monotone",
            is_animation_active=False,
        )
        for key, label, color in series
    ]
    children = [*areas, _x_axis(), _y_axis(), _grid(), _tooltip()]
    if len(series) >= 2:
        children.append(rx.recharts.legend())
    return rx.recharts.area_chart(
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
        _tooltip(),
        data=data,
        bar_category_gap="25%",
        width="100%",
        height=height,
        margin={"top": 8, "right": 8, "bottom": 4, "left": 8},
    )


def composed_bar_line_chart(
    data: ChartData,
    bar_key: str,
    bar_label: str | rx.Var,
    line_key: str,
    line_label: str | rx.Var,
    height: int = 300,
) -> rx.Component:
    """Counts as bars with a trend line over them, sharing ONE y-axis.

    Both measures must be on the same scale for this to be honest. A second
    y-scale is never the answer: it lets the author choose the story by choosing
    the scaling, which is why this helper does not offer one.
    """
    return rx.recharts.composed_chart(
        rx.recharts.bar(
            data_key=bar_key, name=bar_label, fill=theme.series(1), radius=[4, 4, 0, 0]
        ),
        rx.recharts.line(
            data_key=line_key,
            name=line_label,
            stroke=theme.series(2),
            stroke_width=2,
            dot=False,
            type_="monotone",
        ),
        _x_axis(),
        _y_axis(),
        _grid(),
        _tooltip(),
        rx.recharts.legend(),
        data=data,
        width="100%",
        height=height,
        margin={"top": 8, "right": 8, "bottom": 4, "left": 8},
    )


def stripe_chart(data: ChartData, height: int = 140) -> rx.Component:
    """Warming stripes: one bar per year, coloured by its own anomaly.

    Squat by design and axis-free apart from the year: the form's whole job is
    to be read as a colour field, and gridlines fight that. The table view in
    the surrounding card carries the exact numbers.

    `rx.recharts.cell` is passed as a POSITIONAL child of `rx.recharts.bar`,
    not via a `children=` keyword: `Bar.create(*children, **props)` forwards
    `**props` straight into `Component._create(children, **props)`, so a
    `children` keyword collides with the positional `children` argument and
    raises `TypeError: got multiple values for argument 'children'`.
    """
    return rx.recharts.bar_chart(
        rx.recharts.bar(
            rx.foreach(data, lambda row: rx.recharts.cell(fill=row["fill"])),
            data_key="anomaly",
            fill=theme.series(1),
            is_animation_active=False,
        ),
        _x_axis(),
        _tooltip(),
        data=data,
        bar_category_gap=0,
        width="100%",
        height=height,
        margin={"top": 4, "right": 8, "bottom": 4, "left": 8},
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
        # `stroke_width` is not a declared `CartesianGrid` field; see `_grid()`.
        rx.recharts.cartesian_grid(
            stroke=theme.GRIDLINE, horizontal=False, custom_attrs={"strokeWidth": 1}
        ),
        _tooltip(),
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
    zero_lines: bool = False,
) -> rx.Component:
    """Scatter with one series per group; tooltip shows the point's fields.

    `label_key` names a categorical field of each point (e.g. the region) to
    surface in the tooltip — recharts' ZAxis-with-fixed-range idiom, which
    adds the field to the tooltip without affecting dot size.

    `zero_lines` draws reference lines at x=0 and y=0. Only meaningful for a
    scatter whose axes are centred on zero by construction (e.g. two-way
    demeaned panel data), where the cross-hairs let the reader see which
    quadrant a point falls in without tracing the axes. A scatter of absolute
    values has no such natural origin, so it should leave this off. These are
    chrome, not data: `theme.axis()`, never a series colour, and added before
    the scatters so they render beneath the points.
    """
    scatters = [
        rx.recharts.scatter(data=data, name=label, fill=color) for data, label, color in series
    ]
    zero_ref_lines = (
        [
            rx.recharts.reference_line(x=0, stroke=theme.axis(), stroke_width=1),
            rx.recharts.reference_line(y=0, stroke=theme.axis(), stroke_width=1),
        ]
        if zero_lines
        else []
    )
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
        *zero_ref_lines,
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
        # `stroke_width` is not a declared `CartesianGrid` field; see `_grid()`.
        rx.recharts.cartesian_grid(stroke=theme.GRIDLINE, custom_attrs={"strokeWidth": 1}),
        _tooltip(),
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
