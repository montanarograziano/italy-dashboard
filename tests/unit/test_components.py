"""Render tests for chart helpers: a chart that will not build is a broken page.

`stripe_chart` needs a test of its own, distinct from the query-layer test in
test_queries.py. The query test proves `climate_stripes` rows carry distinct
`var(--div-N)` fills; it says nothing about whether the CHART actually wires
each row's fill onto its own bar. A `Bar` painted with one constant colour
renders exactly as successfully as one with per-cell fills — the render step
alone cannot tell a diverging encoding from the single-hue bug it replaced.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
import reflex as rx

from italy_dashboard import components as c
from italy_dashboard import palette, theme
from italy_dashboard.state import ClimateState


def test_stripe_chart_binds_fill_per_cell_not_once_for_the_whole_bar():
    """The stripes' colour IS their value.

    Uses `ClimateState.stripes`, the same Var `pages/climate.py` actually
    passes in, rather than a hand-rolled literal: a plain list of dicts with
    mixed-type values (str period, float anomaly, str fill) makes Reflex infer
    a `str | float` union for `row["fill"]` and reject it as a `Cell.fill` prop
    before rendering even starts — a red herring unrelated to the encoding bug
    this test guards against.

    Asserts the rendered tree contains a `RechartsCell` whose `fill` prop is
    bound to the row's own `fill` field (`row[...]["fill"]`), not a literal
    colour shared by every bar. A revert to a flat `bar_chart(...)` call, or a
    `Cell` with a hardcoded fill, must make this fail.
    """
    rendered = str(c.stripe_chart(ClimateState.stripes).render())
    assert "RechartsCell" in rendered
    assert 'fill:row_rx_state_?.["fill"]' in rendered


# ------------------------------------------------ scatter_chart zero_lines
#
# The climate-crime PANEL scatter plots two-way demeaned values that centre on
# zero on BOTH axes by construction, so a zero cross-hair on each axis is a
# genuine reading aid: it shows which quadrant a region-year falls in without
# tracing the gridlines. The RAW scatter beside it plots absolute temperatures,
# which have no such natural origin, so it must never get one. `zero_lines` is
# the switch; these tests pin both the on and the off state, plus the two
# properties that make the feature correct rather than just present: the lines
# are chrome (`theme.axis()`), not a series colour, and they are added before
# the scatter data so they render underneath it.

SCATTER_POINTS = [
    {"x": -0.4, "y": 0.6, "region": "Lazio"},
    {"x": 0.2, "y": -0.3, "region": "Sicilia"},
]


def _scatter(zero_lines: bool) -> str:
    return str(
        c.scatter_chart(
            [(SCATTER_POINTS, "Panel", theme.series(1))],
            x_key="x",
            y_key="y",
            zero_lines=zero_lines,
        ).render()
    )


def test_scatter_chart_zero_lines_true_draws_reference_lines_at_the_origin():
    rendered = _scatter(zero_lines=True)
    assert rendered.count("RechartsReferenceLine") == 2
    assert "x:0" in rendered
    assert "y:0" in rendered


def test_scatter_chart_zero_lines_false_omits_reference_lines():
    """Default is off: a raw-value scatter must not get a meaningless origin."""
    rendered = _scatter(zero_lines=False)
    assert "RechartsReferenceLine" not in rendered


def test_scatter_chart_zero_lines_use_chrome_colour_not_a_series_colour():
    """The reference lines must resolve through the SAME colour-mode
    conditional `theme.axis()` produces everywhere else, not a bare hex — and
    never the series' own colour. `"resolvedColorMode"` only appears in the
    render if `theme.axis()` (an `rx.color_mode_cond` Var) built the `stroke`,
    never if a plain string (a bare constant, or a hardcoded hex) did.
    """
    rendered = _scatter(zero_lines=True)
    start = rendered.index("RechartsReferenceLine")
    props = rendered[start : start + 200]
    assert "resolvedColorMode" in props  # chrome resolves via colour-mode cond
    assert palette.CATEGORICAL_LIGHT[0] not in props  # never the series' own colour


def test_scatter_chart_zero_lines_render_beneath_the_scatter_data():
    """Reference elements render BENEATH the data: added-after-the-scatter is
    a regression that still `.render()`s fine, so ordering needs its own
    assertion rather than relying on the build-succeeds tests above."""
    rendered = _scatter(zero_lines=True)
    assert rendered.index("RechartsReferenceLine") < rendered.index("'RechartsScatter'")


def test_climate_crime_panel_scatter_has_zero_lines_but_raw_scatter_does_not():
    """Pins the real page wiring, not just the `scatter_chart` API: the panel
    scatter (two-way demeaned, centred on zero by construction) must carry the
    cross-hairs; the raw scatter (absolute temperatures, no natural origin)
    must not. Losing `zero_lines=True` on the panel call silently drops this
    to zero, which is exactly the failure mode this guards against."""
    from italy_dashboard.pages.climate_crime import climate_crime_page

    rendered = str(climate_crime_page().render())
    assert rendered.count("RechartsReferenceLine") == 2


# ------------------------------------------------ area_compare_chart / composed_bar_line_chart
#
# A generic row fixture shared by both new chart helpers: "period" for the
# default x-axis, "value" as a plain count (the composed chart's bar), and
# "early"/"late" as two comparable series (the area chart's pair, and doubling
# as the composed chart's line since both must share ONE y-axis).

ROWS = [
    {"period": "1951", "value": 3, "early": 12.1, "late": 13.4},
    {"period": "1990", "value": 5, "early": 12.6, "late": 13.9},
    {"period": "2025", "value": 8, "early": 13.0, "late": 14.2},
]


def test_area_compare_chart_builds_and_has_a_legend():
    comp = c.area_compare_chart(
        ROWS,
        [("early", "1951-1980", theme.series(1)), ("late", "1996-2025", theme.series(2))],
    )
    rendered = str(comp.render())
    assert rendered
    assert "Legend" in rendered


def test_area_compare_chart_fills_stay_translucent_not_opaque():
    """The legend test above only guards "a second series is present"; it says
    nothing about the property the helper actually exists for. An opaque fill
    on either area would hide the overlap region entirely while still
    rendering fine and still showing a legend, so this pins `fillOpacity`
    directly for BOTH areas.

    Asserts the literal `fillOpacity:0.28` prop form, not `fill_opacity=`: the
    `Area` component has no `fill_opacity` field, so that kwarg is silently
    swept into Reflex's generic style fallback and rendered as
    `wrapperStyle={"fillOpacity": ...}` instead, a prop the real recharts
    `<Area>` does not read. `custom_attrs={"fillOpacity": ...}` is the form
    that actually reaches the component as a real prop.
    """
    comp = c.area_compare_chart(
        ROWS,
        [("early", "1951-1980", theme.series(1)), ("late", "1996-2025", theme.series(2))],
    )
    rendered = str(comp.render())
    assert rendered.count("fillOpacity:0.28") == 2


def test_composed_bar_line_chart_builds_with_one_axis():
    comp = c.composed_bar_line_chart(
        ROWS, bar_key="value", bar_label="Hot days", line_key="early", line_label="Trend"
    )
    rendered = str(comp.render())
    assert rendered
    assert "Legend" in rendered
    # One y-axis only: a dual-axis chart is the single most common chart mistake.
    assert rendered.count("YAxis") == 1


# ------------------------------------------------ tooltip styling / brush


def _content_style_segment(rendered: str) -> str:
    """Isolate just the `contentStyle:(...)` prop from a rendered tree.

    `str(component.render())` is a Python repr of a dict whose `props` list has
    one string per prop, e.g. `['contentStyle:(...)', 'cursor:(...)', ...]`.
    Slicing out only the `contentStyle` element (up to the closing `', '` that
    starts the next list item) means a check against it cannot be satisfied by
    styling that leaked into a DIFFERENT prop, such as `wrapperStyle`.
    """
    start = rendered.index("contentStyle:")
    end = rendered.index("', '", start)
    return rendered[start:end]


def test_tooltip_is_styled_with_surface_tokens():
    """A default tooltip ignores the theme and breaks in dark mode.

    Checks the `contentStyle` prop SEGMENT specifically (see
    `_content_style_segment`), not just whether "contentStyle" or
    "resolvedColorMode" appears anywhere in the render. That distinction is
    the whole point: Reflex accepts an unrecognised kwarg silently and sweeps
    it into `wrapperStyle`, a prop recharts never reads (the exact bug
    `area_compare_chart`'s docstring documents for `fill_opacity`). A tooltip
    "styled" via a typo'd kwarg would still show `resolvedColorMode` and
    `wrapperStyle` in the full render, but NOT inside `contentStyle`, and this
    test's segment-scoped assertions would catch that where a bare substring
    search on the whole render would not.
    """
    rendered = str(c.line_chart(ROWS, [("value", "V", theme.series(1))]).render())
    segment = _content_style_segment(rendered)
    # Mode-aware: theme.surface()/theme.gridline()/theme.ink_primary() compile
    # to rx.color_mode_cond, which emits a `resolvedColorMode` check. A bare
    # hardcoded hex (what a reverted call site would emit) would never produce
    # this string at all.
    assert "resolvedColorMode" in segment
    # The border is itself a colour-mode-conditional VALUE (via
    # `theme.tooltip_border_css()`), not a plain string built by interpolating
    # a Var into an f-string (`f"1px solid {theme.gridline()}"` bakes the
    # Var's repr into the string instead, see theme.py's module docstring).
    assert '"border"] : ((resolvedColorMode' in segment
    # A value only our helper sets; absent from the recharts/Reflex default.
    assert "fontSize" in segment
    # If styling had landed in the generic style fallback instead of the real
    # `contentStyle` prop, `wrapperStyle` would appear in the render at all.
    assert "wrapperStyle" not in rendered


# ------------------------------------------------ dark-mode chrome (chart chrome
# must FLIP with the mode, not just build without error)
#
# Rendering a page proves the tree builds; it says nothing about whether a
# colour actually varies with the mode. `rx.color_mode_cond` compiles to a
# `resolvedColorMode ? light : dark` ternary in the JS output, so its presence
# in a chrome prop is the signature that distinguishes "this colour reacts to
# the toggle" from "this colour is nailed to one hex forever". A gridline,
# axis line or tick label built from a bare `theme.GRIDLINE`/`theme.AXIS`
# constant (or an equivalent hardcoded hex) would render fine and NEVER emit
# this string, which is exactly the bug this migration closes.
#
# Parameterised over every helper that renders its own grid/axis chrome,
# checked INDEPENDENTLY rather than through one representative (`line_chart`)
# by proxy: `line_chart`, `bar_chart`, `composed_bar_line_chart` and
# `area_compare_chart` build their chrome via the shared `_grid()`/`_x_axis()`/
# `_y_axis()` helpers, but `h_bar_chart` and `scatter_chart` construct their
# `x_axis`/`y_axis`/`cartesian_grid` INLINE — the same pattern that hid two of
# the three inert `stroke_width` sites in the prior task. A single test built
# only around `line_chart` would pass by coincidence of a shared code path and
# say nothing about the inline builders, which is exactly where a future edit
# lands without ever touching `_grid()`.

CHART_CHROME_HELPERS: dict[str, Callable[[], rx.Component]] = {
    "line_chart": lambda: c.line_chart(ROWS, [("value", "V", theme.series(1))]),
    "bar_chart": lambda: c.bar_chart(ROWS, data_key="value", x_key="period", color=theme.series(1)),
    "h_bar_chart": lambda: c.h_bar_chart(
        ROWS, data_key="value", y_key="period", color=theme.series(1)
    ),
    "scatter_chart": lambda: c.scatter_chart(
        [(SCATTER_POINTS, "Panel", theme.series(1))], x_key="x", y_key="y"
    ),
    "composed_bar_line_chart": lambda: c.composed_bar_line_chart(
        ROWS, bar_key="value", bar_label="Bars", line_key="early", line_label="Trend"
    ),
    "area_compare_chart": lambda: c.area_compare_chart(
        ROWS,
        [("early", "1951-1980", theme.series(1)), ("late", "1996-2025", theme.series(2))],
    ),
}


def _chrome_segments(rendered: str, tag: str, window: int = 300) -> list[str]:
    """Every occurrence of `tag` in `rendered`, each with its trailing props."""
    segments = []
    start = 0
    while (idx := rendered.find(tag, start)) != -1:
        segments.append(rendered[idx : idx + window])
        start = idx + len(tag)
    return segments


@pytest.mark.parametrize("name", sorted(CHART_CHROME_HELPERS))
def test_chart_chrome_resolves_through_color_mode_cond_not_a_hardcoded_hex(name: str):
    rendered = str(CHART_CHROME_HELPERS[name]().render())

    for tag in ("RechartsCartesianGrid", "RechartsXAxis", "RechartsYAxis"):
        segments = _chrome_segments(rendered, tag)
        assert segments, f"{name}: no {tag} in render"
        for segment in segments:
            assert "resolvedColorMode" in segment, f"{name}: {tag} chrome is not mode-aware"

    # Never the light-mode hex alone, with no conditional around it: that
    # shape is what a revert to `theme.GRIDLINE`/`theme.AXIS` (or a hardcoded
    # equivalent) would produce.
    assert 'stroke:"#e1e0d9"' not in rendered, f"{name}: hardcoded gridline hex"
    assert 'stroke:"#c3c2b7"' not in rendered, f"{name}: hardcoded axis hex"


def test_line_chart_with_brush_builds():
    assert c.line_chart(ROWS, [("value", "V", theme.series(1))], brush=True).render()


def test_line_chart_brush_is_off_by_default():
    rendered = str(c.line_chart(ROWS, [("value", "V", theme.series(1))]).render())
    assert "RechartsBrush" not in rendered


def test_line_chart_brush_true_adds_a_brush():
    rendered = str(c.line_chart(ROWS, [("value", "V", theme.series(1))], brush=True).render())
    assert "RechartsBrush" in rendered
