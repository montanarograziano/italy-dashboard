"""Chart & UI color tokens.

Palette follows a validated data-viz palette (colorblind-safe adjacent pairs,
light surface #fcfcfb). Series colors are assigned in fixed slot order and
never cycled; multi-series charts stay within the first three slots, which
validate for all pair combinations.
"""

# Categorical series slots (light mode) — fixed order, never re-assigned.
SERIES_1 = "#2a78d6"  # blue
SERIES_2 = "#eb6834"  # orange
SERIES_3 = "#1baf7a"  # aqua

# Chrome & ink
SURFACE = "#fcfcfb"
PAGE_BG = "#f9f9f7"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
AXIS = "#c3c2b7"
BORDER = "rgba(11,11,11,0.10)"

FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'
