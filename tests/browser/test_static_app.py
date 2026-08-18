import csv
from collections.abc import Iterator
from pathlib import Path

import pytest

pytestmark = pytest.mark.browser

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

STORAGE_KEY = "italy-dashboard-color-mode"

# Task 1 (router.tsx) made "home" the default landing route (`#/` with no
# hash, or none at all) -- every test below that exercises climate-specific
# markup must navigate to the climate route explicitly, matching the exact
# href its own nav link carries (`#/${slug}` in App.tsx). Only the palette
# test below is route-independent (the body background is painted for every
# route alike) and is left pointed at the bare `static_app` root.
CLIMATE_HREF = "#/climate"


@pytest.fixture(scope="module")
def page(browser) -> Iterator:
    """Override pytest-playwright's function-scoped `page` with one shared by
    every test in this module.

    F5: 2 of 3 full-suite runs of this file went red, a different test each
    time, all 30-second `wait_for_selector` timeouts, 4/4 green in isolation --
    load/ordering sensitivity, not a real assertion failure. Each test used to
    get its own fresh `BrowserContext` (pytest-playwright's default `page`
    fixture), so each paid a full cold DuckDB-WASM boot with an EMPTY disk
    cache for the jsDelivr CDN fetch, competing with whatever else the full
    suite has running. Sharing one page (and therefore one context, and its
    cache) for the module is the same shape `test_conformance.py`'s
    module-scoped `harness_page` already uses. Each test still calls
    `page.goto(static_app)` itself -- a real navigation that resets the app's
    own JS module state (the DuckDB connection singleton in db.ts, the
    colour-mode listener in App.tsx) between tests, so only the network cache
    is shared, not application state.
    """
    p = browser.new_page()
    try:
        yield p
    finally:
        p.close()


def test_the_shell_paints_the_palette_surface(page, static_app):
    """The page background must come from shared/palette.json, not a CSS default.

    A page that renders with the browser's default white looks fine in light
    mode and wrong in dark mode, and nothing else in this suite would notice.
    """
    page.goto(static_app)
    background = page.evaluate("() => getComputedStyle(document.body).backgroundColor")
    assert background == "rgb(252, 252, 251)", background  # palette surface.light


def test_the_stripes_resolve_to_distinct_diverging_colours(page, static_app):
    """Warming stripes must use the diverging scale, and adjacent buckets must
    be visually distinct.

    Asserting "a fill exists" would pass on a chart drawn entirely in one
    colour, which is the failure mode that actually happens when a scale is
    misconfigured.
    """
    page.goto(f"{static_app}/{CLIMATE_HREF}")
    page.wait_for_selector("[data-testid='climate-stripes'] rect", timeout=30_000)
    fills = page.eval_on_selector_all(
        "[data-testid='climate-stripes'] rect",
        "els => [...new Set(els.map(e => getComputedStyle(e).fill))]",
    )
    assert len(fills) >= 4, fills


def test_a_diverging_colour_resolves_differently_across_data_theme_states(page, static_app):
    """The static shell switches modes via a `data-theme` ATTRIBUTE on <html>
    (App.tsx), not the `.dark` CLASS Reflex/Radix uses. `shared/palette.css`
    used to define `--div-N` only for `:root`/`.dark`, so this attribute never
    switched anything: dark mode rendered the warming stripes in the LIGHT
    diverging ramp, on a dark surface, and no test caught it because every
    other check either inspects the render tree (never resolves a browser's
    CSS cascade) or reads `shared/palette.json` directly (theme.ts's
    JS-computed `currentMode()`, a separate mechanism from the CSS custom
    property the stripe fill actually uses -- see queries/climate.ts's
    `withStripeFill`).
    """
    page.goto(f"{static_app}/{CLIMATE_HREF}")
    page.wait_for_selector("[data-testid='climate-stripes'] rect", timeout=30_000)

    def first_bar_fill() -> str:
        return page.eval_on_selector(
            "[data-testid='climate-stripes'] rect",
            "el => getComputedStyle(el).fill",
        )

    page.evaluate("document.documentElement.dataset.theme = 'light'")
    light_fill = first_bar_fill()

    page.evaluate("document.documentElement.dataset.theme = 'dark'")
    dark_fill = first_bar_fill()

    assert dark_fill != light_fill, (
        f"a stripe bar's diverging colour did not change between data-theme "
        f"states (light={light_fill!r}, dark={dark_fill!r}); the generated "
        f"CSS is not actually keyed off the [data-theme] attribute"
    )


def test_the_climate_page_renders_data_not_an_empty_state(page, static_app):
    """The climate route must reach real data, not sit on a spinner.

    Asserting the page merely 'loaded' would pass while every chart is empty,
    which is what a broken parquet path looks like.
    """
    page.goto(f"{static_app}/{CLIMATE_HREF}")
    page.wait_for_selector("[data-testid='climate-annual'] path", timeout=30_000)
    marks = page.eval_on_selector_all("[data-testid='climate-annual'] path", "els => els.length")
    assert marks > 0, "no marks drawn in the annual series chart"


def test_the_stripes_grid_renders_visible_cells(page, static_app):
    """F1: `facetedStripesSpec` used to leave every one of its 912 cells at
    `width="0"` -- no explicit `width` (Plot defaults to 640), so 12 `fx`
    facets of 76 year-bands each divided down to ~0.64px per band before
    `inset: 0.5` (a full pixel removed) clamped every one to zero. The card
    was a blank box with 12 overlapping labels under it, on the climate page.

    Deliberately does NOT `wait_for_selector` with the default `visible`
    state: a zero-width `<rect>` is still attached to the DOM, but Playwright
    refuses to call it "visible", so waiting on visibility is exactly the
    Plot/Playwright interaction Task 2's comment at climate.tsx:55-61 already
    diagnosed for the axis tick dashes -- it would HANG for the full timeout
    rather than fail. `state="attached"` only waits for the elements to
    exist; the actual check is the geometry assertion below.
    """
    page.goto(f"{static_app}/{CLIMATE_HREF}")
    page.wait_for_selector("[data-testid='climate-grid'] rect", state="attached", timeout=30_000)
    widths = page.eval_on_selector_all(
        "[data-testid='climate-grid'] rect",
        "els => els.map(e => e.getBoundingClientRect().width)",
    )
    assert widths, "no cells rendered in the warming-stripes grid"
    assert min(widths) >= 2, (
        f"a warming-stripes grid cell rendered narrower than 2px (min={min(widths)}, "
        f"n={len(widths)}); see facetedStripesSpec's width/inset sizing in climate.tsx"
    )


def test_the_stripes_grid_has_no_phantom_facet_at_italia_scope(page, static_app):
    """F2: `Plot.frame({fx: highlight})` with `highlight = ""` does not "render
    in zero facets" as climate.tsx used to claim -- Plot builds the `fx` scale
    DOMAIN from the union of every mark's `fx` values, so the literal `""`
    joined it as a real 13th entry: a phantom, unlabelled facet with a heavy
    box around it at Italia and region scope (measured: 13 fx tick labels at
    Italia, 12 at Milano). Asserts the exact facet count, not merely "some
    facets exist" -- the phantom facet would satisfy the weaker check too.

    The grid always renders `loadStripesGrid(12)`'s top-12 cities (Climate.tsx),
    so 12 is a real invariant of the code being exercised here, not a guess.
    """
    page.goto(f"{static_app}/{CLIMATE_HREF}")
    page.wait_for_selector("[data-testid='climate-grid'] rect", state="attached", timeout=30_000)
    labels = page.eval_on_selector_all(
        "[data-testid='climate-grid'] [aria-label='fx-axis tick label'] text",
        "els => els.map(e => e.textContent)",
    )
    assert labels.count("") == 0, f"a blank fx facet label is present: {labels}"
    assert len(labels) == 12, (
        f"expected exactly 12 city facets at Italia scope, got {len(labels)}: {labels}"
    )


def test_a_plot_baked_colour_repaints_on_mode_toggle(page, static_app):
    """F3: `theme.ts`'s accessors (series/gridline/inkPrimary/divergingSteps)
    are read at Plot SPEC-BUILD time, and Climate.tsx used to memoise every
    chart spec on data only -- so toggling colour mode repainted the body
    background and the stripes' CSS-driven `var(--div-N)` fill (the existing
    test above), but left every Plot-baked colour, e.g. the ranking bar's
    `series(1)`, stuck on whichever mode was active on first render.

    Unlike the diverging-colour test above, this must exercise the real
    toggle (App.tsx's button), not poke `data-theme` directly: a direct
    attribute mutation resolves through the CSS cascade with no JS involved,
    which is exactly the mechanism that already worked and is not what this
    finding is about. Clicking the button is what drives App's `mode` state,
    which is what the fix threads into Climate's `useMemo` dependencies.

    Exact rgb values from `shared/palette.json`'s categorical scale, index 1
    (`series(1)`): light `#eb6834` = rgb(235, 104, 52), dark `#de5c27` =
    rgb(222, 92, 39) -- the same pair the final review measured by hand.
    """
    page.goto(f"{static_app}/{CLIMATE_HREF}")
    # Deterministic starting point regardless of what an earlier test in this
    # module (or a previous run reusing this profile) left behind: clear the
    # persisted choice and reload so App mounts on "system".
    page.evaluate(f"window.localStorage.removeItem('{STORAGE_KEY}')")
    page.reload()
    page.wait_for_selector("[data-testid='climate-ranking'] rect", timeout=30_000)

    def first_ranking_bar_fill() -> str:
        return page.eval_on_selector(
            "[data-testid='climate-ranking'] rect",
            "el => getComputedStyle(el).fill",
        )

    toggle = page.get_by_role("button", name="Colour mode")
    try:
        toggle.click()  # system -> light (deterministic: choice starts at "system")
        light_fill = first_ranking_bar_fill()
        assert light_fill == "rgb(235, 104, 52)", light_fill

        toggle.click()  # light -> dark
        dark_fill = first_ranking_bar_fill()
        assert dark_fill == "rgb(222, 92, 39)", dark_fill
    finally:
        # Leave no persisted choice behind for whichever test runs next.
        page.evaluate(f"window.localStorage.removeItem('{STORAGE_KEY}')")


def test_a_partial_region_scope_shows_a_composition_caveat(page, static_app):
    """F6: Toscana is 1 of 10 capitals, Puglia 1 of 6, Marche 1 of 5 -- each
    used to be presented as the region with zero alerts, the same shape of
    wrong number the Italia coverage note exists to prevent, at a scope where
    the caveat was switched off entirely (`region == "Italia"` was the whole
    gate). Puglia scope is entirely Barletta. Asserts the caveat text carries
    the real counts (derived from the same seed CSV, never hardcoded here),
    not just "some caveat exists".
    """
    seed = REPO_ROOT / "dbt" / "seeds" / "province_capitals.csv"
    with seed.open(newline="") as f:
        total = sum(1 for row in csv.DictReader(f) if row["region_name"] == "Puglia")
    assert total > 1, (
        "fixture assumption broken: Puglia should have more than 1 capital in the seed"
    )

    page.goto(f"{static_app}/{CLIMATE_HREF}")
    page.wait_for_selector("[data-testid='climate-grid'] rect", state="attached", timeout=30_000)
    page.select_option("[data-testid='climate-region-select']", "Puglia")
    # The caveat depends on `climateCityOptions("Puglia")` resolving (async),
    # which briefly makes the note disappear entirely (Italia's note is gated
    # off the moment `region` changes, before Puglia's own coverage is known)
    # before it reappears with the region's real counts -- poll for the
    # settled state rather than a fixed sleep. If the fix regresses (no
    # branch, or the wrong gate), this never becomes true and raises a normal
    # TimeoutError -- a fail, not a hang.
    page.wait_for_function(
        "() => { const el = document.querySelector(\"[data-testid='climate-scope-note']\"); "
        "return !!el && el.textContent.includes('Puglia'); }",
        timeout=15_000,
    )

    note = page.eval_on_selector("[data-testid='climate-scope-note']", "el => el.textContent")
    assert note is not None, (
        "expected a composition caveat at partial region scope (Puglia), found none"
    )
    assert f"1 of {total} capitals" in note, note


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


def test_the_crime_page_income_scatter_renders_real_points(page, static_app):
    """The income-vs-offender-rate card must reach real data, not an empty chart.

    An empty scatter with no explanation reads as broken, not as "no data" --
    the same standing rule the other chart pages in this suite already
    enforce (see `test_the_climate_page_renders_data_not_an_empty_state`).
    `mart_crime_income`'s latest year (2024) carries 12 regions per
    citizenship group, so this asserts a real, non-trivial point count
    rather than merely "at least one".
    """
    page.goto(f"{static_app}/#/crime")
    page.wait_for_selector("[data-testid='crime-income-scatter'] circle", timeout=30_000)
    points = page.eval_on_selector_all("[data-testid='crime-income-scatter'] circle", "els => els.length")
    assert points >= 20, points


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
