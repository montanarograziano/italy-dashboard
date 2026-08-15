"""Chart and UI colour tokens.

Values live in italy_dashboard/palette.py, which is plain data and machine
validated. This module wraps them in Reflex's native colour-mode conditional so
a component can ask for "the current mode's blue" without knowing the mode.

The bare constants below are the LIGHT values and remain for callers that have
not migrated to the accessors. New code should call the accessors.
"""

from __future__ import annotations

import reflex as rx

from italy_dashboard import palette

# Categorical series slots (light mode) — fixed order, never re-assigned.
SERIES_1 = palette.CATEGORICAL_LIGHT[0]  # blue
SERIES_2 = palette.CATEGORICAL_LIGHT[1]  # orange
SERIES_3 = palette.CATEGORICAL_LIGHT[2]  # aqua

# Chrome & ink (light)
SURFACE = palette.SURFACE_LIGHT
PAGE_BG = "#f9f9f7"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
AXIS = "#c3c2b7"
BORDER = "rgba(11,11,11,0.10)"

FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

# Dark counterparts, selected against the dark surface (not inverted).
_DARK = {
    "PAGE_BG": "#131312",
    "INK_PRIMARY": "#f4f4f2",
    "INK_SECONDARY": "#b8b7b2",
    "INK_MUTED": "#8a8983",
    "GRIDLINE": "#2e2e2c",
    "AXIS": "#3d3d3a",
    "BORDER": "rgba(244,244,242,0.12)",
}


def series(n: int) -> rx.Var:
    """The current mode's colour for categorical slot n (1-based, 1..3)."""
    if not 1 <= n <= len(palette.CATEGORICAL_LIGHT):
        raise ValueError(f"series slot {n} outside 1..{len(palette.CATEGORICAL_LIGHT)}")
    return rx.color_mode_cond(
        light=palette.CATEGORICAL_LIGHT[n - 1],
        dark=palette.CATEGORICAL_DARK[n - 1],
    )


def surface() -> rx.Var:
    return rx.color_mode_cond(light=palette.SURFACE_LIGHT, dark=palette.SURFACE_DARK)


def page_bg() -> rx.Var:
    return rx.color_mode_cond(light=PAGE_BG, dark=_DARK["PAGE_BG"])


def ink_primary() -> rx.Var:
    return rx.color_mode_cond(light=INK_PRIMARY, dark=_DARK["INK_PRIMARY"])


def ink_secondary() -> rx.Var:
    return rx.color_mode_cond(light=INK_SECONDARY, dark=_DARK["INK_SECONDARY"])


def ink_muted() -> rx.Var:
    return rx.color_mode_cond(light=INK_MUTED, dark=_DARK["INK_MUTED"])


def gridline() -> rx.Var:
    return rx.color_mode_cond(light=GRIDLINE, dark=_DARK["GRIDLINE"])


def axis() -> rx.Var:
    return rx.color_mode_cond(light=AXIS, dark=_DARK["AXIS"])


def border() -> rx.Var:
    return rx.color_mode_cond(light=BORDER, dark=_DARK["BORDER"])
