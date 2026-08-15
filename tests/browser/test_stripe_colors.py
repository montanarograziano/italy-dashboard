"""Warming stripes must actually resolve their `var(--div-N)` CSS custom
properties to distinct real colours.

The stripe bars (`italy_dashboard/components.py::stripe_chart`) take their
per-bar colour from `var(--div-N)` custom properties injected into `:root`/
`.dark` by `components.py::shell()` (see `palette.py::diverging_css_vars`).
No Python-side render-tree test can confirm those custom properties actually
resolve in a browser: the rendered tree looks identical whether `var(--div-5)`
paints as a real orange or as nothing at all.
"""

from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

# Default `t()` (en) string for the stripes card's heading
# (italy_dashboard/translations.py); `ClimateState.lang` defaults to "en" and
# each test gets a fresh browser context with no stored language preference.
_STRIPES_HEADING = "Anomaly against the 1981-2010 normal"

# The next `.recharts-wrapper` in document order AFTER this card's own
# heading is this card's own chart: `card()` renders heading, subtitle, then
# children in one vstack, so no other card's chart can land between them.
_NEXT_CHART_XPATH = (
    "xpath=following::*"
    "[contains(concat(' ', normalize-space(@class), ' '), ' recharts-wrapper ')][1]"
)


def test_stripe_bars_resolve_css_custom_properties_to_distinct_colours(page, app_server):
    page.goto(f"{app_server}/climate")

    heading = page.get_by_text(_STRIPES_HEADING)
    heading.wait_for(state="visible")
    chart = heading.locator(_NEXT_CHART_XPATH)
    bars = chart.locator(".recharts-rectangle")
    bars.first.wait_for(state="attached")

    count = bars.count()
    assert count > 1, "expected multiple stripe bars to compare fills across"

    fills = {bars.nth(i).evaluate("(el) => getComputedStyle(el).fill") for i in range(count)}
    print(f"[stripe-colours] {count} bars, {len(fills)} distinct computed fills: {sorted(fills)}")

    assert "" not in fills, f"a stripe bar's fill did not resolve at all: {fills}"
    assert "rgba(0, 0, 0, 0)" not in fills, f"a stripe bar's fill resolved to transparent: {fills}"
    assert "none" not in fills, f"a stripe bar's fill resolved to 'none': {fills}"
    assert len(fills) > 1, (
        f"expected more than one distinct fill across the stripe bars (the whole point of the "
        f"diverging encoding), got only {fills}"
    )
