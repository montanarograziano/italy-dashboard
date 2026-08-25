"""theme.py's public surface: accessors only, no bare light-mode constants.

Two things are pinned here:

- `border_css()` / `tooltip_border_css()` build a COMPLETE CSS declaration
  (`"1px solid <colour>"`) rather than a bare colour, because a Reflex Var
  does not survive being interpolated into an f-string the way a plain string
  does. Verified directly below: `f"1px solid {some_var}"` bakes the Var's
  internal marker (`<reflex.Var>...</reflex.Var>`) into the resulting string
  as literal text. That string happens to render correctly when it is later
  passed straight into a Reflex component prop, because Reflex's own
  `LiteralVar.create()` step recognises the marker and reconstructs the
  expression from it before compiling to JS — but that recovery is an
  internal implementation detail, not something call sites should depend on,
  which is why `border_css()`/`tooltip_border_css()` build the value here
  instead.
- The old bare constants (`theme.SERIES_1`, `theme.GRIDLINE`, `theme.AXIS`,
  etc.) are gone, not merely deprecated: leaving them reachable is exactly
  what let ~84 call sites quietly stay pinned to light mode while the toggle
  itself worked. `test_no_module_references_the_removed_bare_constants` greps
  every module under `italy_dashboard/` so a reintroduction under a new call
  site fails a test immediately, rather than waiting for someone to notice a
  chart that will not flip.
"""

from __future__ import annotations

import re
from pathlib import Path

import reflex as rx

from italy_dashboard import palette, theme

_REMOVED_BARE_NAMES = (
    "SERIES_1",
    "SERIES_2",
    "SERIES_3",
    "INK_PRIMARY",
    "INK_SECONDARY",
    "INK_MUTED",
    "GRIDLINE",
    "AXIS",
    "SURFACE",
    "PAGE_BG",
    "BORDER",
)
_BARE_PATTERN = re.compile(r"theme\.(" + "|".join(_REMOVED_BARE_NAMES) + r")\b")


def test_removed_bare_constants_are_not_attributes_of_theme():
    for name in _REMOVED_BARE_NAMES:
        assert not hasattr(theme, name), f"theme.{name} should not exist"
    # FONT is the one token that does not vary with colour mode, so it is
    # kept as a plain public constant rather than growing a pointless
    # accessor; this is not part of the bug the other names caused.
    assert isinstance(theme.FONT, str)


def test_theme_exposes_no_public_str_constants_besides_font():
    """Closes a gap `test_no_module_references_the_removed_bare_constants`
    cannot: that test greps for the RETIRED NAMES, so it says nothing about
    someone reintroducing the same bug under a NEW name (e.g. a fresh
    `GRID_LIGHT = "#e1e0d9"` constant, used at a call site with no
    `theme.GRIDLINE` text anywhere). This asserts on SHAPE instead of name:
    the only public module-level `str` attribute `theme` may expose is
    `FONT`, which is colour-mode-invariant and was never part of the bug.
    Any other bare colour constant, whatever it is called, fails this.
    """
    public_str_attrs = {
        name: value
        for name, value in vars(theme).items()
        if not name.startswith("_") and isinstance(value, str)
    }
    assert public_str_attrs == {"FONT": theme.FONT}


def test_no_module_references_the_removed_bare_constants():
    """A future `theme.GRIDLINE`-shaped call site would silently pin a chart
    to light mode again. This scans every module under `italy_dashboard/` (a
    text search, not just relying on the `AttributeError` the first time the
    code path actually executes) so that regression fails here instead.
    """
    root = Path(__file__).resolve().parents[2] / "italy_dashboard"
    offenders = []
    for path in sorted(root.rglob("*.py")):
        text = path.read_text()
        offenders.extend(
            f"{path.relative_to(root.parent)}: {m.group(0)}" for m in _BARE_PATTERN.finditer(text)
        )
    assert not offenders, "bare light-mode constants referenced:\n" + "\n".join(offenders)


def test_fstring_interpolation_of_a_var_bakes_in_a_broken_marker():
    """Documents the exact failure mode `border_css()`/`tooltip_border_css()`
    exist to avoid: naively writing `f"1px solid {theme.gridline()}"` does NOT
    produce a usable colour-mode-aware string on its own.
    """
    v = theme.gridline()
    s = f"1px solid {v}"
    assert type(s) is str
    # The Var's internal marker is baked into the string as literal text
    # instead of being resolved: a clean value would read
    # `1px solid <cond> ? "#e1e0d9" : "#2e2e2c"` with no `<reflex.Var>` noise
    # and no duplicated "1px solid " prefix.
    assert "<reflex.Var>" in s
    assert s.count("1px solid") == 1  # the literal prefix, not a resolved pair


# The three tests below assert each accessor renders a COMPLETE CSS
# declaration (the bug they exist for -- see test_fstring_interpolation_... above)
# for BOTH modes, under a real colour-mode conditional, and that it is built on
# the palette token its docstring says it is.
#
# The expected colours are read from `palette` rather than written out as hex.
# They used to be hardcoded, which made this file a SECOND place every palette
# value had to be updated -- and the failure it produced said "assert '1px solid
# rgba(11,11,11,0.10)' in ...", i.e. it reported a stale copy in the test as if
# it were a regression in the code. Naming the constant keeps every real
# assertion (complete declaration, both modes, correct token) while removing the
# duplication: substituting the wrong token in theme.py still fails, because
# each test names the specific constant that accessor is documented to use.


def test_border_css_is_a_complete_declaration_for_both_modes():
    rendered = str(rx.box(border=theme.border_css()).render())
    assert f'"1px solid {palette.BORDER_LIGHT}"' in rendered
    assert f'"1px solid {palette.BORDER_DARK}"' in rendered
    assert "resolvedColorMode" in rendered


def test_tooltip_border_css_is_a_complete_declaration_for_both_modes():
    """Built on GRIDLINE, deliberately subtler than the card BORDER token."""
    rendered = str(rx.box(border=theme.tooltip_border_css()).render())
    assert f'"1px solid {palette.GRIDLINE_LIGHT}"' in rendered
    assert f'"1px solid {palette.GRIDLINE_DARK}"' in rendered
    assert "resolvedColorMode" in rendered
    # ...and therefore NOT the card-edge token, which is the distinction this
    # accessor exists to make.
    assert palette.BORDER_LIGHT not in rendered


def test_selection_border_css_is_a_complete_declaration_for_both_modes():
    """Used to ring a selected item (e.g. the climate page's cross-city
    ranking/grid acknowledging the currently selected city). Built on
    INK_PRIMARY, not BORDER: BORDER is a deliberately subtle hairline (see
    border_css()), which would defeat a selection ring meant to stand out.
    """
    rendered = str(rx.box(border=theme.selection_border_css()).render())
    assert f'"2px solid {palette.INK_PRIMARY_LIGHT}"' in rendered
    assert f'"2px solid {palette.INK_PRIMARY_DARK}"' in rendered
    assert "resolvedColorMode" in rendered
    # Not the hairline BORDER token: that is the whole point of this accessor
    # (see the docstring above), so a future edit that "simplifies" it into
    # border_css() has to fail here.
    assert palette.BORDER_LIGHT not in rendered
