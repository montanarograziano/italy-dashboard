"""The warming chart's min/max band must render translucent, not opaque.

`band_trend_chart` (italy_dashboard/components.py) draws an `Area` band whose
`fillOpacity` is set through `custom_attrs={"fillOpacity": 0.22}`, not a
`fill_opacity=` kwarg: `Area` has no such declared field, so an undeclared
kwarg would silently land in Reflex's generic `wrapperStyle` fallback, a prop
recharts never reads. A render-tree test can see "0.22" was passed in and
still be looking at a component that paints fully opaque in a browser — the
whole failure mode this test exists to catch.
"""

from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

# Default `t()` (en) string for the warming chart's card heading
# (italy_dashboard/translations.py).
_WARMING_HEADING = "Annual temperature"

# The next `.recharts-area-area` in document order after this card's own
# heading is this card's own band: `card()` renders heading, subtitle, then
# children in one vstack, so no other card's chart can land between them.
_NEXT_BAND_XPATH = (
    "xpath=following::*"
    "[contains(concat(' ', normalize-space(@class), ' '), ' recharts-area-area ')][1]"
)


def test_warming_band_renders_translucent(page, app_server):
    page.goto(f"{app_server}/climate")

    heading = page.get_by_text(_WARMING_HEADING)
    heading.wait_for(state="visible")
    band = heading.locator(_NEXT_BAND_XPATH)
    band.wait_for(state="attached")

    fill_opacity = float(band.evaluate("(el) => getComputedStyle(el).fillOpacity"))
    print(f"[band-opacity] computed fill-opacity: {fill_opacity}")

    assert 0 < fill_opacity < 1, (
        f"band fill-opacity is {fill_opacity}, expected strictly between 0 and 1 "
        f"(a swallowed prop would leave it at the recharts default instead)"
    )
