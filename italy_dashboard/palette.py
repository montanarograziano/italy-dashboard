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

# Sequential: one hue, pale -> deep.
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


def diverging_css_vars() -> str:
    """CSS custom properties for the diverging ramp, both modes.

    A per-datum colour cannot be a build-time constant, so the stripe chart
    emits `var(--div-N)` per bar and lets CSS resolve the mode. Everything that
    is not per-datum uses rx.color_mode_cond instead.
    """
    light = "\n".join(f"  --div-{i}: {c};" for i, c in enumerate(DIVERGING_LIGHT))
    dark = "\n".join(f"  --div-{i}: {c};" for i, c in enumerate(DIVERGING_DARK))
    return f":root {{\n{light}\n}}\n\n.dark {{\n{dark}\n}}\n"
