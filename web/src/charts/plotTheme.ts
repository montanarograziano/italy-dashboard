import * as Plot from "@observablehq/plot";
import { axis, gridline, inkMuted, inkSecondary, surface } from "../theme";

// One place where every chart spec in this app gets its chrome: typography,
// axis ink, tip styling and the two Plot defaults that are actively wrong for
// a themed dashboard. Every `*Spec` function in charts/ returns its spec
// through `themed()`, so no page needs to remember to apply this.
//
// This is chrome only -- nothing here touches a scale domain, a mark or a
// datum. Data decisions stay in the individual spec functions.

/** Plot's own default font is 10px system-ui, sized for a notebook cell, not
 * for a card in a 16px-body page: at 10px the tick labels were both too small
 * to read comfortably and too tightly packed to avoid collisions. 12px is the
 * smallest size that still leaves the axis subordinate to the card title. */
const FONT_SIZE = 12;

/** Plot injects a ZERO-SPECIFICITY stylesheet into every SVG it renders
 * (`:where(.plot-xxxxx) { --plot-background: white; ... }`, src/plot.js), and
 * `--plot-background` is HARDCODED to white there. It is not decoration: it is
 * the fill of every `Plot.tip` box and the halo behind `Plot.crosshair`'s
 * value labels. Left alone, every tooltip in this app renders as a white box
 * with near-white text on it in dark mode -- unreadable, and invisible in a
 * screenshot test that only checks the tip EXISTS.
 *
 * An inline `style` (which is what Plot's `style` option becomes, via its
 * `applyInlineStyles`) always beats a `:where(...)` rule, so redefining the
 * custom property here is the whole fix -- one declaration, every tip and
 * crosshair in both modes.
 *
 * `background: "transparent"` is the other half: Plot paints no background of
 * its own, but making that explicit lets the `Card` surface show through
 * rather than the chart carrying its own subtly-different rectangle.
 *
 * `color` drives every axis tick label, axis line and axis title, all of which
 * Plot resolves through `currentColor`. Inherited, that meant `inkPrimary()`
 * -- chart chrome shouting exactly as loudly as the card's own heading. The
 * dedicated `axis()` token is deliberately dimmer while still clearing WCAG's
 * 3:1 non-text floor (see italy_dashboard/palette.py's AXIS_*).
 */
function chromeStyle(): Record<string, string> {
  return {
    background: "transparent",
    color: axis(),
    "--plot-background": surface(),
    fontFamily: "inherit",
    fontSize: `${FONT_SIZE}px`,
  };
}

/** Shared `Plot.tip` options: the hover card's own styling.
 *
 * `fill` is set explicitly rather than left to `--plot-background` above: the
 * tip should read as a raised object over the chart, and on the light theme
 * `surface()` IS the card background, so a tip relying on it alone would be a
 * borderless white box on white with only its (0.2-opacity by default) stroke
 * to define it. `stroke` uses the card-edge token for the same reason.
 */
export function tipOptions(): Plot.TipOptions {
  return {
    fill: surface(),
    stroke: gridline(),
    strokeOpacity: 1,
    fontSize: FONT_SIZE,
    textPadding: 9,
    // A real drop shadow, so the tip separates from a chart it overlaps even
    // where the underlying marks are the same value as its own fill.
    pathFilter: "drop-shadow(0 2px 6px rgba(0,0,0,0.28))",
  };
}

/** A vertical guide line following the pointer, to pair with a `pointerX` tip
 * on a dense time series: without it the tip gives you the value but not WHICH
 * x it belongs to, which on a 75-year axis carrying ~10 tick labels is most of
 * the question.
 *
 * Deliberately NOT `Plot.crosshairX`, which was tried first and is wrong here
 * on three counts, all stemming from the value labels it prints outside the
 * frame:
 *
 * 1. It formats them with the text mark's DEFAULT numeric formatter, so a year
 *    renders as `2,004` -- the same thousands-grouping bug every axis in this
 *    app has an explicit `tickFormat` to defeat. There is no way to fix it:
 *    `crosshair` derives its text channel through an internal `initializer`
 *    (marks/crosshair.js's `textChannel`) and forwards none of the text mark's
 *    formatting options, so no option passed in can reach it.
 * 2. The labels are positioned over the axis, where they collided with the
 *    real tick labels underneath -- two overlapping numbers in slightly
 *    different formats.
 * 3. They are redundant: the tip already states the year and every value, so
 *    the crosshair was re-printing what was on screen 40px away.
 *
 * A bare `ruleX` under the same `pointerX` transform keeps the one thing that
 * was actually useful -- the vertical line locating the selected x -- and
 * drops all three problems. Fewer marks, less code, nothing lost.
 */
// `Plot.ChannelValueSpec` rather than a hand-written `string | ((d) => unknown)`:
// callers pass either a column name ("x", "period") or an accessor function
// (climate.tsx's `year`), and that is exactly the union Plot already exports for
// a channel. Spelling it by hand got the function case wrong -- Plot's accessor
// signature is `(d: any, i: number) => any`, so a `(d: never) => unknown` is not
// assignable to it.
export function pointerRuleX(
  data: readonly unknown[],
  x: Plot.ChannelValueSpec,
): Plot.RuleX {
  return Plot.ruleX(
    data,
    Plot.pointerX({
      x,
      stroke: inkMuted(),
      strokeOpacity: 0.55,
      strokeWidth: 1,
    }),
  );
}

/** Merge this app's chrome into a spec built by a `*Spec` function.
 *
 * Merges rather than overwrites, in three places that all had real bugs
 * waiting in a naive `{...spec, style, x: {...}}`:
 *
 * - `style`: a caller's own style keys win, so a chart that needs something
 *   specific is never silently overridden by this file.
 * - `x`/`y`: the caller's axis options are spread OVER the shared defaults, so
 *   a spec that sets `grid`, `label`, `tickFormat` or `axis: null` keeps them.
 *   Only the keys it does not mention (the gridline colour, tick size) come
 *   from here.
 * - `color`: untouched, and not re-spread either -- only `style`/`x`/`y` are
 *   destructured out, so `rest` already carries `color` (and `marks`, `width`,
 *   `fx`, ...) through verbatim. Legends keep their own colour semantics.
 *
 * `tickSize: 0` as a shared default is load-bearing beyond looks: a purely
 * horizontal/vertical Plot axis tick dash has a zero-height/zero-width
 * bounding box and is unconditionally the FIRST `<path>` in the rendered SVG,
 * which makes a plain Playwright `path` wait resolve to a never-"visible"
 * element and hang for its full timeout. Four separate spec files in this app
 * had each rediscovered that and set `tickSize: 0` by hand (with a long
 * comment each); it is a default here instead.
 */
export function themed(spec: Plot.PlotOptions): Plot.PlotOptions {
  const { style, x, y, ...rest } = spec;
  return {
    ...rest,
    // Plot's defaults are 20/30 (right/bottom) and leave an axis label
    // clipped at the frame edge; the extra room is also what keeps a tip
    // anchored near the edge from being cut off.
    marginRight: spec.marginRight ?? 24,
    marginBottom: spec.marginBottom ?? 34,
    // Plot's own grid colour is `currentColor` at 0.1 opacity, i.e. derived
    // from the axis ink -- close enough to the tick labels that the grid
    // competed with them. The dedicated `gridline()` token is fainter.
    // Applied via the y-scale default below rather than the top-level `grid`
    // shorthand, which would also switch the x grid on for band-scale charts
    // (the stripes, the heatmap) where a vertical line per category is pure
    // chartjunk.
    grid: false,
    style: {
      ...chromeStyle(),
      ...(style as Record<string, string> | undefined),
    },
    x: { tickSize: 0, ...x },
    y: { tickSize: 0, grid: gridline(), ...y },
  };
}

/** Axis-label ink for a chart title/label rendered as a Plot text mark rather
 * than an axis (the ranking charts' end-of-bar value labels). Brighter than
 * `axis()` because it IS data, not chrome. */
export function labelInk(): string {
  return inkSecondary();
}

/** Thin an ordinal/band axis down to at most `max` evenly-spaced ticks.
 *
 * Band scales are the trap in Plot's tick logic: `tickSpacing` (and the
 * `inferTickCount` path behind it) only applies to CONTINUOUS scales. For an
 * ordinal scale with no `interval`, Plot falls through to `data = domain` --
 * i.e. EVERY category gets a tick, with no thinning at all. That is what
 * rendered 75 year labels on top of each other in the warming-stripes chart,
 * and no amount of `ticks`/`tickSpacing` fixes it; the tick VALUES have to be
 * thinned by hand and handed to the axis.
 *
 * Returns the values to pass as `ticks`, keeping the first and last so the
 * axis still states the range it covers.
 */
export function thinTicks<T>(domain: readonly T[], max: number): T[] {
  if (domain.length <= max) return [...domain];
  const step = Math.ceil(domain.length / max);
  const kept = domain.filter((_, i) => i % step === 0);
  const last = domain.at(-1)!;
  if (kept.at(-1) !== last) kept.push(last);
  return kept;
}
