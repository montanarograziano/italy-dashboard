# Static App Shell and Climate Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A deployed static site on Netlify showing the climate page, built on the already-verified TypeScript query layer, with the chart primitives and app shell the remaining six pages will reuse.

**Architecture:** React + Vite reads `shared/palette.json` for colour and calls the ported query functions in `web/src/queries/`, which run DuckDB-WASM against parquet fetched over HTTP range requests. Charts are Observable Plot, chosen for faceting and its `cell` mark. One page ships end to end — including deployment — before six more are built on assumptions about the pipeline.

**Tech Stack:** React 19, Vite 7, TypeScript 5 (strict, `noUncheckedIndexedAccess`), `@observablehq/plot`, `@duckdb/duckdb-wasm` 1.29, Netlify.

**Spec:** `docs/superpowers/specs/2026-08-17-static-netlify-port-design.md`

## Global Constraints

- **Visual parity with the Reflex app is explicitly NOT a goal.** The two frontends share data and colour, not chart implementations. The spec lifted parity as a constraint deliberately; do not reintroduce it.
- **`shared/palette.json` and `shared/palette.css` are the only source of colour.** Nothing in `web/` hardcodes a hex value. Both files are generated from `italy_dashboard/palette.py` and a test asserts they match it.
- **Do not edit `shared/conformance/expected.json`**, and do not change any function in `web/src/queries/`. That layer is verified against Python by 53 conformance cases; a UI need that seems to require changing it is a signal to add a new function, not to edit a verified one.
- All 53 conformance cases must keep passing: `just test-conformance` (7 tests).
- `uv run pytest -q` must stay green (408 tests), `npm --prefix web run typecheck` clean.
- The deployed bundle must not contain `data/raw`, `data/dbt.duckdb`, or `data/weather_daily.parquet`.
- Do not commit `web/node_modules/` or `web/dist/`.

---

## The two facts that shape this plan

**1. `publicDir` currently points at the entire `data/` directory.** `web/vite.config.ts` sets `publicDir: resolve(__dirname, "..", "data")`. Measured on this machine:

| | size |
|---|---|
| `data/` in full (what a **local** build copies) | **843 MB** |
| git-tracked files under `data/` (what **Netlify** has) | **14 MB** |
| `data/raw` + `data/dbt.duckdb` + `data/weather_daily.parquet` | 829 MB, none tracked |

So a local `npm run build` and a Netlify build copy wildly different things, and the local one would publish an 800 MB scratch cache. Task 4 replaces this with an explicit allowlist. This is not a hypothetical tidy-up: it is the difference between a build that works in CI and one that works on the machine of whoever tries it next.

**2. `mart_climate_daily.parquet` is 10 MB of the 14 MB tracked.** The spec excludes it from the static deploy and precomputes its one chart's data at build time. Excluding it drops the payload by **71%**. The query layer already tolerates its absence — `registerParquetViews` skips a missing file, records the name, and still fails loudly on a query that needs it (`web/src/db.ts`).

---

## File Structure

| File | Responsibility |
|---|---|
| `web/src/index.html` | Vite entry. `root` is `web/src`, so it must live here, not at `web/`. Its absence is why `npm run build` currently fails. |
| `web/src/main.tsx` | React bootstrap, mounts `<App/>`. |
| `web/src/App.tsx` | Shell: header, nav, colour-mode toggle, page slot. |
| `web/src/theme.ts` | Reads `shared/palette.json`; exports colour accessors and the active mode. The only module that touches palette data. |
| `web/src/theme.css` | Imports `shared/palette.css`; layout and typography. |
| `web/src/charts/plot.tsx` | One React wrapper that renders an Observable Plot spec into a ref and cleans up. Every chart uses it. |
| `web/src/charts/climate.tsx` | The climate page's chart builders: band trend, stripes, faceted stripes, distribution, threshold bars, ranking, month heatmap. |
| `web/src/pages/Climate.tsx` | Scope cascade state, calls the ported queries, composes the charts. |
| `web/vite.config.ts` | **Modify:** explicit data allowlist replacing the blanket `publicDir`. |
| `netlify.toml` | **Create:** build command, publish dir, the data copy step. |
| `tests/browser/test_static_app.py` | **Create:** Playwright assertions against the built site. |

---

### Task 1: App shell and theme

**Files:**
- Create: `web/src/index.html`, `web/src/main.tsx`, `web/src/App.tsx`, `web/src/theme.ts`, `web/src/theme.css`
- Modify: `web/package.json` (add `react`, `react-dom`, `@observablehq/plot`, `@vitejs/plugin-react`), `web/vite.config.ts` (add the React plugin)
- Test: `tests/browser/test_static_app.py`

**Interfaces:**
- Consumes: `shared/palette.json`.
- Produces: from `web/src/theme.ts` —
  - `type Mode = "light" | "dark"`
  - `currentMode(): Mode` — reads `data-theme` on `<html>`, falling back to `prefers-color-scheme`
  - `series(n: number): string` — nth categorical colour, wrapping
  - `divergingSteps(): string[]` — the seven diverging steps
  - `sequentialSteps(): string[]` — the five sequential steps
  - `surface(): string`, `inkPrimary(): string`, `inkSecondary(): string`, `inkMuted(): string`, `gridline(): string` — names mirror `italy_dashboard/theme.py`'s `surface`, `ink_primary`, `ink_secondary`, `ink_muted`, `gridline` in camelCase, so the two frontends' accessors are recognisably the same set

- [ ] **Step 1: Install the dependencies**

```bash
cd web && npm install react react-dom @observablehq/plot && npm install -D @vitejs/plugin-react @types/react @types/react-dom
```

- [ ] **Step 2: Write `theme.ts` against the real palette**

`shared/palette.json` has exactly these keys, each with `light` and `dark` arrays:

```json
{
  "surface":     {"light": "#fcfcfb", "dark": "#1a1a19"},
  "categorical": {"light": ["#2a78d6", "#eb6834", "#1baf7a"], "dark": ["#2072d0", "#de5c27", "#00995f"]},
  "diverging":   {"light": [7 hexes], "dark": [7 hexes]},
  "sequential":  {"light": [5 hexes], "dark": [5 hexes]}
}
```

```typescript
// web/src/theme.ts
import palette from "../../shared/palette.json";

export type Mode = "light" | "dark";

/** The mode the page is actually rendering in.
 *
 * Three states, matching how the artifact viewer and the Reflex app both
 * behave: an explicit choice sets `data-theme` on <html>, and the default
 * "system" setting sets nothing, leaving `prefers-color-scheme` to decide.
 */
export function currentMode(): Mode {
  const explicit = document.documentElement.dataset.theme;
  if (explicit === "light" || explicit === "dark") return explicit;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function series(n: number): string {
  const scale = palette.categorical[currentMode()];
  return scale[n % scale.length]!;
}

export function divergingSteps(): string[] {
  return palette.diverging[currentMode()];
}

export function sequentialSteps(): string[] {
  return palette.sequential[currentMode()];
}

export function surface(): string {
  return palette.surface[currentMode()];
}
```

`inkPrimary()`, `inkSecondary()`, `inkMuted()` and `gridline()` are not in `palette.json` — they live in `italy_dashboard/theme.py` as derived values. Read that file and either add them to the generator (preferred, so both frontends share them) or derive them here with a comment saying why they are not shared. **If you add them to `scripts/generate_palette.py`, you must regenerate both artifacts and the equality test will hold you to it.**

- [ ] **Step 3: Write `index.html` and mount React**

`web/vite.config.ts` sets `root: web/src`, so the entry is `web/src/index.html`. Import `shared/palette.css` so the `--div-*` custom properties are available.

- [ ] **Step 4: Add the colour-mode toggle**

Setting `data-theme` on `<html>` and persisting the choice. The three-state behaviour above means the toggle must be able to return to "system", not just flip between two.

- [ ] **Step 5: Write the failing browser test**

```python
# tests/browser/test_static_app.py
import pytest

pytestmark = pytest.mark.browser


def test_the_shell_paints_the_palette_surface(page, static_app):
    """The page background must come from shared/palette.json, not a CSS default.

    A page that renders with the browser's default white looks fine in light
    mode and wrong in dark mode, and nothing else in this suite would notice.
    """
    page.goto(static_app)
    background = page.evaluate(
        "() => getComputedStyle(document.body).backgroundColor"
    )
    assert background == "rgb(252, 252, 251)", background  # palette surface.light
```

**`static_app` does not exist yet — you are creating it.** `tests/browser/conftest.py` has a session-scoped `app_server` fixture, but it serves the **Reflex** app, not this one; reusing it would point every assertion in this file at the wrong site and they would fail in confusing ways. Add a sibling session-scoped fixture that starts Vite against `web/` and yields its URL, modelled on `app_server` and on how `test_conformance.py` drives the harness. `test_conformance.py` also shows the right way to get a browser: take pytest-playwright's session `browser` fixture rather than constructing `sync_playwright()` yourself, which errors under `-m browser` (the Sync API cannot run inside the asyncio loop).

- [ ] **Step 6: Run it to verify it fails, then passes**

Run: `uv run pytest -m browser -q`
Expected: FAIL first (no `index.html`), PASS after Steps 3-4.

- [ ] **Step 7: Verify the assertion discriminates**

Change the body background to a hardcoded `#ffffff`.
Run: `uv run pytest -m browser -q`
Expected: **FAIL**, showing `rgb(255, 255, 255)`.

Restore. Report the observed failure.

- [ ] **Step 8: Commit**

```bash
git add web/src web/package.json web/package-lock.json web/vite.config.ts tests/browser/test_static_app.py
git commit -m "feat(web): app shell reading colour from the shared palette"
```

---

### Task 2: Chart primitives in Observable Plot

**Files:**
- Create: `web/src/charts/plot.tsx`, `web/src/charts/climate.tsx`
- Test: `tests/browser/test_static_app.py`

**Interfaces:**
- Consumes: `theme.ts`'s accessors.
- Produces:
  - `<PlotFigure spec={...} />` from `plot.tsx` — renders an Observable Plot spec into a ref, replacing the node on change and cleaning up on unmount
  - From `climate.tsx`: `bandTrendSpec(rows)`, `stripesSpec(rows)`, `facetedStripesSpec(rows)`, `distributionSpec(rows, windows)`, `thresholdSpec(rows)`, `rankingSpec(rows, highlight)`, `monthHeatmapSpec(rows)`

- [ ] **Step 1: Write the Plot wrapper**

```tsx
// web/src/charts/plot.tsx
import * as Plot from "@observablehq/plot";
import { useEffect, useRef } from "react";

/** Renders an Observable Plot spec into a div.
 *
 * Plot returns a detached DOM node rather than React elements, so this is the
 * one place in the app that touches the DOM directly. Replacing rather than
 * appending matters: Plot has no update path, and appending on every render
 * silently stacks charts on top of each other.
 */
export function PlotFigure({ spec }: { spec: Plot.PlotOptions }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const chart = Plot.plot(spec);
    node.replaceChildren(chart);
    return () => chart.remove();
  }, [spec]);
  return <div ref={ref} />;
}
```

Note the `[spec]` dependency: a spec rebuilt inline on every render is a new object each time and will re-render the chart constantly. Memoise specs at the call site.

- [ ] **Step 2: Build the seven climate chart specs**

Each is a pure function from ported-query rows to a Plot spec. Colour comes only from `theme.ts`.

Two that carry real requirements:

- **`facetedStripesSpec`** is the reason Observable Plot was chosen over Recharts. The Reflex app assembles its small-multiples grid by hand from twelve individual charts; here it is one mark with an `fx` channel.
- **`monthHeatmapSpec`** uses Plot's `cell` mark, which Recharts has no equivalent of at all — this chart does not exist in the Reflex app and is the clearest thing the static build offers that the canonical one cannot. `climate_month_heatmap` returns 924 cells for Torino including 4 nulls, all in the partial 2026 year. **Nulls must render as absent cells, not as zero** — a zero reads as "no anomaly", which is a claim about the climate rather than about the data.

- [ ] **Step 3: Write the failing test for diverging colour**

```python
def test_the_stripes_resolve_to_distinct_diverging_colours(page, static_app):
    """Warming stripes must use the diverging scale, and adjacent buckets must
    be visually distinct.

    Asserting "a fill exists" would pass on a chart drawn entirely in one
    colour, which is the failure mode that actually happens when a scale is
    misconfigured.
    """
    page.goto(static_app)
    page.wait_for_selector("[data-testid='climate-stripes'] rect")
    fills = page.eval_on_selector_all(
        "[data-testid='climate-stripes'] rect",
        "els => [...new Set(els.map(e => getComputedStyle(e).fill))]",
    )
    assert len(fills) >= 4, fills
```

- [ ] **Step 4: Run it, implement, run again**

Run: `uv run pytest -m browser -q`
Expected: FAIL, then PASS.

- [ ] **Step 5: Verify it discriminates**

Make `stripesSpec` return a constant fill.
Run: `uv run pytest -m browser -q`
Expected: **FAIL** with one colour in the set.

Restore. Report what you observed.

- [ ] **Step 6: Commit**

```bash
git add web/src/charts tests/browser/test_static_app.py
git commit -m "feat(web): Observable Plot chart primitives"
```

---

### Task 3: The climate page

**Files:**
- Create: `web/src/pages/Climate.tsx`
- Modify: `web/src/App.tsx`
- Test: `tests/browser/test_static_app.py`

**Interfaces:**
- Consumes: every function in `web/src/queries/climate.ts` and `climateScope.ts`; the specs from Task 2.
- Produces: a rendered page. No exports other than the component.

- [ ] **Step 1: Read the Reflex page for the information architecture, not the styling**

`italy_dashboard/pages/climate.py` is the reference for *what is shown and how it is grouped*, which was restructured recently after review: an `Italia → region → city` scope cascade, a "Selected scope" section, and an "Across Italy" section holding the cross-city ranking and the stripes grid.

Two behaviours from that restructure are correctness requirements, not styling:

1. **The cross-city ranking and stripes grid are NOT filtered by the selected city.** They acknowledge the selection with an outline and a ring. Filtering a ranking to one city destroys the thing a ranking is.
2. **When the selected city is in neither the ranking nor the grid, say so.** 30 of 50 capitals are in neither, so without this 60% of city selections produce no visible signal anywhere and the page looks broken.

**Do not copy the Reflex styling.** Visual parity is not a goal; the information architecture is what carries over.

- [ ] **Step 2: Wire the scope cascade**

`climateRegionOptions()` returns 13 entries including `'Italia'`. `climateCityOptions(region)` returns `'All'` first, then the region's cities. **These take display names, not codes** — passing a code returns zero rows rather than raising.

- [ ] **Step 3: Handle the loading and empty states honestly**

Queries are async and DuckDB-WASM's first load pulls 3-5 MB of wasm before any data. A page that renders empty charts during that window is claiming "no data" when it means "not yet" — the Reflex app had exactly this bug and it was fixed by adding a distinct third state. Do the same here: loading, ready-and-empty, ready-with-data are three different things.

The distribution card in particular has no data at Italia scope, which is the **default landing view**, so its empty state is what most visitors see first and must explain itself rather than render a blank chart.

- [ ] **Step 4: Add the coverage note**

The Italia average is an unweighted mean of the capitals covered so far, and the backfill fills in province-code order — from the north. 50 of 106 capitals, 36 of them in four northern regions, the whole Mezzogiorno absent except Bari. The Reflex app states this at Italia scope; the static app must too, because a northern-weighted mean presented as national is a wrong number.

`italy_dashboard/translations.py` holds the wording under `climate_coverage_note` (EN and IT). Reuse the English text; this app is English-only for now.

- [ ] **Step 5: Write the failing test**

```python
def test_the_climate_page_renders_data_not_an_empty_state(page, static_app):
    """The default landing view must reach real data, not sit on a spinner.

    Asserting the page merely 'loaded' would pass while every chart is empty,
    which is what a broken parquet path looks like.
    """
    page.goto(static_app)
    page.wait_for_selector("[data-testid='climate-annual'] path", timeout=30_000)
    marks = page.eval_on_selector_all(
        "[data-testid='climate-annual'] path", "els => els.length"
    )
    assert marks > 0, "no marks drawn in the annual series chart"
```

The 30-second timeout is deliberate: DuckDB-WASM's cold start is slow and a shorter timeout makes this test flaky rather than strict.

- [ ] **Step 6: Run it, implement, run again**

Run: `uv run pytest -m browser -q`
Expected: FAIL, then PASS.

- [ ] **Step 7: Verify the page reads real data**

Point `climateAnnualSeries`'s call site at a city that does not exist (`"Atlantis"`).
Run: `uv run pytest -m browser -q`
Expected: **FAIL** — no marks, because the query legitimately returns `[]`.

Restore. Report the observed failure. This is the check that separates "the page rendered" from "the page rendered *data*".

- [ ] **Step 8: Commit**

```bash
git add web/src/pages web/src/App.tsx tests/browser/test_static_app.py
git commit -m "feat(web): the climate page"
```

---

### Task 4: Data allowlist and the production build

This task fixes the `publicDir` hazard and makes `npm run build` produce a correct, small bundle.

**Files:**
- Modify: `web/vite.config.ts`, `web/package.json`
- Create: `scripts/stage_web_data.py`
- Test: `tests/unit/test_web_build_inputs.py`

**Interfaces:**
- Consumes: the git-tracked parquet under `data/`.
- Produces: a staging directory Vite publishes, containing only the datasets the static app queries.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_web_build_inputs.py
"""The static build must ship the datasets it queries and nothing else.

`publicDir` used to point at all of `data/`, which is 843 MB locally and 14 MB
on a fresh clone -- so a local build and a CI build published different things,
and the local one shipped an 800 MB scratch cache. The allowlist is derived
from what the TypeScript actually registers, so it cannot drift from the app.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_TS = REPO_ROOT / "web" / "src" / "db.ts"

# 10 MB of the 14 MB tracked, for one chart. The spec excludes it from the
# static deploy and precomputes that chart's data at build time instead.
EXCLUDED_FROM_STATIC_BUILD = {"marts/mart_climate_daily"}


def _registered_paths() -> set[str]:
    body = re.search(r"const PARQUET = \[(.*?)\]", DB_TS.read_text(), re.S)
    assert body, "could not find the PARQUET list in db.ts"
    return set(re.findall(r'"([^"]+)"', body.group(1)))


def test_the_staged_data_matches_what_the_app_registers():
    from scripts.stage_web_data import STAGED

    assert STAGED == _registered_paths() - EXCLUDED_FROM_STATIC_BUILD


def test_no_scratch_data_is_staged():
    from scripts.stage_web_data import STAGED

    forbidden = [p for p in STAGED if "raw" in p or p.endswith("dbt.duckdb") or "weather_daily" in p]
    assert not forbidden, forbidden
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_web_build_inputs.py -q`
Expected: FAIL with `ModuleNotFoundError: scripts.stage_web_data`.

- [ ] **Step 3: Write the staging script**

`scripts/stage_web_data.py` exports `STAGED: set[str]` and copies those parquet files into a staging directory. Derive `STAGED` from `db.ts`'s `PARQUET` list minus the exclusion, so the two cannot drift.

- [ ] **Step 4: Point Vite at the staging directory**

Replace `publicDir: resolve(__dirname, "..", "data")` with the staging directory. The conformance harness also reads parquet over HTTP through this path, so **run `just test-conformance` after this change** — if the harness can no longer find its data, the allowlist is wrong.

`mart_climate_daily` is excluded, so `climateDistribution` will now fail in the browser. That is correct and already handled: `registerParquetViews` skips the absent file and records it, other queries are unaffected, and a query needing it fails loudly. Task 3's distribution card must show its explanatory empty state rather than an error.

- [ ] **Step 5: Run the tests and the build**

Run: `uv run pytest tests/unit/test_web_build_inputs.py -q && npm --prefix web run build`
Expected: PASS, and a `web/dist` well under 10 MB.

Report the actual `du -sh web/dist`.

- [ ] **Step 6: Verify the guard discriminates**

Add `"marts/mart_climate_daily"` back into `STAGED`.
Run: `uv run pytest tests/unit/test_web_build_inputs.py -q`
Expected: **FAIL** on the first test.

Restore. Report the observed failure.

- [ ] **Step 7: Commit**

```bash
git add web/vite.config.ts web/package.json scripts/stage_web_data.py tests/unit/test_web_build_inputs.py
git commit -m "build(web): stage only the data the static app queries"
```

---

### Task 5: Netlify deployment

**Files:**
- Create: `netlify.toml`
- Modify: `docs/12-deployment.md`
- Test: manual verification against the deployed URL

**Interfaces:**
- Consumes: Task 4's staging script and build.
- Produces: a live static site.

- [ ] **Step 1: Write `netlify.toml`**

```toml
[build]
  command = "uv run python scripts/stage_web_data.py && npm --prefix web ci && npm --prefix web run build"
  publish = "web/dist"

[build.environment]
  NODE_VERSION = "22"
```

Check whether Netlify's build image provides `uv`; if not, the staging step needs a `pip install uv` or a plain-Python fallback. **Verify this rather than assuming** — a build command that works locally and not on Netlify is the single most likely failure here.

- [ ] **Step 2: Confirm the headers DuckDB-WASM needs**

DuckDB-WASM may require `Cross-Origin-Opener-Policy` and `Cross-Origin-Embedder-Policy` headers for its threaded bundle. The app currently selects a bundle via `duckdb.selectBundle`, which falls back to a non-threaded build when those headers are absent.

Determine which bundle is actually selected in a deployed context and add the headers only if the threaded one is needed. **Do not add COEP speculatively** — it blocks cross-origin resources, and this page loads its wasm from jsDelivr.

- [ ] **Step 3: Deploy and verify against the live URL**

Confirm on the deployed site: the climate page renders real data, the colour-mode toggle works, the distribution card shows its explanatory empty state (`mart_climate_daily` is deliberately absent), and no request 404s except that one dataset.

Report the deployed URL and the observed first-load time — DuckDB-WASM is 3-5 MB before any data, and the real number matters for the next plan.

- [ ] **Step 4: Update the deployment documentation**

`docs/12-deployment.md` documents the Render deployment. Add the Netlify one beside it: what builds, what data ships, what is deliberately excluded and why, and that Render remains canonical.

- [ ] **Step 5: Commit**

```bash
git add netlify.toml docs/12-deployment.md
git commit -m "feat(deploy): publish the static app to Netlify"
```

---

## Self-Review

**Spec coverage.** "Charts" (Observable Plot, faceting, the `cell` mark) is Tasks 2-3. "Data delivery" including the documented `mart_climate_daily` exception is Task 4. "Deployment" is Task 5. "Palette as a generated artifact" is Task 1, which is the first real consumer of `palette.json` — until now it existed only to be checked by its own equality test.

**Deliberate deviation from the spec's decomposition.** The spec orders the work as "the static app" then "deployment". This plan folds deployment in beside a single page instead, because deployment risk discovered after six pages are built is expensive and discovered after one is cheap. The remaining six pages become the next plan, built on a pipeline already proven live.

**Out of scope.** The other six pages; the month heatmap is included here only because it is a climate chart and the spec names it as the thing the static app can draw and Reflex cannot.

**Known gap.** The precomputed JSON for the distribution chart, which the spec describes as the replacement for shipping `mart_climate_daily`, is **not** built in this plan. Task 3 shows the explanatory empty state instead and Task 4 records the exclusion. Precomputing it is a small task worth doing once there is a second consumer of build-time derived data; doing it now would build a build-time data pipeline for exactly one chart.

**Untestable by this plan.** Whether Netlify's build image provides `uv`, and which DuckDB-WASM bundle is selected in a deployed context. Both are flagged in Task 5 as things to verify rather than assume, because both are the kind of thing that only fails in the real environment.
