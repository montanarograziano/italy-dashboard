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
