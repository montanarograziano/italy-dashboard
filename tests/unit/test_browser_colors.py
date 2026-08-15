"""Unit coverage for the WCAG contrast math the browser suite relies on.

Pure arithmetic, no browser needed: if this formula is wrong, the browser
contrast test (tests/browser/test_axis_contrast.py) would silently pass or
fail for the wrong reason, which defeats the point of measuring anything.
"""

from __future__ import annotations

import pytest

from tests.browser._colors import contrast_ratio, parse_rgb, relative_luminance


def test_parse_rgb_reads_rgb_and_rgba_strings():
    assert parse_rgb("rgb(137, 135, 129)") == (137.0, 135.0, 129.0)
    assert parse_rgb("rgba(11, 11, 11, 0.5)") == (11.0, 11.0, 11.0)


def test_parse_rgb_rejects_unparseable_input():
    with pytest.raises(ValueError):
        parse_rgb("none")


def test_relative_luminance_black_and_white_are_the_wcag_extremes():
    assert relative_luminance((0, 0, 0)) == pytest.approx(0.0, abs=1e-9)
    assert relative_luminance((255, 255, 255)) == pytest.approx(1.0, abs=1e-9)


def test_contrast_ratio_black_on_white_is_21_to_1():
    assert contrast_ratio("rgb(0, 0, 0)", "rgb(255, 255, 255)") == pytest.approx(21.0, abs=0.01)


def test_contrast_ratio_identical_colours_is_1_to_1():
    assert contrast_ratio("rgb(100, 100, 100)", "rgb(100, 100, 100)") == pytest.approx(
        1.0, abs=1e-9
    )


def test_contrast_ratio_is_symmetric():
    a, b = "rgb(20, 20, 20)", "rgb(240, 240, 240)"
    assert contrast_ratio(a, b) == pytest.approx(contrast_ratio(b, a), abs=1e-9)


def test_contrast_ratio_matches_the_documented_shipped_defect():
    """The axis-swallows-fill bug this whole suite exists to catch.

    `italy_dashboard/components.py::_tick_style` documents the shipped
    contrast as 1.75:1 in light mode and 1.60:1 in dark: recharts builds each
    tick label's props as `{...axisProps, fill: stroke}`, so the intended
    `ink_muted` fill was always overwritten by the AXIS line colour. Both
    numbers below are the axis colour measured against its own mode's surface
    (`AXIS` on `SURFACE_DARK`/`SURFACE_LIGHT` from italy_dashboard/theme.py),
    which is what actually rendered. This pins the formula against those real,
    previously-shipped, sub-3:1 numbers.
    """
    dark_ratio = contrast_ratio("rgb(61, 61, 58)", "rgb(26, 26, 25)")  # AXIS on SURFACE_DARK
    assert dark_ratio == pytest.approx(1.60, abs=0.01)
    light_ratio = contrast_ratio(
        "rgb(195, 194, 183)", "rgb(252, 252, 251)"
    )  # AXIS on SURFACE_LIGHT
    assert light_ratio == pytest.approx(1.75, abs=0.01)
