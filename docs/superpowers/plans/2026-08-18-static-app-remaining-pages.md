# Static App Remaining Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The remaining six pages of the static app — home, economy, labor, population, crime, climate×crime — reaching parity of information with the Reflex app, navigable, and deployed.

**Architecture:** Each page calls the already-ported and conformance-verified query functions in `web/src/queries/` and renders Observable Plot specs through the existing `PlotFigure` wrapper, reusing `theme.ts` for colour. Navigation is hash-based, deliberately, so no server rewrite rule is needed.

**Tech Stack:** React 19, Vite 7, TypeScript 5 (strict, `noUncheckedIndexedAccess`), `@observablehq/plot`, `@duckdb/duckdb-wasm` 1.29, Netlify.

**Spec:** `docs/superpowers/specs/2026-08-17-static-netlify-port-design.md`

## Global Constraints

- **Visual parity with the Reflex app is explicitly NOT a goal.** The two frontends share data and colour, not chart implementations. The Reflex pages are the reference for *what is shown and how it is grouped*, never for styling.
- **`shared/palette.json` / `palette.css` are the only source of colour.** Nothing in `web/` hardcodes a hex value.
- **Do not modify anything under `web/src/queries/`.** That layer is verified against Python by 53 conformance cases; a UI need that seems to require changing a query function is a signal to add one, not to edit a verified one. Do not edit `shared/conformance/expected.json`.
- **Every caveat on a Reflex page is a correctness requirement, not decoration.** Where a page states a limitation of the data, the static page states it too. The English copy lives in `italy_dashboard/translations.py`; reuse it verbatim.
- `uv run pytest -q` green (414), `uv run pytest -m browser -q` green (20 at start), `just test-conformance` green (8), `npm --prefix web run typecheck` clean.
- Do not commit `web/node_modules/`, `web/dist/`, or `web/public-data/`.

---

## The routing decision, and why the obvious choice is wrong

The app currently has **no navigation at all** — zero `<a>` elements, one page. Six more need reaching.

The reflex is to use real paths (`/crime`) plus the standard Netlify SPA rule:

```toml
[[redirects]]
  from = "/*"
  to = "/index.html"
  status = 200
```

**Do not do this.** That catch-all would also swallow the request for `mart_climate_daily.parquet`, which is **deliberately absent** from this build and whose 404 is load-bearing: `registerParquetViews` (`web/src/db.ts`) relies on that request failing to record the dataset as unavailable, which is what lets the distribution card explain itself instead of erroring, and what the conformance harness's `__excluded_from_static_build__` tagging keys on. With a catch-all, DuckDB would receive **200 OK and an HTML document** where it expected a parquet or a 404 — turning a handled absence into a parse error, on the default landing view.

A scoped redirect excluding `/marts/*` and `/*.parquet` would work, but redirect rules are order-sensitive and this one would be a silent trap for whoever edits it next.

**Use hash routing** (`#/crime`). No server configuration, no rewrite rules, no interaction with the data-fetch 404 semantics, and it cannot be broken by a future edit to `netlify.toml`. The cost is a `#` in the URL, which is the cheapest thing being traded here.

---

## File Structure

| File | Responsibility |
|---|---|
| `web/src/router.tsx` | Hash router: parses `location.hash`, listens for `hashchange`, exposes the active route. |
| `web/src/App.tsx` | **Modify:** nav links, route switch, keeps the existing colour-mode toggle. |
| `web/src/pages/Home.tsx` | Landing page. No charts (the Reflex `home.py` has none). |
| `web/src/pages/Economy.tsx` | Inflation series. 1 chart. |
| `web/src/pages/Labor.tsx` | Unemployment series. 1 chart. |
| `web/src/pages/Population.tsx` | Resident and foreign population. 2 charts. |
| `web/src/pages/Crime.tsx` | The dimension-filtered crime and offenders page. 11 charts — the largest by far. |
| `web/src/pages/ClimateCrime.tsx` | The two-panel heat/offending comparison. 2 charts, and the heaviest caveats in the project. |
| `web/src/charts/series.tsx` | Shared specs for the simple time-series shapes Tasks 2-4 reuse. |
| `tests/browser/test_static_app.py` | **Modify:** per-page assertions. |

---

### Task 1: Hash router, nav, and the home page

**Files:**
- Create: `web/src/router.tsx`, `web/src/pages/Home.tsx`
- Modify: `web/src/App.tsx`, `tests/browser/test_static_app.py`

**Interfaces:**
- Produces: `useRoute(): string` from `router.tsx` — the active route slug, defaulting to `"home"`; `ROUTES: readonly {slug: string; label: string}[]`.

- [ ] **Step 1: Read the Reflex home page**

`italy_dashboard/pages/home.py` (25 lines, no charts) is the reference for what the landing page says. `italy_dashboard/components.py`'s `shell()` is the reference for nav structure.

- [ ] **Step 2: Write the failing test**

```python
def test_every_nav_link_reaches_a_page_that_renders(page, static_app):
    """Nav must not promise pages that do not exist.

    The app shipped with zero <a> elements precisely so nothing could 404; this
    is the test that keeps that true once links exist. Asserting the link count
    alone would pass with every link pointing at a blank page.
    """
    page.goto(static_app)
    slugs = page.eval_on_selector_all("nav a", "els => els.map(e => e.getAttribute('href'))")
    assert len(slugs) >= 7, slugs
    for slug in slugs:
        page.goto(f"{static_app}/{slug}")
        page.wait_for_selector("main h1", timeout=30_000)
        assert page.eval_on_selector("main h1", "e => e.textContent.trim()"), slug
```

- [ ] **Step 3: Run it to verify it fails**

Run: `uv run pytest -m browser -q -k nav_link`
Expected: FAIL — no `nav` element exists.

- [ ] **Step 4: Implement the router, nav and home page**

Parse `location.hash`, listen for `hashchange`, default to `home`. Route switch in `App.tsx`. Keep the colour-mode toggle working across routes — it is `App` state, so it already will, but the charts on each page must include the mode in their spec memo dependencies, the way `Climate.tsx` does.

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest -m browser -q -k nav_link`
Expected: PASS.

- [ ] **Step 6: Verify it discriminates**

Add an eighth nav link pointing at a slug with no route.
Run: `uv run pytest -m browser -q -k nav_link`
Expected: **FAIL** on that slug.

Remove it. Report the observed failure.

- [ ] **Step 7: Commit**

```bash
git add web/src/router.tsx web/src/pages/Home.tsx web/src/App.tsx tests/browser/test_static_app.py
git commit -m "feat(web): hash routing, nav and the home page"
```

---

### Task 2: Economy, labor and population

Four charts across three pages, all simple time series over data the query layer already returns.

**Files:**
- Create: `web/src/pages/Economy.tsx`, `web/src/pages/Labor.tsx`, `web/src/pages/Population.tsx`, `web/src/charts/series.tsx`
- Modify: `web/src/App.tsx`, `tests/browser/test_static_app.py`

**Interfaces:**
- Consumes: `inflationSeries()`, `unemploymentSeries(region)`, `populationTimeseries(region)`, `foreignShareTimeseries(region)`, `regionNames()`.
- Produces: `lineSeriesSpec(rows, opts)` and `stackedAreaSpec(rows, opts)` from `charts/series.tsx`, reused by Tasks 3-4.

- [ ] **Step 1: Read the three Reflex pages**

`italy_dashboard/pages/economy.py` (27 lines, 1 chart), `labor.py` (38 lines, 1 chart), `population.py` (45 lines, 2 charts). Note each page's region selector and its default.

**The region argument is a display name including any parenthetical** — the conformance cases use `'Italia (totale)'`, not `'Italia'`. A wrong string returns `[]` rather than raising, so a page built against the wrong form looks empty rather than broken.

- [ ] **Step 2: Write the failing test**

```python
@pytest.mark.parametrize(
    ("slug", "testid"),
    [("economy", "inflation"), ("labor", "unemployment"), ("population", "resident")],
)
def test_each_simple_page_renders_marks_not_an_empty_chart(page, static_app, slug, testid):
    """A page that loaded but drew nothing is what a wrong region string looks like.

    These queries return [] for an unrecognised region name rather than raising,
    so asserting the page merely rendered would pass with every chart empty.
    """
    page.goto(f"{static_app}/#/{slug}")
    page.wait_for_selector(f"[data-testid='{testid}'] path", timeout=30_000)
    count = page.eval_on_selector_all(f"[data-testid='{testid}'] path", "els => els.length")
    assert count > 0, (slug, testid)
```

- [ ] **Step 3: Run to verify it fails, implement, run again**

Run: `uv run pytest -m browser -q -k simple_page`
Expected: FAIL (no such routes), then PASS.

- [ ] **Step 4: Verify it discriminates**

Pass `"Italia"` instead of the full display name to one page's query.
Run: `uv run pytest -m browser -q -k simple_page`
Expected: **FAIL** for that page — the query returns `[]`.

Restore. Report the observed failure. This is the check that the region argument form is right.

- [ ] **Step 5: Commit**

```bash
git add web/src/pages web/src/charts/series.tsx web/src/App.tsx tests/browser/test_static_app.py
git commit -m "feat(web): the economy, labor and population pages"
```

---

### Task 3: The crime page

Eleven charts and a dimension-filter UI over the probe-driven mart engine. This is the largest task in the plan; the Reflex reference is 397 lines.

**Files:**
- Create: `web/src/pages/Crime.tsx`
- Modify: `web/src/App.tsx`, `tests/browser/test_static_app.py`

**Interfaces:**
- Consumes: `martOptions(mart)`, `martYears(mart)`, `martLatestYear(mart)`, `martProvinceOptions(mart, region)`, `martTrend`, `martTrendPivot`, `martBreakdown`, `kpis`, `offendersKpis`, `offenderRates`, `offenderForeignShare`, `regionRateRanking`, and `Mart` / `ALL` from `queries/martEngine.ts`.

- [ ] **Step 1: Read the Reflex page and the mart engine's contract**

`italy_dashboard/pages/crime.py`. Then read `_mart_where`'s docstring in `italy_dashboard/queries.py:321` — it explains why a pinned region name also needs a level pin (Valle d'Aosta is both a region and a province, so names alone are ambiguous), which the UI must respect when it builds a selection.

Two decisions the conformance reference pins, so getting them wrong will show as a failing case rather than a wrong pixel:

1. **`martTrendPivot` assigns its series slots by the LAST period's value**, not the maximum and not the first. In 2000 the `s3` slot holds Sicilia at 38946 while `s1` holds Lombardia at 35283.
2. **`kpis` and `offendersKpis` return formatted strings** with degradation branches choosing between a number and a `"—"` sentinel, and Python's thousands separator is a **comma**: `584,514`. Do not reformat them in the UI; render the strings the query layer returns.

- [ ] **Step 2: Write the failing test**

```python
def test_the_crime_page_kpis_render_python_formatted_strings(page, static_app):
    """KPI strings come from the query layer already formatted.

    Python renders `584,514` with a comma; JavaScript's toLocaleString('it-IT')
    renders `584.514`. A UI that reformats would show a plausible-looking but
    different number, so this asserts the comma survives to the DOM.
    """
    page.goto(f"{static_app}/#/crime")
    page.wait_for_selector("[data-testid='crime-kpi-total']", timeout=30_000)
    text = page.eval_on_selector("[data-testid='crime-kpi-total']", "e => e.textContent")
    assert "," in text and "." not in text, text
```

- [ ] **Step 3: Run to verify it fails, implement, run again**

Expected: FAIL (no route), then PASS.

Build the dimension filters from `martOptions`, defaulting every dimension to `ALL` — that default is what makes `_mart_where` run its probe, which is the behaviour the whole engine exists for.

- [ ] **Step 4: Verify it discriminates**

Wrap the KPI value in `Number(...).toLocaleString("it-IT")` in the page.
Expected: **FAIL** showing `584.514`.

Restore. Report the observed failure.

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/Crime.tsx web/src/App.tsx tests/browser/test_static_app.py
git commit -m "feat(web): the crime page and its dimension filters"
```

---

### Task 4: The climate×crime page

Two charts, and the most carefully-worded page in the project. **Its caveats are the deliverable as much as its charts are.**

**Files:**
- Create: `web/src/pages/ClimateCrime.tsx`
- Modify: `web/src/App.tsx`, `tests/browser/test_static_app.py`

**Interfaces:**
- Consumes: `crimeClimateScatter()`, `crimeClimateStats()`, `crimeClimateReady()`.

- [ ] **Step 1: Read the Reflex page and every caveat it carries**

`italy_dashboard/pages/climate_crime.py` uses these translation keys, and each one must appear on the static page: `cc_caveat`, `cc_coverage_note`, `cc_obs_note`, `cc_panel_title`, `cc_panel_sub`, `cc_raw_title`, `cc_raw_sub`, `cc_stat_n`, `cc_stat_panel`, `cc_stat_raw`, `cc_x_panel`, `cc_x_raw`, `cc_y_panel`, `cc_y_raw`.

Reuse the English copy from `italy_dashboard/translations.py` **verbatim**. `cc_caveat` in particular is a single paragraph stating that the comparison is association-only, ECOLOGICAL (region-level, says nothing about individuals), ANNUAL (while the heat-aggression literature works at daily and monthly grain), and UNDERPOWERED (ISTAT publishes province-level offenders only from 2022) — and that no p-values or confidence intervals are shown because with 21 clusters they would overstate precision. Do not paraphrase, shorten, or move it below the charts.

**Why this matters more than usual:** the page invites a causal reading of a correlation, and the two panels exist to show that the naive scatter is misleading — the raw view and the within-region view give different answers (r -0.087 versus -0.566 when this was built). A chart pair making that point, shipped without the paragraph explaining it, argues the opposite of what it was built to argue.

- [ ] **Step 2: Write the failing test**

```python
def test_the_climate_crime_caveat_is_present_and_above_the_charts(page, static_app):
    """The caveat is load-bearing: the two panels exist to show that the naive
    correlation is misleading, and without the paragraph the page reads as
    asserting a causal claim it explicitly disclaims.

    Asserting mere presence would pass with the text buried at the bottom, so
    this also checks it precedes the first chart in document order.
    """
    page.goto(f"{static_app}/#/climate-crime")
    page.wait_for_selector("[data-testid='cc-caveat']", timeout=30_000)
    text = page.eval_on_selector("[data-testid='cc-caveat']", "e => e.textContent")
    for word in ("ECOLOGICAL", "ANNUAL", "UNDERPOWERED"):
        assert word in text, (word, text[:200])
    precedes = page.evaluate(
        """() => {
            const caveat = document.querySelector("[data-testid='cc-caveat']");
            const chart = document.querySelector("[data-testid='cc-panel']");
            return !!(caveat && chart) &&
                (caveat.compareDocumentPosition(chart) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
        }"""
    )
    assert precedes, "the caveat must appear before the charts, not after them"
```

- [ ] **Step 3: Run to verify it fails, implement, run again**

Expected: FAIL (no route), then PASS.

- [ ] **Step 4: Verify it discriminates**

Move the caveat below the charts in the JSX.
Expected: **FAIL** on the ordering assertion while the word checks still pass — which is the point of having both.

Restore. Report both halves.

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/ClimateCrime.tsx web/src/App.tsx tests/browser/test_static_app.py
git commit -m "feat(web): the climate-crime page, caveats first"
```

---

### Task 5: Deploy verification and documentation

**Files:**
- Modify: `docs/12-deployment.md`, `tests/browser/test_static_app.py`

- [ ] **Step 1: Build and serve the real bundle**

Run: `npm --prefix web run build && python3 -m http.server -d web/dist 8899`

Serve with a **plain static server, not `vite preview`** — its SPA fallback masks 404s, which is exactly the class of bug a deploy must surface.

- [ ] **Step 2: Check the bundle did not grow unreasonably**

Run: `du -sh web/dist`
Expected: still a few MB. Six pages add JavaScript, not data — the 13 staged parquet are unchanged, so a large jump means something pulled data into the bundle.

Report the actual figure against the 4.7 MB baseline.

- [ ] **Step 3: Walk every route against the served bundle**

For each of the seven routes: it renders, its charts draw marks, and the colour-mode toggle repaints them. Confirm the **only** 404 in the network log is `mart_climate_daily.parquet`.

- [ ] **Step 4: Run the full suites three times**

Run: `uv run pytest -m browser -q` ×3
Expected: green all three. Report all three results — browser tests here went flaky once already from per-test cold DuckDB-WASM boots, and one green run is not evidence.

- [ ] **Step 5: Update the documentation**

`docs/12-deployment.md` describes the Netlify deployment as shipping one page. Update it: seven pages, hash routing and why (no rewrite rule, so the deliberate `mart_climate_daily` 404 stays a 404), and that Render remains canonical.

- [ ] **Step 6: Commit**

```bash
git add docs/12-deployment.md tests/browser/test_static_app.py
git commit -m "docs(deploy): the static app now serves all seven pages"
```

---

## Self-Review

**Spec coverage.** The spec's "Charts" section is satisfied across Tasks 2-4; its month-heatmap `cell` mark already shipped with the climate page. "Deployment" was completed in the previous plan and is only re-verified here (Task 5). The spec's remaining unbuilt item is the precomputed distribution JSON that would replace `mart_climate_daily`; it stays out of scope, and the distribution card continues to explain its absence.

**Type consistency.** `lineSeriesSpec` / `stackedAreaSpec` are defined in Task 2 and reused in Tasks 3-4. `Mart` and `ALL` come from `queries/martEngine.ts`, already exported. `useRoute` / `ROUTES` are defined in Task 1 and consumed by every later task's `App.tsx` edit.

**Chart counts, measured rather than estimated:** crime 11, population 2, climate×crime 2, economy 1, labor 1, home 0 — 17 total. Crime alone is roughly two-thirds of the work and is the one task worth splitting if it proves larger than it looks.

**Known risk.** The crime page is the only one whose UI drives the probe-based mart engine, and the conformance matrix covers the engine at the *query* level, not at the level of selections a user can assemble by clicking. A selection combination the matrix never exercises could produce an empty chart with no explanation. Task 3 should treat "this combination has no data" as a first-class state rather than letting a chart render zero marks.
