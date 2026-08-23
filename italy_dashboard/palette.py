"""Validated colour roles, as plain data.

No Reflex import here on purpose: the palette must be readable by tests and by
the Node validator without pulling in the UI framework.

Every value was derived by search against dataviz/scripts/validate_palette.js
and verified independently. The checks are automated in tests/unit/test_palette.py
precisely so a future edit cannot quietly break colourblind separation.

Dark steps are SELECTED and validated against the dark surface, never a
mechanical inversion of the light values: an inversion fails the dark lightness
band outright, which is what the first candidate set did.
"""

from __future__ import annotations

SURFACE_LIGHT = "#fcfcfb"
SURFACE_DARK = "#1a1a19"

# UI text and gridline tokens (not chart-data colours, so not run through the
# colourblind validator below). Shared with the static frontend via
# scripts/generate_palette.py so its body text and gridlines match Reflex's:
# italy_dashboard/theme.py wraps these in rx.color_mode_cond rather than
# hardcoding its own copies.
INK_PRIMARY_LIGHT = "#0b0b0b"
INK_PRIMARY_DARK = "#f4f4f2"
INK_SECONDARY_LIGHT = "#52514e"
INK_SECONDARY_DARK = "#b8b7b2"
# INK_MUTED_LIGHT was #898781 (3.50:1 on SURFACE_LIGHT): under WCAG AA's
# 4.5:1 floor for normal-weight text under 18px, the size/weight every
# caption and sub-caption that uses this token actually renders at (KPI tile
# notes, chart sub-captions -- see components.py's `card`/`stat_tile`).
# Darkened along the SAME hue/saturation (HSL h=0.125, s=0.033, only L
# lowered) rather than picked ad hoc, so it reads as the same muted warm
# grey, just dark enough to clear the floor: 4.89:1, with headroom above the
# 4.50:1 razor edge a smaller nudge would have landed on. INK_MUTED_DARK is
# unrelated (selected independently against SURFACE_DARK, not a mechanical
# inversion -- see the module docstring) and already clears AA at 4.97:1;
# verified, not changed.
INK_MUTED_LIGHT = "#716f6a"
INK_MUTED_DARK = "#8a8983"
GRIDLINE_LIGHT = "#e1e0d9"
GRIDLINE_DARK = "#2e2e2c"

# Warning/caveat accent: an amber distinct in hue (~40 degrees) from the
# categorical orange (~17 degrees, CATEGORICAL_LIGHT[1]) so a data-quality
# callout is never mistaken for a chart series. Not run through the
# colourblind validator below (a UI chrome role, not chart-data, same as the
# ink/gridline tokens above) -- picked instead by checking WCAG contrast
# against SURFACE_LIGHT/SURFACE_DARK directly (>=4.5:1, AA for normal text):
# #8f5e00 is 5.43:1 on SURFACE_LIGHT, #e8b339 is 9.07:1 on SURFACE_DARK.
#
# Consumed only by the static frontend's web/src/theme.ts (`warning()`),
# for its `Callout` component. Reflex's own equivalent (`rx.callout(...,
# color_scheme="amber")` in climate.py/climate_crime.py) gets its amber from
# Radix's built-in theme rather than this palette, so italy_dashboard/theme.py
# does not grow a matching accessor -- nothing there would call it.
WARNING_LIGHT = "#8f5e00"
WARNING_DARK = "#e8b339"

# Categorical: fixed slot order, never cycled. Blue, orange, aqua in both modes,
# so a series keeps its identity when the mode changes.
CATEGORICAL_LIGHT = ("#2a78d6", "#eb6834", "#1baf7a")
CATEGORICAL_DARK = ("#2072d0", "#de5c27", "#00995f")

# Diverging, cool -> neutral -> warm, 7 steps. Index 3 is the neutral midpoint.
# Blue and orange are the poles, reusing the categorical hues so the palette
# reads as one system rather than two unrelated schemes.
DIVERGING_LIGHT = (
    "#1f5fa8",
    "#2a78d6",
    "#8ab8ea",
    "#b2b2b2",
    "#ff7d44",
    "#eb6834",
    "#cc5e34",
)
DIVERGING_DARK = (
    "#005acb",
    "#2072d0",
    "#4986d4",
    "#4c4d4c",
    "#ef7344",
    "#de5c27",
    "#c34f1e",
)

# Sequential: one hue, pale -> deep. Validated and covered by test_palette.py,
# but nothing consumes it yet: it is reserved for a future magnitude encoding
# (e.g. a choropleth), where a diverging ramp would falsely imply a midpoint.
SEQUENTIAL_LIGHT = ("#71b2ff", "#5090e2", "#2e6ebd", "#054e9a", "#002d77")
SEQUENTIAL_DARK = ("#8ed1ff", "#6eafff", "#4e8ee0", "#2e6ebd", "#074f9b")

DIVERGING_STEPS = len(DIVERGING_LIGHT)


def diverging_bucket(anomaly: float, half_range: float = 1.5) -> int:
    """Map an anomaly in degrees Celsius onto a diverging step index (0..6).

    `half_range` is the anomaly magnitude that saturates an end of the ramp.
    1.5 C is chosen so Italian annual anomalies spread across the ramp instead
    of clumping in the middle; values beyond it clamp rather than wrap.
    """
    if half_range <= 0:
        raise ValueError("half_range must be positive")
    mid = DIVERGING_STEPS // 2
    step = half_range / mid
    index = mid + round(anomaly / step)
    return max(0, min(DIVERGING_STEPS - 1, index))


_EXPLICIT_DARK_SELECTOR = '.dark, [data-theme="dark"]'

# Guards the system-preference fallback below so an explicit choice, in
# EITHER frontend's convention, always wins over the OS setting.
#
# Both `.dark` and `.light` are excluded, not just `.dark`: Reflex's own
# ThemeProvider (web/utils/react-theme.js in the compiled `.web/` output)
# toggles `.light`/`.dark` directly on `document.documentElement` -- i.e. on
# this same `:root` -- via `root.classList.add(resolvedTheme)`. A guard that
# only excluded `.dark` would still match `:root.light` and let this query
# re-flip a Reflex user who explicitly chose light back to dark whenever
# their OS prefers dark. `[data-theme="dark"]`/`[data-theme="light"]` are the
# static app's equivalent explicit markers (App.tsx sets the attribute only
# on an explicit choice, deleting it for "system").
_NO_EXPLICIT_CHOICE = ':not(.dark):not(.light):not([data-theme="dark"]):not([data-theme="light"])'


def diverging_css_vars() -> str:
    """CSS custom properties for the diverging ramp, covering all three
    colour-mode states both frontends need.

    A per-datum colour cannot be a build-time constant, so the stripe chart
    emits `var(--div-N)` per bar and lets CSS resolve the mode. Everything
    that is not per-datum uses rx.color_mode_cond instead.

    Three rules, not two:
    - `:root` -- the light palette. Also what a pre-hydration page paints
      before either frontend's JS has run.
    - an explicit dark choice -- `.dark` is Reflex/Radix's convention
      (a class toggled on `document.documentElement`); `[data-theme="dark"]`
      is the static shell's (an attribute on `<html>`, see web/src/App.tsx).
      Both frontends are listed on one rule so the two stay in lockstep.
    - system preference, via `prefers-color-scheme`, guarded by
      `_NO_EXPLICIT_CHOICE` so it only ever applies when NEITHER frontend has
      recorded an explicit choice on `:root`.

    Previously this emitted only `:root`/`.dark`: correct for Reflex, but the
    static shell sets `data-theme` rather than a class, so its dark mode never
    switched the ramp at all, and its default (no attribute, system-driven)
    state matched neither rule. See tests/unit/test_palette_artifacts.py and
    tests/browser/test_static_app.py for the regression tests.
    """
    light = "\n".join(f"  --div-{i}: {c};" for i, c in enumerate(DIVERGING_LIGHT))
    dark = "\n".join(f"  --div-{i}: {c};" for i, c in enumerate(DIVERGING_DARK))
    dark_indented = "\n".join(f"    --div-{i}: {c};" for i, c in enumerate(DIVERGING_DARK))
    return (
        f":root {{\n{light}\n}}\n"
        "\n"
        f"{_EXPLICIT_DARK_SELECTOR} {{\n{dark}\n}}\n"
        "\n"
        "@media (prefers-color-scheme: dark) {\n"
        f"  :root{_NO_EXPLICIT_CHOICE} {{\n{dark_indented}\n  }}\n"
        "}\n"
    )
