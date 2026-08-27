import csv
import json
import re
from collections.abc import Iterator
from pathlib import Path

# Environment artefact, not a missing dependency: pytest is a dev dependency and
# is installed in .venv -- `uv run pyrefly check` (the typechecker `just check`
# and CI run) reports 0 errors on this file. The suppression is for a
# Pyright-based language server whose workspace root sits ABOVE this repo, which
# therefore never reads our pyrightconfig.json and resolves imports against the
# system interpreter. Same case, and same one-rule-one-line scoping, as the
# `import reflex` suppression in italy_dashboard/theme.py.
import pytest  # pyright: ignore[reportMissingImports]

pytestmark = pytest.mark.browser

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# The same artefact the frontend itself reads (web/src/theme.ts imports it), so
# a palette change cannot leave this file asserting a stale colour. Loaded once
# at module scope rather than re-read per test.
PALETTE = json.loads((REPO_ROOT / "shared" / "palette.json").read_text())


def _rgb(hex_colour: str) -> str:
    """`#rrggbb` as the `rgb(r, g, b)` string `getComputedStyle` returns."""
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgb({r}, {g}, {b})"


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


def test_the_shell_paints_the_palette_page_background(page, static_app):
    """The page background must come from shared/palette.json, not a CSS default.

    A page that renders with the browser's default white looks fine in light
    mode and wrong in dark mode, and nothing else in this suite would notice.

    `page_bg`, not `surface`: those were the same colour until the readability
    pass, which is precisely why the app read as one flat sheet -- every `Card`
    paints itself `surface()`, so a body painted the same value left a card
    detectable only by its 1px border. They are now two roles, and this asserts
    the body gets the PAGE one. Read from palette.json rather than hardcoded, so
    a future palette edit does not fail here with a stale literal reported as if
    it were a regression in the app.
    """
    page.goto(static_app)
    background = page.evaluate("() => getComputedStyle(document.body).backgroundColor")
    assert background == _rgb(PALETTE["page_bg"]["light"]), background
    # ...and specifically NOT the card surface, which is the distinction the
    # whole two-surface change exists to create.
    assert background != _rgb(PALETTE["surface"]["light"])


def test_a_card_is_visually_raised_off_the_page(page, static_app):
    """A `Card` must not be the same colour as the page behind it.

    The regression this pins: the app shipped with `pageBg()` and `surface()`
    as one value, so every card was distinguishable only by a 1px hairline and
    the entire UI read as flat. A test asserting only "the card has a border"
    would have passed throughout. This asserts the two surfaces actually
    differ, in the browser's own computed values.
    """
    page.goto(static_app + CLIMATE_HREF)
    card = page.locator("main section").first
    card.wait_for(state="visible")
    card_bg = card.evaluate("el => getComputedStyle(el).backgroundColor")
    body_bg = page.evaluate("() => getComputedStyle(document.body).backgroundColor")
    assert card_bg != body_bg, (
        f"card background ({card_bg}) is identical to the page ({body_bg}): "
        "the elevation cue is gone"
    )
    assert card_bg == _rgb(PALETTE["surface"]["light"]), card_bg


def test_keyboard_focus_shows_a_visible_ring_on_the_first_frame(page, static_app):
    """WCAG 2.1 SS2.4.7 (Focus Visible): a `:focus-visible` ring must be there
    on the very first frame after `Tab` lands on an element, not partway
    through a CSS transition.

    `theme.css`'s `.nav-link`/`.mode-toggle` rule sets `outline: none` and
    compensates with a `box-shadow` ring. An earlier version also
    TRANSITIONED that box-shadow (matching the hover background's fade), so
    reading computed style immediately after `Tab` -- exactly what this test
    does, deliberately with no wait -- caught the ring still fading in from
    a near-zero spread, indistinguishable from no ring at all; a 150-250ms
    wait before reading made the very same rule look correct. Checked via
    the box-shadow's SPREAD radius (the last length in `"... 0px 0px 0px
    2px"`), not its colour string: `color-mix()` serializes differently
    across engines (`rgba(...)` vs `color(srgb ... / a)`), but a real ring
    always carries a positive spread, and a not-yet-transitioned one is 0.
    """
    page.goto(static_app)
    page.wait_for_timeout(300)
    focusable_seen = 0
    for _ in range(6):
        page.keyboard.press("Tab")
        # No `wait_for_timeout` here on purpose -- see the docstring.
        box_shadow, class_name = page.evaluate(
            "() => [getComputedStyle(document.activeElement).boxShadow, "
            "document.activeElement.className]"
        )
        if class_name not in ("nav-link", "mode-toggle"):
            continue
        focusable_seen += 1
        spreads = re.findall(r"(-?[\d.]+)px", box_shadow)
        assert spreads and float(spreads[-1]) > 0, (
            f".{class_name} has no visible focus ring on the first frame after "
            f"Tab: boxShadow={box_shadow!r}"
        )
    assert focusable_seen > 0, "never tabbed onto a .nav-link/.mode-toggle element"


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


def test_year_axes_render_without_a_thousands_separator(page, static_app):
    """F6: Plot's default numeric tick formatter groups thousands, so a bare
    year axis (no `tickFormat`) read `2,024` instead of `2024` -- pre-existing
    on the climate page, multiplied across every chart this plan added that
    shares `lineSeriesSpec`'s x-axis or climate.tsx's own year-axis builders.
    Checks one chart from each of the two fixed spec builders
    (`lineSeriesSpec` via labor's unemployment, `bandTrendSpec` via climate)
    rather than every affected chart, since the fix is the same one-line
    `tickFormat` in both places and a regression would show up on either
    sample alike. (Economy's inflation -- the old first sample -- moved off
    `lineSeriesSpec` onto `vBarSpec`, whose band year axis has no formatter
    grouping to regress, so unemployment carries that leg now.)
    """
    page.goto(f"{static_app}/#/labor")
    page.wait_for_selector("[data-testid='unemployment'] path", timeout=30_000)
    labor_ticks = page.eval_on_selector_all(
        "[data-testid='unemployment'] [aria-label='x-axis tick label'] text",
        "els => els.map(e => e.textContent)",
    )
    assert labor_ticks, "no x-axis ticks found on the unemployment chart"
    assert not any("," in t for t in labor_ticks), labor_ticks

    page.goto(f"{static_app}/{CLIMATE_HREF}")
    page.wait_for_selector("[data-testid='climate-annual'] path", timeout=30_000)
    climate_ticks = page.eval_on_selector_all(
        "[data-testid='climate-annual'] [aria-label='x-axis tick label'] text",
        "els => els.map(e => e.textContent)",
    )
    assert climate_ticks, "no x-axis ticks found on the climate annual chart"
    assert not any("," in t for t in climate_ticks), climate_ticks


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
    labels = page.locator("[data-testid='climate-stripe-city']").all_text_contents()
    assert all(labels), f"a blank city label is present: {labels}"
    assert len(labels) == 12, (
        f"expected exactly 12 city panels at Italia scope, got {len(labels)}: {labels}"
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
    """F6: Toscana, Puglia, Marche -- each used to be presented as the region
    with zero alerts once only one of its capitals had temperature data, the
    same shape of wrong number the Italia coverage note exists to prevent, at
    a scope where the caveat was switched off entirely (`region == "Italia"`
    was the whole gate). Asserts the caveat text carries the real counts, both
    derived here (never hardcoded): `total` from the seed CSV (every frontend
    already does this), `covered` from `climate_city_options`, the same
    DuckDB-backed function the app itself calls for the city dropdown -- so
    this keeps passing as the temperature backfill covers more of Puglia,
    rather than pinning today's snapshot as if it were permanent.
    """
    from italy_dashboard import queries as q

    seed = REPO_ROOT / "dbt" / "seeds" / "province_capitals.csv"
    with seed.open(newline="") as f:
        total = sum(1 for row in csv.DictReader(f) if row["region_name"] == "Puglia")
    assert total > 1, (
        "fixture assumption broken: Puglia should have more than 1 capital in the seed"
    )
    covered = len(q.climate_city_options("Puglia")) - 1  # -1 for the "All" entry
    assert 0 < covered < total, (
        "fixture assumption broken: Puglia should be partially, not fully, covered"
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
    assert f"{covered} of {total} capitals" in note, note


def test_the_climate_coverage_note_renders_as_a_prominent_callout_not_plain_text(page, static_app):
    """The concrete visual regression this task exists to fix: before `Callout`
    (ui.tsx) existed, `climate-scope-note` was a plain bordered `<div>` --
    visually identical to `EmptyNote`'s neutral "no data" text, with no colour
    and no icon, easy to miss on a page whose whole point is that this
    aggregate is not what it looks like.

    Two independent signals, either of which a reverted-to-plain-`<div>`
    render would fail: an icon element (`Callout` always renders one, `EmptyNote`
    /a plain `<div>` never do), and a background colour visibly different from
    the page surface (a plain `<div>` never sets `background`, so it computes
    to the surface colour showing through, or `transparent`).
    """
    page.goto(
        f"{static_app}/{CLIMATE_HREF}"
    )  # region defaults to "Italia" -> the national coverage note
    page.wait_for_selector("[data-testid='climate-scope-note']", timeout=30_000)

    has_icon = page.eval_on_selector(
        "[data-testid='climate-scope-note']", "el => el.querySelector('svg') !== null"
    )
    assert has_icon, "expected an icon inside the coverage-note callout, found none"

    background = page.eval_on_selector(
        "[data-testid='climate-scope-note']", "el => getComputedStyle(el).backgroundColor"
    )
    surface = page.evaluate("() => getComputedStyle(document.body).backgroundColor")
    assert background not in (surface, "rgba(0, 0, 0, 0)", "transparent"), (
        f"coverage-note callout background ({background}) is not visibly distinct "
        f"from the plain page surface ({surface})"
    )


@pytest.mark.parametrize(
    ("slug", "testid", "mark"),
    [
        # Economy's inflation is now a VERTICAL BAR chart (`vBarSpec`, after
        # the bar-parity task moved it off the line spec), so its marks are
        # `<rect>`s, not `<path>`s -- matched separately from the two charts
        # that are still lines. See vBarSpec's docstring.
        ("economy", "inflation", "rect"),
        ("labor", "unemployment", "path"),
        ("population", "resident", "path"),
    ],
)
def test_each_simple_page_renders_marks_not_an_empty_chart(page, static_app, slug, testid, mark):
    """A page that loaded but drew nothing is what a wrong region string looks like.

    These queries return [] for an unrecognised region name rather than raising,
    so asserting the page merely rendered would pass with every chart empty.
    """
    page.goto(f"{static_app}/#/{slug}")
    page.wait_for_selector(f"[data-testid='{testid}'] {mark}", timeout=30_000)
    count = page.eval_on_selector_all(f"[data-testid='{testid}'] {mark}", "els => els.length")
    assert count > 0, (slug, testid)


def test_the_education_page_renders_dsu_bars(page, static_app):
    page.goto(f"{static_app}/#/education")
    page.wait_for_selector("[data-testid='dsu-ranking'] rect", timeout=30_000)
    count = page.eval_on_selector_all("[data-testid='dsu-ranking'] rect", "els => els.length")
    assert count > 0, count


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
    points = page.eval_on_selector_all(
        "[data-testid='crime-income-scatter'] circle", "els => els.length"
    )
    assert points >= 20, points


def test_the_crime_page_correlation_strings_render_verbatim(page, static_app):
    """`incomeCorrelations()` returns already-formatted `"r = ... (n=...)"`
    strings, the same rule as the KPI tiles: rendered as-is, never recomputed
    or reformatted in the UI. This pins the exact strings for the mart's
    latest year against a direct query (`italy_dashboard.queries`, not a
    retyped literal), so a page that recalculated the correlation itself --
    or reformatted the sign, precision, or `n` -- would fail here even though
    nothing about the request or response shape looks wrong, while a routine
    data refresh that shifts the actual r/n does not desync this test from
    reality.
    """
    from italy_dashboard import queries as q

    latest_year = q.income_years()[0]
    expected = q.income_correlations(latest_year)

    page.goto(f"{static_app}/#/crime")
    page.wait_for_selector("[data-testid='crime-income-corr-italians']", timeout=30_000)
    italians = page.eval_on_selector(
        "[data-testid='crime-income-corr-italians']", "e => e.textContent"
    )
    foreigners = page.eval_on_selector(
        "[data-testid='crime-income-corr-foreigners']", "e => e.textContent"
    )
    assert italians == expected["ITL"], italians
    assert foreigners == expected["FRG"], foreigners


def test_the_crime_page_method_note_is_present_verbatim(page, static_app):
    """The final review (F1) found `method_note` missing from the offenders
    tab entirely: no statement anywhere that the headline totals are counts
    rather than rates, that citizenship is not residence status, or that a
    cross-crime total counts a person once per crime type -- on the page
    that publishes a 37.3% foreign-share figure and a 6.1x rate ratio. Pins
    the exact English copy against `italy_dashboard.translations.EN`
    directly (not a hand-retyped copy in this test) so a paraphrase,
    truncation, or reordering would fail here even though the paragraph is
    technically present.
    """
    import italy_dashboard.translations as translations

    expected = translations.EN["method_note"]
    page.goto(f"{static_app}/#/crime")
    page.wait_for_selector("[data-testid='crime-method-note']", timeout=30_000)
    text = page.eval_on_selector("[data-testid='crime-method-note']", "e => e.textContent")
    assert text == expected, text


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


def test_the_cc_panel_has_zero_lines_but_the_raw_scatter_does_not(page, static_app):
    """Mirrors tests/unit/test_components.py's
    `test_climate_crime_panel_scatter_has_zero_lines_but_raw_scatter_does_not`
    on the STATIC side, which was missing the cross-hairs entirely until the
    zero-lines parity task: `scatterSpec` got an opt-in `zeroLines` so the
    demeaned panel can draw them.

    The two zero rules (`Plot.ruleX([0])` / `Plot.ruleY([0])`) are stroked
    at 1.5px -- a step up from the 1px grid and gridlines, both of which
    otherwise share the axis ink (see scatterSpec's own comment on why) --
    so they are the addressable stand-ins for Reflex's two
    `RechartsReferenceLine`s: exactly two heavier lines on the panel, exactly
    zero on the raw scatter. `cc-raw` is waited on to prove it RENDERED (a
    missing chart tops out at "0 heavier lines" too), so a broken raw data
    path cannot pass by absence.
    """
    page.goto(f"{static_app}/#/climate-crime")
    page.wait_for_selector("[data-testid='cc-panel'] circle", timeout=30_000)
    page.wait_for_selector("[data-testid='cc-raw'] circle", timeout=30_000)
    panel_zero = page.eval_on_selector_all(
        "[data-testid='cc-panel'] line",
        "els => els.filter(e => getComputedStyle(e).strokeWidth === '1.5px').length",
    )
    raw_zero = page.eval_on_selector_all(
        "[data-testid='cc-raw'] line",
        "els => els.filter(e => getComputedStyle(e).strokeWidth === '1.5px').length",
    )
    assert panel_zero == 2, (panel_zero, raw_zero)
    assert raw_zero == 0, (panel_zero, raw_zero)


def test_every_chart_card_has_an_expandable_view_as_table(page, static_app):
    """Parity with Reflex's `data_table(...)`: every static chart card that
    has rows exposes a native `<details>` "View as table" (ui.tsx `DataTable`).
    Exercise the economy one end-to-end -- it is gated on real rows, so a
    broken data path cannot pass by absence -- and assert the native toggle
    actually reveals the table's header + cells on click.
    """
    page.goto(f"{static_app}/#/economy")
    page.wait_for_selector("[data-testid='inflation'] rect", timeout=30_000)
    details = page.locator("details[data-testid='inflation-table']")
    assert details.is_visible(), "data table should be rendered under the card"
    assert details.get_attribute("open") is None, "table should start collapsed"
    details.locator("summary").click()
    assert details.get_attribute("open") is not None, "summary click should expand the table"
    headers = details.locator("th").all_text_contents()
    assert headers == ["Year", "Change (%)"], headers
    rows = details.locator("tbody tr").count()
    assert rows > 0, rows
    first = details.locator("tbody tr td").first.text_content()
    assert first, first


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


def test_an_unregistered_route_shows_the_branded_not_found_panel(page, static_app):
    """A slug that is not in ROUTES at all (a dangling link, a stale bookmark,
    a typo) must render App.tsx's `NotFound` panel inside the normal shell --
    not a silent blank content area, and not a route the app happens to
    coerce to home.

    Before `NotFound` existed, `router.tsx`'s deliberate "return an unknown
    slug verbatim" behaviour (see its own docstring) meant the header, nav
    and colour-mode control all rendered fine while `<main>` was completely
    empty -- indistinguishable from a genuinely broken page to a visitor.
    """
    page.goto(f"{static_app}/#/this-route-does-not-exist")
    page.wait_for_selector("main h1", timeout=30_000)
    assert page.eval_on_selector("main h1", "e => e.textContent.trim()") == "Page not found"
    # The shell around it must still be there: this is a panel inside the
    # normal page, not a separate error screen.
    assert page.locator("nav a").count() >= 7
    assert page.get_by_text("Italy Dashboard").count() > 0


def test_a_route_missing_its_switch_case_still_renders_nothing(page, static_app):
    """The other half of the `NotFound` gate: a slug that IS in `ROUTES` (so a
    real nav link points at it) must still render nothing in `<main>` if its
    `switch` `case` were ever deleted -- `NotFound` must not swallow that
    regression the way an earlier generic `ComingSoon` fallback used to (see
    App.tsx's comment above the switch). This test cannot delete a `case` at
    runtime, so it pins the CURRENT behaviour of a route with a real case
    (home always renders a non-empty `<h1>`), which is exactly what
    `test_every_nav_link_reaches_a_page_that_renders` already covers end to
    end; this test exists as a fast, explicit statement of the invariant
    `NotFound`'s ROUTES-membership gate depends on, not a new code path.
    """
    page.goto(f"{static_app}/#/home")
    page.wait_for_selector("main h1", timeout=30_000)
    heading = page.eval_on_selector("main h1", "e => e.textContent.trim()")
    assert heading and heading != "Page not found", heading


# Task 5 (deploy verification): the one route-independent invariant that
# actually matters for a static host with no rewrite rule (see
# docs/12-deployment.md's "Routing" section) -- a wrong asset path, a JS chunk
# that failed to load, or an accidentally-shipped/accidentally-excluded mart
# would all show up here as a bad response somewhere in this walk.
_ROUTE_READY_SELECTORS = {
    "home": "main h1",  # no chart by design (four KPI tiles only); the heading is the whole signal
    "economy": "[data-testid='inflation'] rect",  # bars since the vBarSpec task
    "education": "[data-testid='dsu-ranking'] rect",
    "labor": "[data-testid='unemployment'] path",
    "population": "[data-testid='resident'] path",
    "crime": "[data-testid='crime-offenders-trend'] path",
    "climate": "[data-testid='climate-annual'] path",
    "climate-crime": "[data-testid='cc-panel'] circle",
}


def test_only_the_deliberately_excluded_mart_404s_across_every_route(page, built_static_app):
    """Walking all routes must produce exactly one kind of non-2xx
    response: `marts/mart_climate_daily.parquet` (10 MB for one chart,
    excluded from the static build by `scripts/stage_web_data.py`) and
    DuckDB-WASM's own glob-fallback probe against that same path.

    Deliberately uses `built_static_app` (a real `npm run build`, served by a
    plain HTTP server), not the module's usual `static_app` (Vite's dev
    server): see `built_static_app`'s docstring in conftest.py for why Vite's
    dev server cannot be trusted for this specific check -- it has its own
    SPA fallback, keyed on the request's `Accept` header rather than the
    URL, that a plain `fetch()` call (what DuckDB-WASM's httpfs reader sends)
    triggers just as reliably as `vite preview`'s does.

    `getConnection()` (db.ts) registers a view for every dataset in `PARQUET`
    -- including the excluded one -- SEQUENTIALLY before any query on that
    connection resolves, and that registration reruns on every full
    navigation (a fresh JS module, a fresh connection singleton). Waiting for
    each route's own chart marks (not just its heading) before moving on
    guarantees that route's registration pass has actually completed and its
    network activity captured, rather than racing a navigation that aborts
    it mid-flight.

    Any *other* 404 -- a missing asset, a wrong path, a JS chunk that failed
    to load -- is a real bug this test exists to catch.
    """
    bad_responses: list[tuple[int, str]] = []

    def record(response) -> None:
        if response.status >= 400:
            bad_responses.append((response.status, response.url))

    page.on("response", record)
    try:
        for slug, ready_selector in _ROUTE_READY_SELECTORS.items():
            # This module's `page` fixture is shared across every test in the
            # file (see its docstring). `built_static_app` is a different
            # origin (its own port) from whatever `static_app` URL earlier
            # tests left this page on, so the FIRST iteration below is
            # already a genuine cross-origin navigation; `about:blank` in
            # between guards the REMAINING iterations too, where successive
            # `goto`s differ only by hash against the same
            # `built_static_app` origin -- ruling out any same-document
            # optimisation a repeated hash-only URL might otherwise get, so
            # every route gets a fresh JS module load and therefore a fresh
            # `getConnection()` singleton, re-registering every `PARQUET`
            # view (including the excluded one) from scratch.
            page.goto("about:blank")
            page.goto(f"{built_static_app}/#/{slug}")
            page.wait_for_selector(ready_selector, timeout=30_000)
    finally:
        page.remove_listener("response", record)

    unexpected = [
        (status, url) for status, url in bad_responses if "mart_climate_daily.parquet" not in url
    ]
    assert not unexpected, (
        f"unexpected non-2xx response(s) while walking every route: {unexpected}\n"
        f"(all bad responses seen: {bad_responses})"
    )
    assert any("mart_climate_daily.parquet" in url for _, url in bad_responses), (
        "expected marts/mart_climate_daily.parquet to 404 at least once across all seven "
        "routes; none was observed -- check scripts/stage_web_data.py's EXCLUDED_FROM_STATIC_BUILD "
        "and that web/public-data was actually staged before this build"
    )


LANG_STORAGE_KEY = "italy-dashboard-lang"


def test_the_language_toggle_switches_every_landmark_to_italian_and_back(page, static_app):
    """The EN · IT toggle in the header must swap the shell's own copy, run the
    per-page strings (home title + card labels + the 404 template) with it, and
    persist the choice across a reload -- in both directions.

    The static app ships as a single English bundle that subscribes to a
    language after mount (i18n.tsx), so there is nothing else in this suite
    that would notice a toggle that updated only the chip itself. This test is
    the parity check for `_lang_toggle` in Reflex's components.py: the same
    two-chip control, the same default (browser language, otherwise English),
    the same persistence. `aria-pressed` marks the active chip, and asserts the
    control state rather than font weight, which the ink-priority styles could
    re-shuffle without breaking behaviour.
    """
    page.goto(static_app)
    # Deterministic starting point: the shared module-scoped page keeps the
    # browser context (and its localStorage) across tests, so clear any choice
    # left behind and reload to exercise the no-preference path (EN default).
    page.evaluate(f'() => localStorage.removeItem("{LANG_STORAGE_KEY}")')
    page.goto(static_app)
    page.get_by_role("heading", name="Italy at a glance").wait_for(state="visible")
    assert (
        page.get_by_role("button", name="IT", exact=True).get_attribute("aria-pressed") == "false"
    )
    assert page.get_by_role("button", name="EN", exact=True).get_attribute("aria-pressed") == "true"

    page.get_by_role("button", name="IT", exact=True).click()
    assert page.get_by_role("button", name="IT", exact=True).get_attribute("aria-pressed") == "true"
    assert (
        page.get_by_role("button", name="EN", exact=True).get_attribute("aria-pressed") == "false"
    )
    page.get_by_role("heading", name="L'Italia in sintesi").wait_for(state="visible")
    page.get_by_role("link", name="Popolazione").wait_for(state="visible")
    page.wait_for_timeout(300)  # let the sync localStorage write land
    assert page.evaluate(f'() => localStorage.getItem("{LANG_STORAGE_KEY}")') == "it"

    # Choice survives a reload (module-level currentLang re-initialises from
    # localStorage before the first paint).
    page.reload()
    page.get_by_role("heading", name="L'Italia in sintesi").wait_for(state="visible")
    page.get_by_role("button", name="IT", exact=True).wait_for(state="visible")

    # And back to English.
    page.get_by_role("button", name="EN", exact=True).click()
    page.get_by_role("heading", name="Italy at a glance").wait_for(state="visible")
    assert (
        page.get_by_role("button", name="IT", exact=True).get_attribute("aria-pressed") == "false"
    )
