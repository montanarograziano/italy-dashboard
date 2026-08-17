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
            color=rx.cond(AppState.lang == code, theme.ink_primary(), theme.ink_muted()),
        )

    return rx.hstack(
        chip("en", "EN"),
        rx.text("·", color=theme.ink_muted(), font_size="0.85em"),
        chip("it", "IT"),
        spacing="2",
        align="center",
    )


def navbar() -> rx.Component:
    return rx.hstack(
        rx.heading("Italy Dashboard", size="5", color=theme.ink_primary()),
        rx.spacer(),
        *[
            rx.link(
                t(key),
                href=href,
                color=theme.ink_secondary(),
                _hover={"color": theme.ink_primary()},
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
        background=theme.surface(),
        border_bottom=theme.border_css(),
    )


def no_data_callout() -> rx.Component:
    return rx.callout(
        t("no_data"),
        icon="triangle_alert",
        color_scheme="orange",
        width="100%",
    )


def _loading_placeholder() -> rx.Component:
    """Neutral placeholder shown before a page's data has loaded.

    Never the error callout: a bare `ready`/`mart_ready` bool defaults False
    and can't tell "haven't loaded yet" from "genuinely no data" (see
    `data_gate`), so painting the error for the instant before the websocket
    connects and `load()` runs would be a false alarm on every single visit.
    """
    return rx.center(rx.spinner(size="3"), padding_y="3em", width="100%")


def data_gate(
    has_loaded: rx.Var | bool,
    ready: rx.Var | bool,
    content: rx.Component,
    empty: rx.Component,
    loading: rx.Component | None = None,
) -> rx.Component:
    """Three-state render gate: loading (neutral) / ready (content) / empty (callout).

    `has_loaded` must be set True at the END of the owning state's `load()`,
    regardless of outcome (see the per-state `has_loaded` fields in state.py,
    and AppState's docstring for why it's page-scoped rather than shared):
    until then this always renders `loading`, never `empty`, which is what
    stops the error callout from flashing on every page visit. Once loaded,
    `ready` picks between the real content and the real "no data" callout
    exactly as before this fix.
    """
    return rx.cond(
        has_loaded,
        rx.cond(ready, content, empty),
        loading if loading is not None else _loading_placeholder(),
    )


def shell(*children: rx.Component, has_loaded: rx.Var | bool) -> rx.Component:
    """Page frame: navbar + the shared "no data snapshot" banner + content.

    `has_loaded` is required (no default) so every call site names the
    CALLING PAGE's own state flag explicitly — it can't default to a shared
    AppState value (see AppState's docstring for why that would be wrong).
    """
    return rx.box(
        rx.el.style(palette.diverging_css_vars()),
        navbar(),
        rx.vstack(
            # `loading=rx.fragment()`: this slot is a thin top-of-page banner,
            # not a content area, so "nothing" (not a spinner) is the right
            # neutral placeholder while a page's own `load()` is still running.
            data_gate(
                has_loaded,
                AppState.data_ready,
                rx.fragment(),
                no_data_callout(),
                loading=rx.fragment(),
            ),
            *children,
            spacing="5",
            width="100%",
            max_width="1100px",
            margin="0 auto",
            padding="1.5em",
        ),
        background=theme.page_bg(),
        min_height="100vh",
        font_family=theme.FONT,
    )


def card(
    title: str | rx.Var, subtitle: str | rx.Var, *children: rx.Component | rx.Var
) -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.heading(title, size="4", color=theme.ink_primary()),
            rx.text(subtitle, color=theme.ink_muted(), font_size="0.85em"),
            *children,
            spacing="3",
            width="100%",
        ),
        background=theme.surface(),
        border=theme.border_css(),
        border_radius="10px",
        padding="1.25em",
        width="100%",
    )


def stat_tile(label: str | rx.Var, value: rx.Var | str, note: str | rx.Var) -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.text(label, color=theme.ink_secondary(), font_size="0.85em"),
            rx.heading(value, size="7", color=theme.ink_primary()),
            rx.text(note, color=theme.ink_muted(), font_size="0.75em"),
            spacing="1",
        ),
        background=theme.surface(),
        border=theme.border_css(),
        border_radius="10px",
        padding="1.25em",
        flex="1",
        min_width="200px",
    )


def region_select(value: rx.Var | str, on_change: Any) -> rx.Component:
    return rx.hstack(
        rx.text(t("region"), color=theme.ink_secondary(), font_size="0.9em"),
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
        stroke=theme.gridline(), vertical=False, custom_attrs={"strokeWidth": 1}
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
            "border": theme.tooltip_border_css(),
            "borderRadius": "8px",
            "fontSize": "12px",
            "color": theme.ink_primary(),
        },
        cursor={"stroke": theme.axis(), "strokeWidth": 1},
    )


def _tick_style() -> dict[str, Any]:
    """Tick LABEL styling, delivered via the axis's declared `tick` prop.

    A `fill` smuggled through `custom_attrs` never reaches the labels. Recharts'
    `CartesianAxis` builds each label's props as
    `{...axisProps, textAnchor, stroke: 'none', fill: stroke}` — the literal
    `fill: stroke` lands AFTER the spread of the axis's own props, so the axis
    `stroke` always overwrites any supplied `fill` and the labels render in the
    axis-line colour. That shipped the muted ink at the axis's contrast: 1.75:1
    in light mode and 1.60:1 in dark, both under the 3:1 floor for non-text UI,
    and effectively invisible in dark mode.

    The `tick` prop is the one that wins: recharts derives `customTickProps`
    from it and spreads it LAST (`{...tickProps, ...customTickProps}`), after
    the `fill: stroke` assignment. `tick` is a declared field on both `XAxis`
    and `YAxis` (verified: `"tick" in cartesian.XAxis.get_fields()` is True,
    typed `Var[bool | dict]`), so a dict reaches recharts as a real prop rather
    than being swept into the `wrapperStyle` fallback. Both `fill` and
    `fontSize` survive recharts' SVG-prop filter (`svgPropertiesNoEvents`).

    `fontSize` stays duplicated in `custom_attrs` on each axis because the AXIS
    also uses it to size its own tick layout, independently of the label props.
    """
    return {"fill": theme.ink_muted(), "fontSize": 12}


def _x_axis(data_key: str = "period") -> rx.Component:
    return rx.recharts.x_axis(
        data_key=data_key,
        stroke=theme.axis(),
        tick_line=False,
        tick=_tick_style(),
        custom_attrs={"fontSize": "12px"},
    )


def _y_axis() -> rx.Component:
    return rx.recharts.y_axis(
        stroke=theme.axis(),
        axis_line=False,
        tick_line=False,
        tick=_tick_style(),
        custom_attrs={"fontSize": "12px"},
    )


def line_chart(
    data: ChartData,
    series: list[tuple[str, str | rx.Var, str | rx.Var]],  # (data_key, label, color)
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
    series: list[tuple[str, str | rx.Var, str | rx.Var]],  # (data_key, label, color)
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


def band_trend_chart(
    data: ChartData,
    band_key: str,
    mean_key: str,
    rolling_key: str,
    band_label: str | rx.Var,
    mean_label: str | rx.Var,
    rolling_label: str | rx.Var,
    color: str | rx.Var,
    height: int = 300,
) -> rx.Component:
    """One quantity shown three ways, all in ONE hue: a min/max band, its thin
    annual line, and a heavier multi-year rolling-mean trend line.

    This is deliberately NOT three differently-coloured series: min, mean and
    max here are one entity (e.g. a year's temperature) viewed at three levels
    of detail, not three different entities that would each need their own
    colour to stay distinguishable. The legend tells them apart by mark
    weight and label instead — band vs thin line vs thick line — which is why
    every one of `fill`/`stroke` below is the SAME `color` argument.

    `band_key` must point at a two-element `[min, max]` array per row (see
    `queries.climate_annual_series`'s `t_band`, and NOT two separate columns):
    recharts' `Area` treats an array-valued `dataKey` as a "range area" and
    fills BETWEEN the two values. Two ordinary areas would each fill from the
    axis baseline instead and shade a region that means nothing.

    `stroke="none"` and the translucent fill are exactly the mechanism
    verified before this helper was written. `custom_attrs={"fillOpacity":
    ...}` is required, not a `fill_opacity=` kwarg: `Area` has no such
    declared field (see `area_compare_chart`'s docstring for the same
    pitfall), so an undeclared kwarg silently lands in Reflex's generic
    `wrapperStyle` fallback, a prop recharts never reads.

    `rolling_key` is expected to be `None` at the series' edges (an
    incomplete rolling window; see `queries.climate_annual_series`).
    `connect_nulls` is left at its default (`False`) for that line so it
    simply stops short at the edges instead of bridging the gap with a
    straight segment that would misstate the trend exactly where it is
    least supported by data.
    """
    band = rx.recharts.area(
        data_key=band_key,
        name=band_label,
        stroke="none",
        fill=color,
        custom_attrs={"fillOpacity": 0.22},
        legend_type="rect",
        type_="monotone",
        is_animation_active=False,
    )
    mean_line = rx.recharts.line(
        data_key=mean_key,
        name=mean_label,
        stroke=color,
        stroke_width=1.25,
        dot=False,
        legend_type="line",
        type_="monotone",
    )
    rolling_line = rx.recharts.line(
        data_key=rolling_key,
        name=rolling_label,
        stroke=color,
        stroke_width=3,
        dot=False,
        legend_type="line",
        type_="monotone",
    )
    return rx.recharts.composed_chart(
        band,
        mean_line,
        rolling_line,
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


def bar_chart(
    data: ChartData,
    data_key: str,
    x_key: str,
    color: str | rx.Var,
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


def small_multiples(items: rx.Var | list, height: int = 90) -> rx.Component:
    """A grid of stripe charts, one per city, on a shared colour scale.

    Small multiples work because every panel shares the scale: the reader
    compares panels, not axes. Panels are deliberately small and label-light;
    the card's table view carries exact values.
    """
    return rx.grid(
        rx.foreach(
            items,
            lambda item: rx.vstack(
                rx.text(item["city"], font_size="0.75em", color=theme.ink_secondary()),
                stripe_chart(item["rows"], height=height),
                spacing="1",
                width="100%",
            ),
        ),
        columns="3",
        spacing="4",
        width="100%",
    )


def h_bar_chart(
    data: ChartData,
    data_key: str,
    y_key: str,
    color: str | rx.Var,
    height: int = 380,
) -> rx.Component:
    """Horizontal bars: readable labels for long category names."""
    return rx.recharts.bar_chart(
        rx.recharts.bar(data_key=data_key, fill=color, radius=[0, 4, 4, 0]),
        rx.recharts.x_axis(
            type_="number",
            stroke=theme.axis(),
            axis_line=False,
            tick_line=False,
            tick=_tick_style(),
            custom_attrs={"fontSize": "12px"},
        ),
        rx.recharts.y_axis(
            data_key=y_key,
            type_="category",
            width=220,
            stroke=theme.axis(),
            tick_line=False,
            tick=_tick_style(),
            custom_attrs={"fontSize": "12px"},
        ),
        # `stroke_width` is not a declared `CartesianGrid` field; see `_grid()`.
        rx.recharts.cartesian_grid(
            stroke=theme.gridline(), horizontal=False, custom_attrs={"strokeWidth": 1}
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
    series: list[tuple[rx.Var | list, str | rx.Var, str | rx.Var]],  # (data, label, color)
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
    # Legend only at >= 2 series, matching `line_chart`/`area_compare_chart`.
    # A single-series scatter's legend just restates the card heading, which is
    # exactly what the climate-crime page was showing.
    legend = [rx.recharts.legend()] if len(series) >= 2 else []
    return rx.recharts.scatter_chart(
        *zero_ref_lines,
        *scatters,
        *extra_axes,
        rx.recharts.x_axis(
            data_key=x_key,
            type_="number",
            name=x_label,
            stroke=theme.axis(),
            tick_line=False,
            domain=["auto", "auto"],
            tick=_tick_style(),
            custom_attrs={"fontSize": "12px"},
        ),
        rx.recharts.y_axis(
            data_key=y_key,
            type_="number",
            name=y_label,
            stroke=theme.axis(),
            axis_line=False,
            tick_line=False,
            domain=["auto", "auto"],
            tick=_tick_style(),
            custom_attrs={"fontSize": "12px"},
        ),
        # `stroke_width` is not a declared `CartesianGrid` field; see `_grid()`.
        rx.recharts.cartesian_grid(stroke=theme.gridline(), custom_attrs={"strokeWidth": 1}),
        _tooltip(),
        *legend,
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
