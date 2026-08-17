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
from italy_dashboard.state import ClimateState, GridItem


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


# ------------------------------------------------------- small_multiples
#
# `small_multiples` is a grid built by iterating a *list of cities*, each
# carrying its own stripe rows. A guard that only re-tests `stripe_chart`
# would pass just as happily if the grid quietly rendered one panel, or the
# same city N times, as it does for a real per-city grid: the failure mode
# lives in the OUTER iteration, not in the stripe rendering `stripe_chart`
# already covers above. So this uses a concrete two-city literal, explicitly
# typed as `list[GridItem]` (matching what `ClimateState.stripes_grid` really
# is), precisely so the two cities' names and fills land as literal text in
# the rendered tree and can be told apart. Without the explicit `.to(...)`,
# Reflex's structural inference over a raw nested literal collapses `rows`
# to a union type before it ever reaches `stripe_chart`'s own foreach — the
# same class of problem `GridItem` fixes for the real state Var, just hit a
# different way for a literal.

GRID_ITEMS = rx.Var.create(
    [
        {"city": "Roma", "rows": [{"period": "2020", "anomaly": 0.5, "fill": "var(--div-5)"}]},
        {"city": "Milano", "rows": [{"period": "2020", "anomaly": -0.2, "fill": "var(--div-3)"}]},
    ]
).to(list[GridItem])


def test_small_multiples_renders_a_distinct_panel_per_city():
    """Both cities' names and both cities' distinct fills must appear as
    data, AND the tree must show a real per-item iteration rather than a
    single indexed element.

    The data-level checks alone are not a reliable guard here: Reflex's Var
    repr embeds the full underlying array literal as debug metadata on every
    derived Var, INCLUDING on a single `.at(0)` index — so "Milano" and
    `var(--div-3)` show up in `str(component.render())` even when the actual
    generated code only ever reads index 0 (verified by hand: reverting
    `small_multiples` to `first = items[0]; ...` still leaves both city names
    in the rendered string). The real tell is the JS *shape*: a working
    `rx.foreach` compiles to an anonymous per-item arg (`item_rx_state_...`)
    bound over the whole array, with no `.at?.(` index anywhere; `items[0]`
    compiles to an explicit `.at?.(0)` and drops that arg entirely. Both
    `.at?.(` presence and `item_rx_state_` absence flip on that same revert.
    """
    rendered = str(c.small_multiples(GRID_ITEMS).render())
    assert "Roma" in rendered
    assert "Milano" in rendered
    assert "var(--div-5)" in rendered
    assert "var(--div-3)" in rendered
    assert "item_rx_state_" in rendered, "expected a real rx.foreach arg, not indexed access"
    assert ".at?.(" not in rendered, "items[0] compiles to an explicit index, not a foreach"


def test_small_multiples_builds_against_the_real_state_var():
    """`ClimateState.stripes_grid` is `list[GridItem]`, a `TypedDict` with
    `rows: list[Row]`, precisely so Reflex infers `item["rows"]` as a real
    list type inside the foreach arg. The flat `Row = dict[str, Any]` alias
    would collapse it to `Any` and `stripe_chart`'s own internal `rx.foreach`
    would raise `ForeachVarError: ... of type Any` at render time. This test
    catches a regression to that flat typing even though a hand-rolled
    literal (see the test above) would not: literals don't go through
    Reflex's state-var type inference at all.
    """
    assert c.small_multiples(ClimateState.stripes_grid).render()


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


def test_scatter_chart_single_series_has_no_legend():
    """One series means the legend restates the card heading and nothing else.

    `line_chart` and `area_compare_chart` already gate on `len(series) >= 2`;
    `scatter_chart` emitted one unconditionally, which is what put a redundant
    legend under both climate-crime scatters.
    """
    assert "Legend" not in _scatter(zero_lines=False)


def test_scatter_chart_two_series_keeps_its_legend():
    """The gate must not cost the multi-series case its legend: with two
    series the colours are the ONLY thing telling the groups apart."""
    rendered = str(
        c.scatter_chart(
            [
                (SCATTER_POINTS, "Italians", theme.series(1)),
                (SCATTER_POINTS, "Foreigners", theme.series(2)),
            ],
            x_key="x",
            y_key="y",
        ).render()
    )
    assert "Legend" in rendered


def _nodes(tree, name: str) -> list[dict]:
    """Every rendered node called `name`, found anywhere in the tree.

    A page's charts sit inside `rx.cond`/`rx.match` branches, which the render
    dict carries under keys other than `children`, so this walks every nested
    dict and list rather than only the `children` lists. Walking the tree, not
    substring-searching `str(...)`, is what makes "does THIS chart have a
    legend" answerable on a page that holds several charts.
    """
    found = []
    stack = [tree]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if node.get("name") == name:
                found.append(node)
            stack.extend(node.values())
        elif isinstance(node, (list, tuple)):
            stack.extend(node)
    return found


def test_climate_page_warming_card_uses_the_band_trend_chart():
    """Pins the REAL page wiring, not just the helper in isolation: the
    warming card must actually build with a band, both lines and a legend,
    and must not leak anything into `wrapperStyle`.
    """
    from italy_dashboard.pages.climate import climate_page

    tree = climate_page().render()
    composed = _nodes(tree, "RechartsComposedChart")
    assert composed, "warming card must use the band+line composed chart"

    warming = composed[0]
    assert len(_nodes(warming, "RechartsArea")) == 1
    assert len(_nodes(warming, "RechartsLine")) == 2
    assert _nodes(warming, "RechartsLegend")
    assert "wrapperStyle" not in str(warming)


def test_climate_crime_scatters_render_and_carry_no_legend():
    """Pins the real page, not just the helper: both cards hold a single-series
    scatter whose series name IS the card heading, so a legend there is pure
    restatement."""
    from italy_dashboard.pages.climate_crime import climate_crime_page

    tree = climate_crime_page().render()
    charts = _nodes(tree, "RechartsScatterChart")
    assert len(charts) == 2, "both climate-crime scatters must still render"
    for chart in charts:
        assert _nodes(chart, "RechartsScatter"), "the scatter lost its data"
        assert not _nodes(chart, "RechartsLegend"), "single-series scatter kept a legend"


def test_crime_income_scatter_keeps_its_legend():
    """The crime page's income scatter carries two series (Italians vs
    foreigners), where colour is the ONLY thing separating the groups, so the
    gate must not take its legend away."""
    from italy_dashboard.pages.crime import crime_page

    charts = _nodes(crime_page().render(), "RechartsScatterChart")
    assert len(charts) == 1
    assert _nodes(charts[0], "RechartsLegend")


def test_crime_multi_series_line_charts_keep_their_legends():
    """The 2- and 3-series branches of the crime trend chart are compiled
    up-front by `rx.match`, so their legends are observable statically."""
    from italy_dashboard.pages.crime import crime_page

    line_charts = _nodes(crime_page().render(), "RechartsLineChart")
    with_legend = [ch for ch in line_charts if _nodes(ch, "RechartsLegend")]
    assert len(with_legend) >= 2, f"only {len(with_legend)} of {len(line_charts)} kept a legend"


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


# ------------------------------------------------------------ band_trend_chart
#
# One entity (annual temperature) shown three ways: a min/max band, its thin
# annual-mean line, and a heavier 10-year rolling-mean trend line, ALL in one
# hue. `t_rolling` is None at the series edges (see queries.climate_annual_
# series), which the chart must simply not draw a line through, not bridge.

BAND_ROWS = [
    {"period": "2000", "t_band": [10.0, 20.0], "t_mean": 15.0, "t_rolling": None},
    {"period": "2005", "t_band": [11.0, 21.0], "t_mean": 16.0, "t_rolling": 15.5},
    {"period": "2010", "t_band": [12.0, 22.0], "t_mean": 17.0, "t_rolling": 16.5},
    {"period": "2015", "t_band": [13.0, 23.0], "t_mean": 18.0, "t_rolling": None},
]


def _band_chart() -> rx.Component:
    return c.band_trend_chart(
        BAND_ROWS,
        band_key="t_band",
        mean_key="t_mean",
        rolling_key="t_rolling",
        band_label="Range",
        mean_label="Mean",
        rolling_label="10-yr average",
        color=theme.series(1),
    )


def _node_prop(node: dict, prop: str) -> str | None:
    """The raw `<prop>:<value>` string from a rendered node's props list."""
    for p in node.get("props", []):
        if p.startswith(f"{prop}:"):
            return p
    return None


def test_band_trend_chart_has_one_band_two_lines_and_a_legend():
    tree = _band_chart().render()
    assert len(_nodes(tree, "RechartsArea")) == 1
    assert len(_nodes(tree, "RechartsLine")) == 2
    assert _nodes(tree, "RechartsLegend")


def test_band_trend_chart_band_has_no_stroke_and_a_low_opacity_fill():
    """Verified mechanism (see `queries.climate_annual_series` / task spec):
    `stroke="none"` plus a translucent fill via `custom_attrs`, matching the
    `fill_opacity` pitfall already documented on `area_compare_chart` — `Area`
    has no `fill_opacity` field, so anything else here would silently land in
    `wrapperStyle` instead of actually reaching recharts.
    """
    tree = _band_chart().render()
    areas = _nodes(tree, "RechartsArea")
    assert len(areas) == 1
    assert _node_prop(areas[0], "stroke") == 'stroke:"none"'
    # fillOpacity must be a real prop on the Area itself, not swallowed.
    fill_opacity = next(p for p in areas[0]["props"] if p.startswith("fillOpacity"))
    value = float(fill_opacity.split(":", 1)[1])
    assert 0 < value < 0.5, "the band must stay translucent, not opaque"


def test_band_trend_chart_rolling_line_is_visually_heavier_than_the_mean_line():
    tree = _band_chart().render()
    lines = _nodes(tree, "RechartsLine")
    assert len(lines) == 2
    widths = []
    for node in lines:
        prop = _node_prop(node, "strokeWidth")
        assert prop is not None, "every line must set an explicit strokeWidth"
        widths.append(float(prop.split(":", 1)[1]))
    assert max(widths) > min(widths), "the rolling mean must outweigh the annual mean line"


def test_band_trend_chart_band_and_both_lines_share_one_hue():
    """One entity shown three ways: distinguished by mark weight, not colour."""
    tree = _band_chart().render()
    areas = _nodes(tree, "RechartsArea")
    lines = _nodes(tree, "RechartsLine")
    fill_prop = _node_prop(areas[0], "fill")
    assert fill_prop is not None
    fill = fill_prop.split(":", 1)[1]
    strokes = set()
    for line in lines:
        stroke_prop = _node_prop(line, "stroke")
        assert stroke_prop is not None
        strokes.add(stroke_prop.split(":", 1)[1])
    assert strokes == {fill}, "band fill and both line strokes must be the same colour"


def test_band_trend_chart_renders_band_both_lines_legend_no_wrapper_style():
    """The chart-renders acceptance test from the task spec, verbatim."""
    rendered = str(_band_chart().render())
    assert rendered.count("RechartsArea") >= 1
    assert rendered.count("RechartsLine") == 2
    assert "RechartsLegend" in rendered
    assert "wrapperStyle" not in rendered


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
    # The `wrapperStyle` check that used to live here now runs against EVERY
    # chart helper, see `test_no_chart_helper_swallows_a_prop_into_wrapper_style`.


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
    "band_trend_chart": lambda: c.band_trend_chart(
        BAND_ROWS,
        band_key="t_band",
        mean_key="t_mean",
        rolling_key="t_rolling",
        band_label="Range",
        mean_label="Mean",
        rolling_label="10-yr average",
        color=theme.series(1),
    ),
}


def _chrome_segments(rendered: str, tag: str) -> list[str]:
    """Every occurrence of `tag` in `rendered`, sliced to its OWN props list.

    `str(component.render())` is a Python repr of nested dicts shaped
    `{'name': 'RechartsXAxis', 'props': [...], 'children': [...]}`. Cutting each
    segment at that component's `'children'` key, rather than at a fixed
    character window, means an assertion about one axis can never be satisfied
    by a prop that belongs to the NEXT component in the tree.
    """
    segments = []
    start = 0
    while (idx := rendered.find(tag, start)) != -1:
        end = rendered.find("'children'", idx)
        segments.append(rendered[idx:end] if end != -1 else rendered[idx:])
        start = idx + len(tag)
    return segments


def _prop(segment: str, prop: str) -> str:
    """The single `<prop>:...` element of a rendered props list."""
    start = segment.index(f"{prop}:")
    end = segment.find("', '", start)
    return segment[start:end] if end != -1 else segment[start:]


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


@pytest.mark.parametrize("name", sorted(CHART_CHROME_HELPERS))
def test_axis_tick_labels_carry_their_own_fill_not_the_axis_line_colour(name: str):
    """Tick LABELS need their own colour; the check above cannot see them.

    The mode-awareness assertion above is satisfied by the axis's `stroke`
    alone, so it passed for the entire life of a real defect: every axis passed
    `custom_attrs={"fill": theme.ink_muted()}`, and that `fill` never reached a
    single label. Recharts builds label props as
    `{...axisProps, textAnchor, stroke: 'none', fill: stroke}`, so the axis's
    own `stroke` overwrites any supplied `fill` and the labels rendered at the
    axis line's contrast: 1.75:1 in light mode, 1.60:1 in dark, against a 3:1
    floor. The declared `tick` prop is the one recharts spreads LAST
    (`{...tickProps, ...customTickProps}`), so it is the only form that wins.

    Scoped to the `tick:` prop specifically, not the whole axis segment: a
    revert to the `custom_attrs` form still emits `fill:` somewhere in the
    render (as an axis-level prop), and a whole-segment substring search would
    happily accept it.
    """
    rendered = str(CHART_CHROME_HELPERS[name]().render())

    for tag in ("RechartsXAxis", "RechartsYAxis"):
        for segment in _chrome_segments(rendered, tag):
            assert "tick:" in segment, f"{name}: {tag} sets no tick label style"
            tick = _prop(segment, "tick")
            assert "fill" in tick, f"{name}: {tag} tick labels inherit the axis-line colour"
            # The label colour must follow the mode toggle like the rest of the
            # chrome, i.e. `theme.ink_muted()`, never a bare hex.
            assert "resolvedColorMode" in tick, f"{name}: {tag} tick fill is not mode-aware"


@pytest.mark.parametrize("name", sorted(CHART_CHROME_HELPERS))
def test_no_chart_helper_swallows_a_prop_into_wrapper_style(name: str):
    """A universal detector for the bug class that cost this plan four rounds.

    Reflex accepts an undeclared kwarg silently and sweeps it into its generic
    style fallback, rendered as `wrapperStyle:(...)` — a prop no recharts
    component reads. That is how an inert `fill_opacity=` on `Area`, an inert
    `stroke_width=` on `CartesianGrid` and an inert `type_=` on `ZAxis` all
    shipped looking correct in the rendered output. No helper here emits a
    `wrapperStyle` legitimately, so its mere presence anywhere in a chart's
    render means a kwarg was swallowed, whatever the kwarg happens to be.
    """
    rendered = str(CHART_CHROME_HELPERS[name]().render())
    assert "wrapperStyle" not in rendered, f"{name}: a kwarg was swallowed into wrapperStyle"


def test_line_chart_with_brush_builds():
    assert c.line_chart(ROWS, [("value", "V", theme.series(1))], brush=True).render()


def test_line_chart_brush_is_off_by_default():
    rendered = str(c.line_chart(ROWS, [("value", "V", theme.series(1))]).render())
    assert "RechartsBrush" not in rendered


def test_line_chart_brush_true_adds_a_brush():
    rendered = str(c.line_chart(ROWS, [("value", "V", theme.series(1))], brush=True).render())
    assert "RechartsBrush" in rendered


# ------------------------------------------------------------------ data_gate
#
# The fix for "the app shows an error callout while it is merely loading": a
# bare `mart_ready`-style bool defaults False, indistinguishable from
# "genuinely no data", so a page rendering directly on it shows the error
# callout on first paint, before `load()` has run. `data_gate` adds the third
# state (`has_loaded`) that tells the two apart.
#
# `rx.cond`'s render() ALWAYS embeds both branches (recharts/React decides
# which one to mount client-side; see reflex_components_core.core.cond.Cond),
# so a plain `"ERROR_TEXT" not in str(component.render())` assertion over the
# WHOLE tree can never distinguish the three states — both the loading
# placeholder's markup and the error callout's markup are always present
# somewhere in the string. These tests instead navigate to the STRUCTURAL
# slot each state occupies (loading = outer cond's false_value; ready = inner
# cond's true_value; empty = inner cond's false_value), which is fixed by
# which argument `data_gate` was called with, and check each slot on its own.

CHARTS_MARKER = "STATE_CHARTS_MARKER"
EMPTY_MARKER = "STATE_EMPTY_MARKER"


def _data_gate_branches(rendered_gate: dict) -> tuple[str, str, str]:
    """(loading, ready, empty) branch sub-trees, each stringified on its own."""
    outer = rendered_gate["children"][0]
    assert "cond_state" in outer, "expected the outer has_loaded cond"
    loading = str(outer["false_value"])

    inner = outer["true_value"]["children"][0]
    assert "cond_state" in inner, "expected the inner ready/mart_ready cond"
    ready = str(inner["true_value"])
    empty = str(inner["false_value"])
    return loading, ready, empty


def test_data_gate_loading_branch_never_contains_the_error_or_the_content():
    """State 1/3: not loaded yet. Must be neutral — never the error callout,
    and obviously not the real content either (it isn't ready to show yet).
    """
    gate = c.data_gate(
        ClimateState.has_loaded,
        ClimateState.mart_ready,
        rx.text(CHARTS_MARKER),
        rx.text(EMPTY_MARKER),
    )
    loading, _ready, _empty = _data_gate_branches(gate.render())

    assert EMPTY_MARKER not in loading, "loading branch must never show the error"
    assert CHARTS_MARKER not in loading, "loading branch must not show unready content either"


def test_data_gate_ready_branch_shows_content_not_the_error():
    """State 2/3: loaded and ready. The real content, and only the content."""
    gate = c.data_gate(
        ClimateState.has_loaded,
        ClimateState.mart_ready,
        rx.text(CHARTS_MARKER),
        rx.text(EMPTY_MARKER),
    )
    _loading, ready, _empty = _data_gate_branches(gate.render())

    assert CHARTS_MARKER in ready
    assert EMPTY_MARKER not in ready


def test_data_gate_empty_branch_shows_the_existing_error_callout_unchanged():
    """State 3/3: loaded but genuinely no data. The pre-existing callout,
    unchanged — this fix is about not lying during load, not about changing
    what the genuinely-empty case looks like.
    """
    gate = c.data_gate(
        ClimateState.has_loaded,
        ClimateState.mart_ready,
        rx.text(CHARTS_MARKER),
        rx.text(EMPTY_MARKER),
    )
    _loading, _ready, empty = _data_gate_branches(gate.render())

    assert EMPTY_MARKER in empty
    assert CHARTS_MARKER not in empty


def test_data_gate_defaults_to_a_spinner_while_loading_not_silence_or_error():
    """The default `loading=` placeholder is a spinner, not the caller's
    `empty` callout and not literally nothing — `shell()` is the one call
    site that deliberately overrides this to `rx.fragment()` (see its own
    comment); every page-content gate should get real, visible feedback.
    """
    gate = c.data_gate(
        ClimateState.has_loaded,
        ClimateState.mart_ready,
        rx.text(CHARTS_MARKER),
        rx.text(EMPTY_MARKER),
    )
    loading, _ready, _empty = _data_gate_branches(gate.render())
    assert "RadixThemesSpinner" in loading


def _cond_nodes(tree) -> list[dict]:
    """Every `Cond`-shaped node (has `cond_state`/`true_value`/`false_value`)
    found anywhere in a rendered tree, walked the same way `_nodes` (above)
    walks named components — `rx.cond` branches nest under keys other than
    `children`, so a `children`-only walk would miss them.
    """
    found = []
    stack = [tree]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if "cond_state" in node:
                found.append(node)
            stack.extend(node.values())
        elif isinstance(node, (list, tuple)):
            stack.extend(node)
    return found


def test_climate_page_wires_data_gate_with_its_own_state():
    """Pins the real page, not just the helper in isolation: `climate_page()`
    must gate its content on a `has_loaded` cond that itself WRAPS the
    `mart_ready` cond (exactly what `data_gate` builds), not merely have both
    strings appear somewhere in the page. A regression that reverts to a bare
    `rx.cond(ClimateState.mart_ready, ...)` still has `has_loaded` elsewhere
    in the tree (`shell()`'s own parameter), so a flat "both substrings
    appear" check would miss it — the nesting is what has_loaded is FOR.
    """
    from italy_dashboard.pages.climate import climate_page

    tree = climate_page().render()
    has_loaded_conds = [c for c in _cond_nodes(tree) if "has_loaded" in c["cond_state"]]
    assert has_loaded_conds, "expected at least one has_loaded-gated cond"

    wraps_mart_ready = [
        c for c in has_loaded_conds if any("mart_ready" in n["cond_state"] for n in _cond_nodes(c))
    ]
    assert wraps_mart_ready, (
        "the page's own content must be gated by has_loaded WRAPPING mart_ready "
        "(data_gate's shape), not just have both flags appear independently"
    )
