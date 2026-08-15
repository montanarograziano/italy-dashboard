# Visualization Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise the dashboard's charts from functional to well-designed: correct encodings, a validated multi-role palette, visual polish, two richer chart forms, and dark mode.

**Architecture:** `theme.py` grows from flat constants into four colour roles across two modes, exposed as mode-aware accessors built on Reflex's native `rx.color_mode_cond`. Per-datum colours that must also react to mode (warming stripes) resolve through CSS custom properties, because a per-row colour cannot be a build-time constant. `components.py` gains chart helpers; the two climate pages consume them.

**Tech Stack:** Reflex 0.9.8 (Recharts wrapper), Python 3.11+, uv, pytest, Node (palette validator).

**Spec:** `docs/superpowers/specs/2026-08-15-visualization-quality-design.md`

## Global Constraints

- Line length 100. Ruff lint selects E, W, F, I, UP, B, SIM, C4, RUF.
- `italy_dashboard/` must never make network calls.
- Every user-facing string goes through `t()`. **Every EN key needs its IT counterpart** — a missing IT key raises at render time, not import, so no test catches it. Verify parity after any translation edit.
- Never a dual-axis chart. Two measures of different scale become two charts or one indexed to a common base.
- Categorical hues are assigned in fixed slot order and never cycled.
- Sequential ramps are one hue, light to dark. Diverging ramps are two hues with a neutral gray midpoint. Never a rainbow, never a hue at the midpoint.
- Text wears ink tokens, never a series colour.
- A legend is present for every chart with 2 or more series.
- Palette values are **exactly** those in the spec. Do not adjust a hex by eye. If a value seems wrong, re-run the validator and report.
- `just check` must pass before every commit. It is green at 173 tests.
- Commit messages end with:
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`
- No em dashes or double hyphens in prose. Use commas, colons or parentheses.

---

## File Structure

**Created:**
- `italy_dashboard/palette.py` — the four colour roles for both modes, as plain data. No Reflex import, so tests and the validator can read it directly.
- `tests/unit/test_palette.py` — runs the Node validator over `palette.py` and fails on any regression.
- `tests/unit/test_components.py` — render tests for the new chart helpers.

**Modified:**
- `italy_dashboard/theme.py` — mode-aware accessors over `palette.py`; existing constant names kept as light-mode values so nothing breaks mid-migration.
- `italy_dashboard/components.py` — new helpers: `stripe_chart`, `area_compare_chart`, `composed_bar_line_chart`, `small_multiples`; existing helpers gain reference lines, brush, styled tooltips.
- `italy_dashboard/pages/climate.py`, `climate_crime.py` — consume the new helpers.
- `italy_dashboard/queries.py` — `climate_stripes` gains a diverging bucket index.
- `italy_dashboard/translations.py` — new labels, EN and IT.
- `italy_dashboard/italy_dashboard.py` — app-level stylesheet for the CSS custom properties.
- `docs/06-dashboard.md`, `docs/11-roadmap.md`.

---

### Task 1: Palette module, mode-aware theme, and dark mode

This task establishes the mechanism every later task builds on. Do it first and do it carefully.

**Files:**
- Create: `italy_dashboard/palette.py`, `tests/unit/test_palette.py`
- Modify: `italy_dashboard/theme.py`, `italy_dashboard/components.py`, `italy_dashboard/italy_dashboard.py`

**Interfaces:**
- Produces: `palette.CATEGORICAL_LIGHT/DARK: tuple[str, ...]`, `palette.DIVERGING_LIGHT/DARK: tuple[str, ...]` (7 steps, cool to warm), `palette.SEQUENTIAL_LIGHT/DARK: tuple[str, ...]` (5 steps, pale to deep), `palette.SURFACE_LIGHT/DARK`, `palette.diverging_css_vars() -> str`.
- Produces: `theme.series(n: int) -> rx.Var` for n in 1..3, `theme.surface() -> rx.Var`, `theme.ink_primary()/ink_secondary()/ink_muted()/gridline()/axis()/border()`, all returning `rx.color_mode_cond` Vars.

- [ ] **Step 1: Write the failing palette test**

Create `tests/unit/test_palette.py`:

```python
"""The palette is machine-validated, not eyeballed.

These tests run the dataviz validator over the shipped values. A colour edit
that breaks colourblind separation, the lightness band or contrast fails here
rather than shipping.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from italy_dashboard import palette

VALIDATOR = Path(
    "/private/tmp/claude-501/bundled-skills/2.1.220/"
    "a98a95678ed18250c62d48f3cfa1dc2a/dataviz/scripts/validate_palette.js"
)

pytestmark = pytest.mark.skipif(
    not VALIDATOR.exists() or shutil.which("node") is None,
    reason="dataviz validator or node unavailable",
)


def _run(kind: str, colors: tuple[str, ...], mode: str, surface: str) -> dict:
    """Call the validator's validate()/validateOrdinal() and return its report."""
    script = f"""
    import {{ validate, validateOrdinal }} from "{VALIDATOR}";
    const fn = {"validateOrdinal" if kind == "ordinal" else "validate"};
    const res = fn({json.dumps(list(colors))}, {{mode: "{mode}", surface: "{surface}"}});
    console.log(JSON.stringify(res));
    """
    out = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return json.loads(out.stdout)


def _assert_no_failures(res: dict, label: str) -> None:
    failures = [r for r in res["report"] if r[1] is False or r[1] == "fail"]
    assert not failures, f"{label}: {failures}"


def test_categorical_light_passes():
    _assert_no_failures(
        _run("cat", palette.CATEGORICAL_LIGHT, "light", palette.SURFACE_LIGHT), "cat light"
    )


def test_categorical_dark_passes():
    _assert_no_failures(
        _run("cat", palette.CATEGORICAL_DARK, "dark", palette.SURFACE_DARK), "cat dark"
    )


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_diverging_arms_pass(mode: str):
    """Each arm is validated as a single-hue ramp, EXCLUDING the neutral midpoint.

    Including the midpoint would blow the single-hue check by design: a neutral
    gray is not the arms' hue. That is expected, not a failure.
    """
    steps = palette.DIVERGING_LIGHT if mode == "light" else palette.DIVERGING_DARK
    surface = palette.SURFACE_LIGHT if mode == "light" else palette.SURFACE_DARK
    cool = tuple(reversed(steps[:3]))  # pale -> deep
    warm = steps[4:]
    _assert_no_failures(_run("ordinal", cool, mode, surface), f"div {mode} cool")
    _assert_no_failures(_run("ordinal", warm, mode, surface), f"div {mode} warm")


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_sequential_passes(mode: str):
    steps = palette.SEQUENTIAL_LIGHT if mode == "light" else palette.SEQUENTIAL_DARK
    surface = palette.SURFACE_LIGHT if mode == "light" else palette.SURFACE_DARK
    _assert_no_failures(_run("ordinal", steps, mode, surface), f"seq {mode}")


def test_diverging_has_seven_steps_with_a_neutral_middle():
    for steps in (palette.DIVERGING_LIGHT, palette.DIVERGING_DARK):
        assert len(steps) == 7
        r, g, b = (int(steps[3][i : i + 2], 16) for i in (1, 3, 5))
        assert abs(r - g) <= 2 and abs(g - b) <= 2, f"midpoint {steps[3]} is not neutral"


def test_css_vars_cover_every_diverging_step():
    css = palette.diverging_css_vars()
    for i in range(7):
        assert f"--div-{i}:" in css
    assert ".dark" in css or "[data-theme" in css
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_palette.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'italy_dashboard.palette'`

- [ ] **Step 3: Write `italy_dashboard/palette.py`**

Values are copied verbatim from the spec. Every one was derived by search against the validator and verified independently. Do not adjust any of them by eye.

```python
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
    index = mid + int(round(anomaly / step))
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
```

- [ ] **Step 4: Run the palette tests**

Run: `uv run pytest tests/unit/test_palette.py -v`
Expected: all PASS. If any validator check fails, STOP and report the exact numbers. Do not adjust a hex to make a test pass.

- [ ] **Step 5: Make `theme.py` mode-aware**

Keep every existing constant name at its light value, so nothing breaks while callers migrate. Add accessors alongside.

```python
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
```

- [ ] **Step 6: Register the CSS custom properties and a mode toggle**

In `italy_dashboard/italy_dashboard.py`, pass the diverging variables as app-level style so `var(--div-N)` resolves:

```python
from italy_dashboard import palette

app = rx.App(
    style={},
    stylesheets=[],
)
app.add_page(...)  # existing pages unchanged
```

Reflex has no direct "raw CSS string" app argument in 0.9.8, so inject the block through a `rx.el.style` element in the shell instead. In `italy_dashboard/components.py`, inside `shell(...)`, add as the first child:

```python
        rx.el.style(palette.diverging_css_vars()),
```

Then add the mode toggle beside the language chips. In `components.py`, extend `navbar()` by inserting before `_lang_toggle()`:

```python
        rx.color_mode.button(size="1"),
```

- [ ] **Step 7: Verify the mechanism actually works**

This is the step that de-risks every later task. Run:

```bash
uv run pytest tests/integration/test_app_pages.py -v -m integration
just compile
```

Both must pass. Then confirm the CSS block reaches the rendered tree:

```bash
uv run python -c "
from italy_dashboard.pages.climate import climate_page
html = str(climate_page().render())
print('--div-0 present:', '--div-0' in html)
print('.dark block present:', '.dark' in html)
"
```

Expected: both `True`. If either is `False`, the custom properties are not reaching the page and the stripe chart in Task 2 cannot work. STOP and report rather than proceeding.

- [ ] **Step 8: Run the full check and commit**

Run: `just check`
Expected: green, 173 tests plus the new palette tests.

```bash
git add italy_dashboard/palette.py italy_dashboard/theme.py \
        italy_dashboard/components.py italy_dashboard/italy_dashboard.py \
        tests/unit/test_palette.py
git commit -m "feat: validated colour roles, mode-aware theme and dark mode

Four colour roles (categorical, diverging, sequential, neutral) across light
and dark, every value derived by search against the dataviz validator rather
than chosen by eye. Validation runs as a test so a future edit that breaks
colourblind separation fails the suite instead of shipping.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Warming stripes get their diverging encoding

The headline fix. The stripes currently render in one categorical hue, which is the wrong encoding for the form: colour is supposed to carry the value.

**Files:**
- Modify: `italy_dashboard/queries.py` (`climate_stripes`), `italy_dashboard/components.py`, `italy_dashboard/pages/climate.py`
- Test: `tests/unit/test_queries.py`, `tests/unit/test_components.py`

**Interfaces:**
- Consumes: `palette.diverging_bucket`, `palette.DIVERGING_STEPS`.
- Produces: `climate_stripes` rows gain `fill: str` (a `var(--div-N)` string); `components.stripe_chart(data, height=140) -> rx.Component`.

- [ ] **Step 1: Write the failing query test**

Append to `tests/unit/test_queries.py`:

```python
def test_climate_stripes_carry_a_diverging_fill(climate_db):
    rows = q.climate_stripes("Roma")
    if not rows:
        pytest.skip("no anomalies in this fixture: the CLINO guard nulls them")
    assert {"period", "anomaly", "fill"} == set(rows[0])
    for r in rows:
        assert r["fill"].startswith("var(--div-")
    # colour must track the value: the warmest year cannot share the coldest's step
    warmest = max(rows, key=lambda r: r["anomaly"])
    coldest = min(rows, key=lambda r: r["anomaly"])
    if warmest["anomaly"] > coldest["anomaly"]:
        assert warmest["fill"] != coldest["fill"]
```

- [ ] **Step 2: Write the failing bucket tests**

Append to `tests/unit/test_palette.py`:

```python
def test_diverging_bucket_maps_sign_to_the_right_arm():
    mid = palette.DIVERGING_STEPS // 2
    assert palette.diverging_bucket(0.0) == mid
    assert palette.diverging_bucket(-1.5) < mid
    assert palette.diverging_bucket(1.5) > mid


def test_diverging_bucket_clamps_instead_of_wrapping():
    assert palette.diverging_bucket(-99.0) == 0
    assert palette.diverging_bucket(99.0) == palette.DIVERGING_STEPS - 1


def test_diverging_bucket_is_monotonic():
    values = [palette.diverging_bucket(a / 10) for a in range(-40, 41)]
    assert values == sorted(values)


def test_diverging_bucket_rejects_a_non_positive_range():
    with pytest.raises(ValueError):
        palette.diverging_bucket(0.5, half_range=0)
```

- [ ] **Step 3: Run both to verify they fail**

Run: `uv run pytest tests/unit/test_palette.py tests/unit/test_queries.py -k "bucket or stripes" -v`
Expected: FAIL — `diverging_bucket` missing, and `climate_stripes` has no `fill` key.

- [ ] **Step 4: Add the fill to `climate_stripes`**

In `italy_dashboard/queries.py`, replace the body of `climate_stripes` with:

```python
def climate_stripes(city: str) -> list[Row]:
    """Anomaly against the 1981-2010 normal per year, with its diverging colour.

    The colour is the data here: warming stripes are a diverging encoding, so
    each bar carries its own step of the ramp. The fill is a CSS custom
    property rather than a hex, because a per-datum colour still has to follow
    the light/dark mode and cannot be a build-time constant.
    """
    rows = _query(
        f"""
        SELECT year AS period, anomaly_1981_2010 AS anomaly
        FROM {CLIMATE_ANNUAL}
        WHERE capital_city = ? AND anomaly_1981_2010 IS NOT NULL
        ORDER BY year
        """,
        [city],
    )
    for r in rows:
        r["fill"] = f"var(--div-{palette.diverging_bucket(float(r['anomaly']))})"
    return rows
```

Add `from italy_dashboard import palette` to the imports at the top of `queries.py`.

- [ ] **Step 5: Add the `stripe_chart` helper**

In `italy_dashboard/components.py`, after `bar_chart`:

```python
def stripe_chart(data: ChartData, height: int = 140) -> rx.Component:
    """Warming stripes: one bar per year, coloured by its own anomaly.

    Squat by design and axis-free apart from the year: the form's whole job is
    to be read as a colour field, and gridlines fight that. The table view in
    the surrounding card carries the exact numbers.
    """
    return rx.recharts.bar_chart(
        rx.recharts.bar(
            data_key="anomaly",
            fill=theme.series(1),
            is_animation_active=False,
            children=[
                rx.foreach(data, lambda row: rx.recharts.cell(fill=row["fill"])),
            ],
        ),
        _x_axis(),
        rx.recharts.graphing_tooltip(),
        data=data,
        bar_category_gap=0,
        width="100%",
        height=height,
        margin={"top": 4, "right": 8, "bottom": 4, "left": 8},
    )
```

If `rx.recharts.bar` rejects a `children=` keyword in this Reflex version, pass the `rx.foreach(...)` as a positional child of `rx.recharts.bar(...)` instead. Determine which form works and note it in your report.

- [ ] **Step 6: Use it on the climate page**

In `italy_dashboard/pages/climate.py`, replace the stripes card's `bar_chart(...)` call with:

```python
                    stripe_chart(ClimateState.stripes),
```

and add `stripe_chart` to the import from `italy_dashboard.components`. Add a `data_table` beneath it so the exact anomalies remain readable:

```python
                    data_table(
                        ClimateState.stripes,
                        [("period", t("year")), ("anomaly", t("anomaly"))],
                    ),
```

- [ ] **Step 7: Run the tests**

Run: `just check`
Expected: green. The stripes tests pass, and the page still renders.

- [ ] **Step 8: Verify the colours actually differ across bars**

```bash
uv run python -c "
from italy_dashboard import queries as q
rows = q.climate_stripes('Roma')
print('rows:', len(rows))
print('distinct fills:', sorted({r['fill'] for r in rows}))
"
```

Expected: more than one distinct fill. **If every bar has the same fill, the encoding has not been fixed** — report it rather than moving on. If the list is empty, the fixture's anomalies are NULL under the CLINO guard; say so explicitly.

- [ ] **Step 9: Commit**

```bash
git add italy_dashboard/queries.py italy_dashboard/components.py \
        italy_dashboard/pages/climate.py tests/unit/test_palette.py \
        tests/unit/test_queries.py
git commit -m "feat: warming stripes carry their diverging encoding

The stripes rendered in one categorical hue, which is the wrong encoding for
the form: colour is supposed to be the value. Each bar now takes its own step
of the validated diverging ramp, via a CSS custom property so the colour still
follows the light/dark mode.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Reference lines and baseline bands on anomaly charts

**Files:**
- Modify: `italy_dashboard/components.py`, `italy_dashboard/pages/climate.py`, `italy_dashboard/translations.py`
- Test: `tests/unit/test_components.py`

**Interfaces:**
- Produces: `components.line_chart(..., zero_line: bool = False, band: tuple[float, float] | None = None)`.

- [ ] **Step 1: Write the failing render test**

Create `tests/unit/test_components.py`:

```python
"""Render tests for chart helpers: a chart that will not build is a broken page."""

from __future__ import annotations

from italy_dashboard import components as c
from italy_dashboard import theme

ROWS = [
    {"period": "2000", "value": 1.0, "anomaly": -0.4, "early": 2.0, "late": 3.0},
    {"period": "2001", "value": 2.0, "anomaly": 0.6, "early": 1.0, "late": 4.0},
]


def test_line_chart_with_zero_line_and_band_builds():
    comp = c.line_chart(
        ROWS, [("value", "Value", theme.SERIES_1)], zero_line=True, band=(-0.2, 0.2)
    )
    assert comp.render()


def test_line_chart_without_extras_still_builds():
    assert c.line_chart(ROWS, [("value", "Value", theme.SERIES_1)]).render()


def test_multi_series_line_chart_has_a_legend():
    """Identity must never be colour-alone."""
    comp = c.line_chart(
        ROWS,
        [("early", "Early", theme.SERIES_1), ("late", "Late", theme.SERIES_2)],
    )
    assert "Legend" in str(comp.render())
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_components.py -v`
Expected: FAIL — `line_chart() got an unexpected keyword argument 'zero_line'`

- [ ] **Step 3: Extend `line_chart`**

In `italy_dashboard/components.py`, change the signature and body of `line_chart`:

```python
def line_chart(
    data: ChartData,
    series: list[tuple[str, str | rx.Var, str]],  # (data_key, label, color)
    height: int = 300,
    zero_line: bool = False,
    band: tuple[float, float] | None = None,
) -> rx.Component:
    """Line chart; legend shown only when there are >= 2 series.

    `zero_line` draws a reference line at y=0, which an anomaly chart needs so
    "above or below normal" is readable without tracing the axis. `band` shades
    a reference area, used for the CLINO baseline range.
    """
    lines = [
        rx.recharts.line(
            data_key=key,
            name=label,
            stroke=color,
            stroke_width=2,
            dot=False,
            type_="monotone",
        )
        for key, label, color in series
    ]
    extras: list[rx.Component] = []
    if band is not None:
        extras.append(
            rx.recharts.reference_area(
                y1=band[0], y2=band[1], fill=theme.gridline(), fill_opacity=0.55
            )
        )
    if zero_line:
        extras.append(rx.recharts.reference_line(y=0, stroke=theme.axis(), stroke_width=1))
    children = [*extras, *lines, _x_axis(), _y_axis(), _grid(), rx.recharts.graphing_tooltip()]
    if len(series) >= 2:
        children.append(rx.recharts.legend())
    return rx.recharts.line_chart(
        *children,
        data=data,
        width="100%",
        height=height,
        margin={"top": 8, "right": 8, "bottom": 4, "left": 8},
    )
```

Reference elements are added BEFORE the lines so they render underneath rather than over the data.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_components.py -v`
Expected: all PASS.

- [ ] **Step 5: Use the zero line on the climate page**

In `italy_dashboard/pages/climate.py`, the threshold-days card keeps its current call. No anomaly line chart exists yet on that page (stripes cover anomalies), so apply `zero_line=True` in Task 6's composed chart instead. For now, verify no regression:

Run: `just check`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add italy_dashboard/components.py tests/unit/test_components.py
git commit -m "feat: zero reference line and baseline band on line charts

An anomaly chart without a zero line makes the reader trace the axis to answer
its only question. Reference elements render beneath the data, never over it.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Distribution as overlapping areas with gradient fills

**Files:**
- Modify: `italy_dashboard/components.py`, `italy_dashboard/pages/climate.py`
- Test: `tests/unit/test_components.py`

**Interfaces:**
- Produces: `components.area_compare_chart(data, series, height=300) -> rx.Component` where `series` is `list[tuple[str, str | rx.Var, str]]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_components.py`:

```python
def test_area_compare_chart_builds_and_has_a_legend():
    comp = c.area_compare_chart(
        ROWS,
        [("early", "1951-1980", theme.SERIES_1), ("late", "1996-2025", theme.SERIES_2)],
    )
    rendered = str(comp.render())
    assert rendered
    assert "Legend" in rendered
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_components.py::test_area_compare_chart_builds_and_has_a_legend -v`
Expected: FAIL — `module 'italy_dashboard.components' has no attribute 'area_compare_chart'`

- [ ] **Step 3: Implement it**

In `italy_dashboard/components.py`, after `line_chart`:

```python
def area_compare_chart(
    data: ChartData,
    series: list[tuple[str, str | rx.Var, str]],  # (data_key, label, color)
    height: int = 300,
) -> rx.Component:
    """Two or more overlapping distributions as translucent areas.

    Areas beat lines for comparing distributions: the eye reads the shift in
    mass, not two thin squiggles. Fills stay translucent so the overlap region
    is visible rather than one series hiding another, and each area keeps a 2px
    stroke so its edge is legible where the fills coincide.
    """
    areas = [
        rx.recharts.area(
            data_key=key,
            name=label,
            stroke=color,
            stroke_width=2,
            fill=color,
            fill_opacity=0.28,
            type_="monotone",
            is_animation_active=False,
        )
        for key, label, color in series
    ]
    children = [*areas, _x_axis(), _y_axis(), _grid(), rx.recharts.graphing_tooltip()]
    if len(series) >= 2:
        children.append(rx.recharts.legend())
    return rx.recharts.area_chart(
        *children,
        data=data,
        width="100%",
        height=height,
        margin={"top": 8, "right": 8, "bottom": 4, "left": 8},
    )
```

- [ ] **Step 4: Run the test**

Run: `uv run pytest tests/unit/test_components.py -v`
Expected: all PASS.

- [ ] **Step 5: Use it for the distribution card**

In `italy_dashboard/pages/climate.py`, replace the distribution card's `line_chart(...)` with `area_compare_chart(...)`, keeping the same series tuples, and add `area_compare_chart` to the imports.

- [ ] **Step 6: Verify and commit**

Run: `just check`
Expected: green.

```bash
git add italy_dashboard/components.py italy_dashboard/pages/climate.py \
        tests/unit/test_components.py
git commit -m "feat: distribution shift as overlapping areas

Two thin lines make a distribution comparison hard to read. Translucent areas
show the shift in mass directly, with strokes so edges stay legible where the
fills overlap.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Polish pass — tooltips, brush, marks

**Files:**
- Modify: `italy_dashboard/components.py`
- Test: `tests/unit/test_components.py`

**Interfaces:**
- Produces: `components._tooltip() -> rx.Component` (styled), `components.line_chart(..., brush: bool = False)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_components.py`:

```python
def test_line_chart_with_brush_builds():
    assert c.line_chart(ROWS, [("value", "V", theme.SERIES_1)], brush=True).render()


def test_tooltip_is_styled_with_surface_tokens():
    """A default tooltip ignores the theme and breaks in dark mode."""
    rendered = str(c.line_chart(ROWS, [("value", "V", theme.SERIES_1)]).render())
    assert "contentStyle" in rendered or "content_style" in rendered
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_components.py -k "brush or tooltip" -v`
Expected: FAIL on the unexpected `brush` keyword.

- [ ] **Step 3: Add the styled tooltip and brush**

In `italy_dashboard/components.py`, add near the other private helpers:

```python
def _tooltip() -> rx.Component:
    """Tooltip wearing the surface and ink tokens.

    The default is a white box with a light border, which disappears against a
    dark surface. Styling it here means every chart inherits a correct one.
    """
    return rx.recharts.graphing_tooltip(
        content_style={
            "background": theme.surface(),
            "border": f"1px solid {theme.GRIDLINE}",
            "borderRadius": "8px",
            "fontSize": "12px",
            "color": theme.INK_PRIMARY,
        },
        cursor={"stroke": theme.AXIS, "strokeWidth": 1},
    )
```

Replace every bare `rx.recharts.graphing_tooltip()` in `line_chart`, `bar_chart`, `h_bar_chart`, `area_compare_chart` and `stripe_chart` with `_tooltip()`.

Then add the brush parameter to `line_chart`: add `brush: bool = False` to the signature, and before building the chart:

```python
if brush:
    children.append(
        rx.recharts.brush(
            data_key="period",
            height=24,
            stroke=theme.axis(),
            fill=theme.surface(),
        )
    )
```

- [ ] **Step 4: Verify**

Run: `just check`
Expected: green. If `content_style` is rejected by this Reflex version, use `custom_attrs={"contentStyle": {...}}` instead and note which form worked in your report.

- [ ] **Step 5: Commit**

```bash
git add italy_dashboard/components.py tests/unit/test_components.py
git commit -m "feat: styled tooltips and an optional brush

The default tooltip is a white box that vanishes on a dark surface. Styling it
once in the shared helper means every chart inherits a correct one.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Composed chart — threshold-day bars with a trend line

**Files:**
- Modify: `italy_dashboard/components.py`, `italy_dashboard/pages/climate.py`, `italy_dashboard/translations.py`
- Test: `tests/unit/test_components.py`

**Interfaces:**
- Produces: `components.composed_bar_line_chart(data, bar_key, bar_label, line_key, line_label, height=300) -> rx.Component`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_components.py`:

```python
def test_composed_bar_line_chart_builds_with_one_axis():
    comp = c.composed_bar_line_chart(
        ROWS, bar_key="value", bar_label="Hot days", line_key="early", line_label="Trend"
    )
    rendered = str(comp.render())
    assert rendered
    assert "Legend" in rendered
    # One y-axis only: a dual-axis chart is the single most common chart mistake.
    assert rendered.count("YAxis") == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_components.py -k composed -v`
Expected: FAIL — attribute missing.

- [ ] **Step 3: Implement it**

```python
def composed_bar_line_chart(
    data: ChartData,
    bar_key: str,
    bar_label: str | rx.Var,
    line_key: str,
    line_label: str | rx.Var,
    height: int = 300,
) -> rx.Component:
    """Counts as bars with a trend line over them, sharing ONE y-axis.

    Both measures must be on the same scale for this to be honest. A second
    y-scale is never the answer: it lets the author choose the story by choosing
    the scaling, which is why this helper does not offer one.
    """
    return rx.recharts.composed_chart(
        rx.recharts.bar(
            data_key=bar_key, name=bar_label, fill=theme.series(1), radius=[4, 4, 0, 0]
        ),
        rx.recharts.line(
            data_key=line_key,
            name=line_label,
            stroke=theme.series(2),
            stroke_width=2,
            dot=False,
            type_="monotone",
        ),
        _x_axis(),
        _y_axis(),
        _grid(),
        _tooltip(),
        rx.recharts.legend(),
        data=data,
        width="100%",
        height=height,
        margin={"top": 8, "right": 8, "bottom": 4, "left": 8},
    )
```

- [ ] **Step 4: Verify and commit**

Run: `just check`
Expected: green.

```bash
git add italy_dashboard/components.py tests/unit/test_components.py
git commit -m "feat: composed bar-and-line chart on a single axis

Deliberately offers no second y-scale: a dual axis lets the author pick the
story by picking the scaling.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Small multiples of warming stripes across cities

**Files:**
- Modify: `italy_dashboard/components.py`, `italy_dashboard/queries.py`, `italy_dashboard/state.py`, `italy_dashboard/pages/climate.py`, `italy_dashboard/translations.py`
- Test: `tests/unit/test_queries.py`, `tests/unit/test_components.py`

**Interfaces:**
- Produces: `queries.climate_stripes_grid(limit: int = 12) -> list[Row]` with keys `city` and `rows`; `components.small_multiples(items, height=90) -> rx.Component`.

- [ ] **Step 1: Write the failing query test**

Append to `tests/unit/test_queries.py`:

```python
def test_climate_stripes_grid_returns_one_entry_per_city(climate_db):
    grid = q.climate_stripes_grid(limit=6)
    if not grid:
        pytest.skip("no anomalies in this fixture: the CLINO guard nulls them")
    assert len(grid) <= 6
    assert {"city", "rows"} == set(grid[0])
    assert all(r["fill"].startswith("var(--div-") for r in grid[0]["rows"])
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_queries.py -k stripes_grid -v`
Expected: FAIL — attribute missing.

- [ ] **Step 3: Implement the query**

In `italy_dashboard/queries.py`:

```python
def climate_stripes_grid(limit: int = 12) -> list[Row]:
    """Stripes for several cities at once, for a small-multiples grid.

    Ordered by warming rate, fastest first, so the grid leads with the cities
    where the signal is strongest rather than with whatever sorts first
    alphabetically. Capped because a 106-panel grid is a wall, not a chart.
    """
    ranked = warming_rate_ranking(top_n=limit)
    return [
        {"city": r["name"], "rows": climate_stripes(r["name"])}
        for r in ranked
        if climate_stripes(r["name"])
    ]
```

- [ ] **Step 4: Implement the component**

In `italy_dashboard/components.py`:

```python
def small_multiples(items: rx.Var | list, height: int = 90) -> rx.Component:
    """A grid of stripe charts, one per city, on a shared colour scale.

    Small multiples work because every panel shares the scale: the reader
    compares panels, not axes. Panels are deliberately small and label-light;
    the card's table view carries exact values.
    """
    return rx.grid(
        rx.foreach(
            items,
            lambda item: rx.vstack(
                rx.text(item["city"], font_size="0.75em", color=theme.ink_secondary()),
                stripe_chart(item["rows"], height=height),
                spacing="1",
                width="100%",
            ),
        ),
        columns="3",
        spacing="4",
        width="100%",
    )
```

- [ ] **Step 5: Wire it into state and the page**

In `italy_dashboard/state.py`, add to `ClimateState`:

```python
    stripes_grid: list[Row] = []
```

and inside `load`, after `self.ranking = ...`:

```python
        self.stripes_grid = q.climate_stripes_grid(limit=12)
```

In `italy_dashboard/pages/climate.py`, add a card after the stripes card:

```python
                card(
                    t("grid_title"),
                    t("grid_sub"),
                    small_multiples(ClimateState.stripes_grid),
                ),
```

Add `small_multiples` to the imports. Add to `translations.py`, EN:

```python
    "grid_title": "Warming stripes across cities",
    "grid_sub": "Fastest-warming capitals, same colour scale in every panel",
```

and IT:

```python
    "grid_title": "Strisce del riscaldamento per città",
    "grid_sub": "Capoluoghi che si scaldano più in fretta, stessa scala di colore in ogni pannello",
```

- [ ] **Step 6: Verify translation parity and commit**

```bash
uv run python -c "
from italy_dashboard.translations import EN, IT
print('EN', len(EN), 'IT', len(IT), 'asymmetry:', sorted(set(EN) ^ set(IT)) or 'none')
"
just check
```

Expected: zero asymmetry, `just check` green.

```bash
git add italy_dashboard/ tests/unit/test_queries.py tests/unit/test_components.py
git commit -m "feat: small multiples of warming stripes across cities

One panel per capital on a shared colour scale, ordered by warming rate. The
only view that makes many cities legible at once.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Documentation

**Files:**
- Modify: `docs/06-dashboard.md`, `docs/11-roadmap.md`

- [ ] **Step 1: Document the palette and encodings in `docs/06-dashboard.md`**

Add a section covering: the four colour roles and that every value is machine-validated with the validation running as a test; that warming stripes are a diverging encoding where colour is the value; that dark-mode steps are selected against the dark surface rather than inverted; and that per-datum colours resolve through CSS custom properties because they cannot be build-time constants.

State plainly that the month-by-year heatmap remains absent because Recharts has no heatmap mark.

- [ ] **Step 2: Update `docs/11-roadmap.md`**

Remove the "Dark mode" entry, which is now done. Keep the heatmap entry and note that it needs a charting library with a heatmap mark, not more Recharts work.

- [ ] **Step 3: Verify the docs build and commit**

```bash
uv run zensical build
```
Expected: no issues.

```bash
git add docs/
git commit -m "docs: palette roles, chart encodings and dark mode

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage.** Palette and its validation-as-test: Task 1. Right encodings: Task 2 (stripes), Task 3 (reference lines and band), Task 4 (distribution areas), Task 5 (brush). Polish: Task 5 (tooltips, marks). Richer forms: Task 6 (composed), Task 7 (small multiples). Dark mode: Task 1. Testing: distributed, with the palette validator wired into the suite in Task 1. Docs: Task 8.

**Known risks, stated rather than hidden.**
1. The `rx.recharts.cell` child form inside `rx.recharts.bar` is the one API shape I could not confirm from the installed version. Task 2 Step 5 gives both candidate forms and requires the implementer to report which worked. If neither does, the stripe encoding needs a different mechanism and that is a STOP-and-report, not a workaround.
2. Task 1 Step 7 exists precisely because the CSS custom property mechanism is load-bearing for Task 2 and unproven. It fails loudly before five tasks are built on top.
3. `content_style` on the tooltip may need `custom_attrs` instead; Task 5 Step 4 says so and asks which form worked.

**Type consistency.** `theme.series(n)` is 1-based throughout. `palette.diverging_bucket` returns `0..DIVERGING_STEPS-1`, and `climate_stripes` turns that into `var(--div-N)` with the same N. `climate_stripes_grid` returns `{"city", "rows"}` and `small_multiples` reads exactly those keys.

**Ordering.** Task 1 must land first: every later task consumes its accessors, and Task 2 consumes its CSS variables.
