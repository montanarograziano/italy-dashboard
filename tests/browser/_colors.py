"""WCAG relative-luminance contrast helpers.

Framework-agnostic on purpose: these operate on the plain `rgb(...)`/
`rgba(...)` strings a browser's `getComputedStyle(...)` returns, not on
Reflex Vars or our own hex literals. That is the whole point of the browser
test that uses this module — it must not smuggle in an assumption about what
colour SHOULD have been painted, only measure what actually was.
"""

from __future__ import annotations

import re

_RGB_RE = re.compile(r"rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)")


def parse_rgb(css_color: str) -> tuple[float, float, float]:
    """Parse a computed-style `rgb(...)`/`rgba(...)` string into (r, g, b), each 0..255."""
    match = _RGB_RE.search(css_color)
    if not match:
        raise ValueError(f"cannot parse an rgb()/rgba() colour out of {css_color!r}")
    r, g, b = (float(x) for x in match.groups())
    return r, g, b


def _channel_luminance(c: float) -> float:
    c = c / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb: tuple[float, float, float]) -> float:
    """WCAG relative luminance of an (r, g, b) triple, each 0..255."""
    r, g, b = rgb
    return (
        0.2126 * _channel_luminance(r)
        + 0.7152 * _channel_luminance(g)
        + 0.0722 * _channel_luminance(b)
    )


def contrast_ratio(css_color_a: str, css_color_b: str) -> float:
    """WCAG contrast ratio between two computed-style colour strings (always >= 1.0)."""
    luminance_a = relative_luminance(parse_rgb(css_color_a))
    luminance_b = relative_luminance(parse_rgb(css_color_b))
    lighter, darker = max(luminance_a, luminance_b), min(luminance_a, luminance_b)
    return (lighter + 0.05) / (darker + 0.05)
