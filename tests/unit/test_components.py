"""Render tests for chart helpers: a chart that will not build is a broken page.

`stripe_chart` needs a test of its own, distinct from the query-layer test in
test_queries.py. The query test proves `climate_stripes` rows carry distinct
`var(--div-N)` fills; it says nothing about whether the CHART actually wires
each row's fill onto its own bar. A `Bar` painted with one constant colour
renders exactly as successfully as one with per-cell fills — the render step
alone cannot tell a diverging encoding from the single-hue bug it replaced.
"""

from __future__ import annotations

from italy_dashboard import components as c
from italy_dashboard import theme
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
            [(SCATTER_POINTS, "Panel", theme.SERIES_1)],
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
    rendered = _scatter(zero_lines=True)
    start = rendered.index("RechartsReferenceLine")
    props = rendered[start : start + 200]
    assert theme.AXIS in props  # chrome colour from theme.axis()
    assert theme.SERIES_1 not in props  # never the data series' own colour


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
        [("early", "1951-1980", theme.SERIES_1), ("late", "1996-2025", theme.SERIES_2)],
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
        [("early", "1951-1980", theme.SERIES_1), ("late", "1996-2025", theme.SERIES_2)],
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
