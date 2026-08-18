import pytest

pytestmark = pytest.mark.browser


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
    page.goto(static_app)
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
    page.goto(static_app)
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
    """The default landing view must reach real data, not sit on a spinner.

    Asserting the page merely 'loaded' would pass while every chart is empty,
    which is what a broken parquet path looks like.
    """
    page.goto(static_app)
    page.wait_for_selector("[data-testid='climate-annual'] path", timeout=30_000)
    marks = page.eval_on_selector_all("[data-testid='climate-annual'] path", "els => els.length")
    assert marks > 0, "no marks drawn in the annual series chart"


def test_the_stripes_grid_renders_visible_cells(page, static_app):
    """F1: `facetedStripesSpec` used to leave every one of its 912 cells at
    `width="0"` -- no explicit `width` (Plot defaults to 640), so 12 `fx`
    facets of 76 year-bands each divided down to ~0.64px per band before
    `inset: 0.5` (a full pixel removed) clamped every one to zero. The card
    was a blank box with 12 overlapping labels under it, on the default
    landing view of the only page in this deploy.

    Deliberately does NOT `wait_for_selector` with the default `visible`
    state: a zero-width `<rect>` is still attached to the DOM, but Playwright
    refuses to call it "visible", so waiting on visibility is exactly the
    Plot/Playwright interaction Task 2's comment at climate.tsx:55-61 already
    diagnosed for the axis tick dashes -- it would HANG for the full timeout
    rather than fail. `state="attached"` only waits for the elements to
    exist; the actual check is the geometry assertion below.
    """
    page.goto(static_app)
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
    page.goto(static_app)
    page.wait_for_selector("[data-testid='climate-grid'] rect", state="attached", timeout=30_000)
    labels = page.eval_on_selector_all(
        "[data-testid='climate-grid'] [aria-label='fx-axis tick label'] text",
        "els => els.map(e => e.textContent)",
    )
    assert labels.count("") == 0, f"a blank fx facet label is present: {labels}"
    assert len(labels) == 12, (
        f"expected exactly 12 city facets at Italia scope, got {len(labels)}: {labels}"
    )
