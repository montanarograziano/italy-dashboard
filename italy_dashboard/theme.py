"""Chart and UI colour tokens.

Values live in italy_dashboard/palette.py, which is plain data and machine
validated. This module wraps them in Reflex's native colour-mode conditional so
a component can ask for "the current mode's blue" without knowing the mode.

Every colour token is reached through an accessor (`series()`, `surface()`,
`ink_primary()`, `gridline()`, `axis()`, `border()`, ...), which returns an
`rx.color_mode_cond` Var that follows the toggle. There are no public bare
light-mode constants: an earlier version of this module exposed both a bare
constant (fixed at the light value) and an accessor for the same colour, and
~84 call sites quietly used the bare constant, so toggling dark mode flipped
the tooltip and page shell but left every chart's gridlines, axes and tick
labels pinned to light-mode hex on a dark surface. Removing the bare names
turns that mistake into an immediate `AttributeError` instead of a silent
rendering bug; `tests/unit/test_theme.py` also greps for the old names as a
second guard against reintroducing them under a new call site.

`FONT` is the one exception: the font family does not vary with colour mode,
so it stays a plain public string rather than growing a pointless accessor.

Two call sites need a COMPLETE CSS value (e.g. `"1px solid <colour>"`) rather
than a bare colour, because a Reflex Var does not survive f-string
interpolation the way a plain string does: `f"1px solid {some_var}"` bakes the
Var's repr into the string instead of producing a live conditional wherever
the plain-string path does not run it back through Reflex's Var machinery.
`border_css()` and `tooltip_border_css()` build the whole declaration here so
callers never assemble it themselves.
"""

from __future__ import annotations

# NOT a guarded optional import (contrast ingestion/cds.py): `reflex` is a
# hard runtime dependency, is declared in pyproject.toml's [project]
# dependencies, and is installed in .venv -- `uv run python -c "import
# italy_dashboard.theme"` works, and `uv run pyrefly check italy_dashboard/`
# (the typechecker `just check` and CI actually run, see [tool.pyrefly])
# reports 0 errors on this file.
#
# The suppression exists for a Pyright-based language server whose workspace
# root is a directory ABOVE this repo (e.g. an editor/agent opened on the
# parent projects folder). Such a server never reads our pyrightconfig.json
# and so resolves imports against the system interpreter, where reflex is
# absent -- a pure environment artefact that also produces knock-on
# reportCallIssue noise on every `rx.*` call in components.py. Scoped to the
# one rule on the one line, per the convention in f1b989e, so a genuinely
# missing import elsewhere still surfaces.
import reflex as rx  # pyright: ignore[reportMissingImports]

from italy_dashboard import palette

FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

# Light and dark chrome & ink values, keyed identically. Private: nothing
# outside this module should reach for a single mode's colour directly — that
# is exactly the bug described above. Always go through the accessors below.
# PAGE_BG, AXIS and BORDER used to be local literals here, so the static
# frontend (which reads shared/palette.json, generated from palette.py) had no
# way to reach them and painted its page, its cards and its chart axes all
# from SURFACE/INK_PRIMARY instead -- the flat, over-contrasted look this pass
# exists to fix. They now live in palette.py alongside every other role and
# are shared by both frontends. The old AXIS values (#c3c2b7 / #3d3d3a) were
# also under WCAG's 3:1 non-text floor against their own surfaces (1.53:1 and
# 1.61:1 respectively); palette.AXIS_* clears it at ~6:1.
_LIGHT = {
    "SURFACE": palette.SURFACE_LIGHT,
    "PAGE_BG": palette.PAGE_BG_LIGHT,
    "INK_PRIMARY": palette.INK_PRIMARY_LIGHT,
    "INK_SECONDARY": palette.INK_SECONDARY_LIGHT,
    "INK_MUTED": palette.INK_MUTED_LIGHT,
    "GRIDLINE": palette.GRIDLINE_LIGHT,
    "AXIS": palette.AXIS_LIGHT,
    "BORDER": palette.BORDER_LIGHT,
}

# Dark counterparts, selected against the dark surface (not inverted).
_DARK = {
    "SURFACE": palette.SURFACE_DARK,
    "PAGE_BG": palette.PAGE_BG_DARK,
    "INK_PRIMARY": palette.INK_PRIMARY_DARK,
    "INK_SECONDARY": palette.INK_SECONDARY_DARK,
    "INK_MUTED": palette.INK_MUTED_DARK,
    "GRIDLINE": palette.GRIDLINE_DARK,
    "AXIS": palette.AXIS_DARK,
    "BORDER": palette.BORDER_DARK,
}


def _cond(key: str) -> rx.Var:
    return rx.color_mode_cond(light=_LIGHT[key], dark=_DARK[key])


def series(n: int) -> rx.Var:
    """The current mode's colour for categorical slot n (1-based, 1..3)."""
    if not 1 <= n <= len(palette.CATEGORICAL_LIGHT):
        raise ValueError(f"series slot {n} outside 1..{len(palette.CATEGORICAL_LIGHT)}")
    return rx.color_mode_cond(
        light=palette.CATEGORICAL_LIGHT[n - 1],
        dark=palette.CATEGORICAL_DARK[n - 1],
    )


def surface() -> rx.Var:
    return _cond("SURFACE")


def page_bg() -> rx.Var:
    return _cond("PAGE_BG")


def ink_primary() -> rx.Var:
    return _cond("INK_PRIMARY")


def ink_secondary() -> rx.Var:
    return _cond("INK_SECONDARY")


def ink_muted() -> rx.Var:
    return _cond("INK_MUTED")


def gridline() -> rx.Var:
    return _cond("GRIDLINE")


def axis() -> rx.Var:
    return _cond("AXIS")


def border() -> rx.Var:
    return _cond("BORDER")


def border_css() -> rx.Var:
    """The full `1px solid <colour>` value, using the BORDER token.

    A Var cannot be interpolated into an f-string (see module docstring), so
    callers that need the whole CSS declaration (`border=`, `border_bottom=`)
    get it built here under `color_mode_cond` rather than assembling it
    themselves with `f"1px solid {border()}"`.
    """
    return rx.color_mode_cond(
        light=f"1px solid {_LIGHT['BORDER']}",
        dark=f"1px solid {_DARK['BORDER']}",
    )


def tooltip_border_css() -> rx.Var:
    """The full `1px solid <colour>` value, using the GRIDLINE token.

    The chart tooltip wants a subtler line than the card BORDER token (it
    matches the gridlines instead), so it gets its own complete-value
    accessor rather than sharing `border_css()`.
    """
    return rx.color_mode_cond(
        light=f"1px solid {_LIGHT['GRIDLINE']}",
        dark=f"1px solid {_DARK['GRIDLINE']}",
    )


def selection_border_css() -> rx.Var:
    """The full `2px solid <colour>` ring used to call out a selected item.

    Built on INK_PRIMARY, not the BORDER token: BORDER is a deliberately
    subtle, near-invisible hairline for card edges (see `border_css()`),
    which would defeat the point of a ring meant to actually stand out.
    """
    return rx.color_mode_cond(
        light=f"2px solid {_LIGHT['INK_PRIMARY']}",
        dark=f"2px solid {_DARK['INK_PRIMARY']}",
    )
