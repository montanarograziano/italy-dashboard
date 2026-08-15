"""Axis tick labels must clear WCAG's 3:1 non-text contrast floor, in BOTH
colour modes.

This is the regression test for the real defect that motivated this whole
suite: every axis passed its tick colour via `custom_attrs={"fill": ...}`,
but recharts builds each tick label's props as `{...axisProps, fill: stroke}`
— the axis LINE colour always won over the intended fill (see
`italy_dashboard/components.py::_tick_style` for the full mechanism). Dark
mode shipped at 1.60:1, invisible in practice, and every render-tree test
passed throughout because the Python-side component tree looked exactly as
intended.

No hardcoded hex here: both the tick's fill and the surface it sits on are
read back from the browser's own `getComputedStyle`, so this measures what
was actually painted, not what the source claims.
"""

from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api")

from tests.browser._colors import contrast_ratio

pytestmark = pytest.mark.browser

WCAG_NON_TEXT_MIN = 3.0

_READ_TICK_AND_BACKGROUND_JS = """(el) => {
    function backgroundOf(node) {
        while (node) {
            const colour = getComputedStyle(node).backgroundColor;
            if (colour && colour !== "rgba(0, 0, 0, 0)" && colour !== "transparent") {
                return colour;
            }
            node = node.parentElement;
        }
        return getComputedStyle(document.body).backgroundColor;
    }
    return [getComputedStyle(el).fill, backgroundOf(el)];
}"""


def _tick_fill_and_background(page) -> tuple[str, str]:
    """The first axis tick label's computed fill, and the real background behind it."""
    tick = page.locator(".recharts-cartesian-axis-tick-value").first
    tick.wait_for(state="visible")
    fill, background = tick.evaluate(_READ_TICK_AND_BACKGROUND_JS)
    return fill, background


def test_axis_tick_contrast_clears_wcag_floor_in_both_modes(page, app_server):
    page.goto(f"{app_server}/climate")
    page.wait_for_selector(".recharts-cartesian-axis-tick-value")

    light_fill, light_bg = _tick_fill_and_background(page)
    light_ratio = contrast_ratio(light_fill, light_bg)
    print(
        f"[axis-contrast] light mode: {light_ratio:.2f}:1  (fill={light_fill!r}, bg={light_bg!r})"
    )
    assert light_ratio >= WCAG_NON_TEXT_MIN, (
        f"light mode axis tick contrast is {light_ratio:.2f}:1 (fill={light_fill!r} on "
        f"bg={light_bg!r}), under the {WCAG_NON_TEXT_MIN}:1 WCAG non-text floor"
    )

    toggle = page.locator("button:has(svg.lucide-sun), button:has(svg.lucide-moon)").first
    toggle.click()
    page.wait_for_function("document.documentElement.classList.contains('dark')")
    # The colour-mode CSS custom properties repaint on the next frame; give the
    # SVG a moment to actually reflect the new `fill` before reading it back.
    page.wait_for_timeout(150)

    dark_fill, dark_bg = _tick_fill_and_background(page)
    dark_ratio = contrast_ratio(dark_fill, dark_bg)
    print(f"[axis-contrast] dark mode:  {dark_ratio:.2f}:1  (fill={dark_fill!r}, bg={dark_bg!r})")
    assert dark_ratio >= WCAG_NON_TEXT_MIN, (
        f"dark mode axis tick contrast is {dark_ratio:.2f}:1 (fill={dark_fill!r} on "
        f"bg={dark_bg!r}), under the {WCAG_NON_TEXT_MIN}:1 WCAG non-text floor"
    )
