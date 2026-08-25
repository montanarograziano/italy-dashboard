import * as Plot from "@observablehq/plot";
import { divergingSteps, gridline, inkPrimary, series } from "../theme";
import {
  labelInk,
  pointerRuleX,
  themed,
  thinTicks,
  tipOptions,
} from "./plotTheme";

// Pure functions from ported-query rows (see web/src/queries/climate.ts,
// climateScope.ts and static.ts) to Observable Plot specs. Nothing here
// queries the database or touches the DOM -- that split is what makes these
// testable as plain data-in/spec-out functions and keeps PlotFigure (plot.tsx)
// the one place that does.
//
// Colour comes only from theme.ts's accessors (series/divergingSteps) or from
// a row's own `fill` (a `var(--div-N)` string set by queries/climate.ts's
// withStripeFill) -- never a literal hex here.

type Row = Record<string, unknown>;

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

const year = (d: Row) => Number(d.period);

/** Annual warming trend: the min-max band each year (shaded), the annual mean
 * (thin line) and a 10-year centred rolling average (heavy line) -- all in
 * ONE hue, mirroring band_trend_chart's reasoning in italy_dashboard.components:
 * these are one quantity (a year's temperature) viewed at three levels of
 * detail, not three different series that would each need their own colour.
 *
 * `t_rolling` is `null` at both edges of the series (annualWindowed's
 * incomplete rolling window there -- see that function's own docstring).
 * Plot's line mark skips a null y-value rather than bridging it, which is the
 * same "stop short, don't connect" behaviour `band_trend_chart` relies on
 * (Recharts' `connect_nulls={false}`) -- so the edges are left genuinely
 * open here too, not defaulted to a straight line across the gap.
 */
export function bandTrendSpec(rows: Row[]): Plot.PlotOptions {
  const hue = series(1);
  const fmt = (v: unknown) =>
    v === null || v === undefined ? "n/a" : `${Number(v).toFixed(1)}°C`;
  return themed({
    // `tickSize: 0` drops the little tick-mark dashes, not the tick labels
    // (still rendered as `<text>`) or the y gridlines already on above --
    // it is the only way to also stop them being drawn as `<path>` elements
    // at all. Plot unconditionally unshifts its axis marks to the FRONT of
    // the mark list regardless of the order given here, so the tick dashes
    // are otherwise the FIRST `path` elements in DOM order under this
    // chart's container -- and a purely horizontal (or vertical) tick dash
    // has a zero-height (or zero-width) bounding box, which a real browser
    // correctly treats as not "visible". A selector that resolves to the
    // first DOM match (as a plain, non-strict `path` selector does) would
    // then wait on THAT element forever, never reaching the real data marks
    // a few siblings later -- confirmed empirically (getBoundingClientRect
    // on the first tick was 6x0), not assumed.
    // `tickFormat`: a year is a whole number Plot's default numeric
    // formatter would otherwise group as `1,950` -- see `thresholdSpec`
    // below (the same bug, same fix) and series.tsx's `lineSeriesSpec`,
    // where the plan's final review (F6) first caught it.
    x: { label: "Year", tickFormat: (y: number) => String(y) },
    // No `Plot.ruleY([0])` here, unlike every other spec in this file.
    //
    // A zero rule does not just DRAW a line at zero, it forces 0 into the y
    // domain -- and 0°C is not a meaningful baseline for an absolute
    // temperature, it is an arbitrary point on the Celsius scale. With it, an
    // Italian annual mean series (roughly 12-24°C) was squeezed into the top
    // sixth of the chart as a visually flat line, with five sixths of every
    // card given over to empty space between 0 and the data: the warming this
    // chart exists to show was compressed into near-invisibility. Letting the
    // domain fit the data is what makes the trend and the min-max band
    // legible. `zero: false` is stated explicitly rather than left implicit so
    // a future edit adding a zero rule back has to argue with this comment
    // first.
    y: { label: "Temperature (°C)", zero: false },
    marks: [
      // fillOpacity down from 0.16 to 0.10, and the mean line back to full
      // strength. Once `zero: false` (above) let the domain fit the data, the
      // band stopped being a thin sliver and became the whole plot area -- at
      // 0.16 it read as a solid muddy block in dark mode with the two lines
      // lost inside it, which inverts the intended hierarchy: the ROLLING
      // AVERAGE is the signal, the band is context.
      Plot.areaY(rows, {
        x: year,
        y1: "t_min",
        y2: "t_max",
        fill: hue,
        fillOpacity: 0.1,
      }),
      Plot.line(rows, {
        x: year,
        y: "t_mean",
        stroke: hue,
        strokeWidth: 1,
        strokeOpacity: 0.8,
      }),
      Plot.line(rows, {
        x: year,
        y: "t_rolling",
        stroke: hue,
        strokeWidth: 2.75,
      }),
      pointerRuleX(rows, year),
      Plot.dot(
        rows,
        Plot.pointerX({
          x: year,
          y: "t_mean",
          fill: hue,
          r: 3.5,
          stroke: "var(--plot-background)",
          strokeWidth: 2,
        }),
      ),
      // All four values for the hovered year in one tip -- the whole point of
      // a band chart is the relationship between them, so showing only the
      // series the cursor happens to be nearest would be the less useful half.
      Plot.tip(
        rows,
        Plot.pointerX({
          x: year,
          y: "t_mean",
          title: (d: Row) =>
            [
              String(d.period),
              `Mean: ${fmt(d.t_mean)}`,
              `Range: ${fmt(d.t_min)} to ${fmt(d.t_max)}`,
              `10-yr average: ${fmt(d.t_rolling)}`,
            ].join("\n"),
          ...tipOptions(),
        }),
      ),
    ],
  });
}

/** One city's (or region's) warming stripes: one cell per year, coloured by
 * its own diverging bucket. `rows` must already carry a `fill` field (see
 * queries/climate.ts's `withStripeFill`) -- a `var(--div-N)` string, which
 * Plot recognises as a literal CSS colour (its `isColor` check matches
 * `var(...)`) and therefore renders directly rather than running it through
 * its own categorical colour scale. That is what makes the stripes and the
 * grid below resolve to the SAME diverging ramp `theme.ts` exports, without
 * this file importing a single hex value itself.
 *
 * Plot's `cell` mark renders `<rect>` elements (it extends the same
 * `AbstractBar` bar/cell renders as `barX`/`barY`), which is what
 * `test_the_stripes_resolve_to_distinct_diverging_colours` selects on.
 */
export function stripesSpec(rows: Row[]): Plot.PlotOptions {
  // The axis fix this chart is named for in the bug report: it rendered EVERY
  // year as its own tick label, ~75 of them in a ~1000px card, printed on top
  // of one another into an illegible smear -- and with Plot's default numeric
  // formatter grouping each one as `1,950`, so the smear was of five-character
  // labels rather than four.
  //
  // Two independent defects, two fixes:
  //
  // 1. `tickFormat` -- drop the thousands separator. Same bug and same fix as
  //    `bandTrendSpec`/`thresholdSpec`/`monthHeatmapSpec`; this spec was the
  //    one that never got it.
  // 2. `ticks` -- thin the tick VALUES by hand. `Plot.cell` hardcodes its x
  //    scale to a BAND scale (see the note below on `x: year`), and band
  //    scales are precisely where Plot's automatic tick thinning does not
  //    apply: with no `interval` set, Plot falls through to `data = domain`,
  //    i.e. one tick per category, and `ticks: 10`/`tickSpacing` have no
  //    effect at all. `thinTicks` (plotTheme.ts) picks evenly-spaced years
  //    and keeps the last, so the axis still states the range it covers.
  const years = [...new Set(rows.map(year))].sort((a, b) => a - b);
  return themed({
    x: {
      label: null,
      ticks: thinTicks(years, 6),
      tickFormat: (y: number) => String(y),
    },
    // `grid: false` overrides `themed()`'s y-grid default: this chart's y axis
    // is a single unlabelled band (`axis: null`), so a horizontal gridline
    // would be a line drawn across the stripes for no reason.
    y: { axis: null, grid: false },
    // `x: year` (the numeric accessor above), not `x: "period"`: Plot's
    // `Cell` mark hardcodes its x scale `type` to "band" regardless of the
    // channel's underlying value type, so this changes nothing about the
    // banding -- it only stops Plot's own heuristic from seeing numeric-
    // looking strings on an ordinal scale and logging "some data ... are
    // strings that appear to be numbers" to the console on every render.
    marks: [
      Plot.cell(rows, { x: year, fill: "fill", inset: 0.5 }),
      // Without a tip this chart is unreadable by design: a stripe encodes its
      // anomaly ONLY as a colour bucket, so there is no way to recover the
      // year or the value from the picture. `pointerX` matches the one-cell-
      // per-year geometry -- the stripe is full-height, so x-distance is the
      // only meaningful measure of "nearest".
      Plot.tip(
        rows,
        Plot.pointerX({
          x: year,
          title: (d: Row) => {
            const v = Number(d.anomaly);
            return `${String(d.period)}\n${v > 0 ? "+" : ""}${v.toFixed(2)}\u00b0C vs 1981-2010`;
          },
          ...tipOptions(),
        }),
      ),
    ],
  });
}

// Target pixel width for the narrowest year band in the faceted grid below.
// Plot's default `width` (640) was sized for a single, unfaceted chart; split
// across twelve `fx` facets of 76 year-bands each, that default gives every
// band ~0.64px before `inset` even runs, which is what produced F1 (every
// cell at width="0"). Measured directly against a real render (12 facets,
// 76 bands): the fx/x band scales' combined default padding (paddingInner
// 0.1 on both, paddingOuter 0.1 on the inner x scale) leaves each band at
// ~0.81 * MIN_BAND_PX once margins are subtracted, so 5 lands comfortably
// clear of the ~2px floor (≈4px) with real headroom, not just past it. This
// only holds because `PlotFigure`'s `scrollable` prop (plot.tsx) keeps Plot's
// own `max-width: 100%` from shrinking the resulting wide chart back down to
// its container's width, which would otherwise silently undo this sizing --
// confirmed by measuring the rendered (not just the spec's) pixel width
// before landing on 5.
const MIN_BAND_PX = 5;
const FACETED_MARGIN_LEFT = 40;
const FACETED_MARGIN_RIGHT = 20;

/** Stripes for several cities at once, one Plot mark faceted on `fx` -- the
 * reason Observable Plot was chosen over Recharts for this app: the Reflex
 * app assembles its small-multiples grid by hand from twelve separate
 * charts (italy_dashboard.components.small_multiples), where this is a
 * single mark.
 *
 * `rows` is flat: every city's stripe rows concatenated, each carrying its
 * own `city` field (see pages/Climate.tsx, which builds this from
 * warmingRateRanking + climateStripes -- climate_stripes_grid was
 * deliberately not ported to the query layer for exactly this reason; see
 * that file's own comment).
 *
 * `highlight` (a city name, or `""` to disable -- the same convention
 * `rankingSpec`'s highlight uses, both meant to be driven by the same
 * selected-city value) draws a ring around just that city's panel via
 * `Plot.frame`: passing a literal string (not a field accessor) as a
 * decoration mark's `fx` option restricts that mark to the one facet whose
 * `fx` value equals it -- PROVIDED that mark is included at all. Unlike
 * `rankingSpec`'s `highlight`, which feeds a `stroke` ACCESSOR FUNCTION
 * evaluated per datum (never touching a scale), `Plot.frame({ fx: highlight
 * })` feeds `highlight` straight into the `fx` SCALE's domain -- Plot builds
 * that domain from the union of every mark's `fx` values, literal included.
 * So `""` does not "match nothing and render in zero facets"; it becomes a
 * real 13th domain entry, an unlabelled phantom facet with a heavy
 * `inkPrimary` box drawn around it. A real branch is required instead of a
 * sentinel value.
 */
export function facetedStripesSpec(
  rows: Row[],
  highlight: string = "",
): Plot.PlotOptions {
  const bandsPerCity = new Map<string, number>();
  for (const r of rows) {
    const city = String(r.city);
    bandsPerCity.set(city, (bandsPerCity.get(city) ?? 0) + 1);
  }
  const facetCount = Math.max(1, bandsPerCity.size);
  const maxBandsInAnyFacet = Math.max(1, ...bandsPerCity.values());
  const width =
    FACETED_MARGIN_LEFT +
    FACETED_MARGIN_RIGHT +
    facetCount * maxBandsInAnyFacet * MIN_BAND_PX;

  return themed({
    width,
    marginLeft: FACETED_MARGIN_LEFT,
    marginRight: FACETED_MARGIN_RIGHT,
    fx: { label: null },
    x: { axis: null, grid: false },
    // `grid: false` -- see stripesSpec: `themed()` turns the y grid on for the
    // line/bar charts that want it, and an axis-less cell grid does not.
    y: { axis: null, grid: false },
    marks: [
      // inset: 0 (not stripesSpec's 0.5) -- at this many bands per facet,
      // shaving even a single pixel off each side is the other half of what
      // produced F1's zero-width cells; the faceted grid does not need the
      // single-chart variant's inset because adjacent cells are already
      // visually separated by the gap the diverging fills create.
      Plot.cell(rows, { x: year, fill: "fill", fx: "city", inset: 0 }),
      ...(highlight
        ? [Plot.frame({ fx: highlight, stroke: inkPrimary(), strokeWidth: 3 })]
        : []),
      // LAST in the mark list, not first: Plot renders marks in array order, so
      // a tip declared before the `cell` mark is painted underneath every
      // stripe and is invisible wherever it overlaps the data -- which, in a
      // chart that is nothing but stripes, is everywhere.
      //
      // The x axis is deliberately absent from this grid (no room for year
      // labels in a 76-band facet), which makes this tip the ONLY way to find
      // out which year a stripe is: the small-multiples grid was otherwise a
      // pure texture with no readable value anywhere in it.
      Plot.tip(
        rows,
        Plot.pointerX({
          x: year,
          fx: "city",
          title: (d: Row) => {
            const v = Number(d.anomaly);
            return `${String(d.city)} ${String(d.period)}\n${v > 0 ? "+" : ""}${v.toFixed(2)}\u00b0C vs 1981-2010`;
          },
          ...tipOptions(),
        }),
      ),
    ],
  });
}

/** Daily-maximum histogram, one city's record split into an early and a late
 * window (see queries/static.ts's climateDistributionWindows/climateDistribution).
 * `windows` labels the two curves with the ACTUAL year range they cover
 * (derived per city, never a hardcoded pair -- a stale literal would drift
 * silently every time the record grows by a year), and reshaping into one
 * long array keyed by that label is what gives Plot a real two-entry colour
 * legend instead of two unlabelled curves.
 */
export function distributionSpec(
  rows: Row[],
  windows: [number, number, number, number],
): Plot.PlotOptions {
  const [earlyLo, earlyHi, lateLo, lateHi] = windows;
  const earlyLabel = `${earlyLo}-${earlyHi}`;
  const lateLabel = `${lateLo}-${lateHi}`;
  const long: Row[] = [
    ...rows.map((r) => ({
      period: r.period,
      share: r.early,
      window: earlyLabel,
    })),
    ...rows.map((r) => ({
      period: r.period,
      share: r.late,
      window: lateLabel,
    })),
  ];
  return themed({
    x: { label: "Daily max (°C)" },
    y: { label: "Share of days (%)" },
    color: {
      legend: true,
      domain: [earlyLabel, lateLabel],
      range: [series(1), series(2)],
    },
    marks: [
      Plot.ruleY([0], { stroke: gridline() }),
      Plot.areaY(long, {
        x: "period",
        y: "share",
        fill: "window",
        fillOpacity: 0.28,
        stroke: "window",
        strokeWidth: 2,
      }),
      // Both windows at the hovered temperature in ONE tip: this chart exists
      // to compare the two distributions at the same x, so a tip showing only
      // whichever curve the cursor is nearest would answer the wrong question.
      // Hence the tip is bound to `rows` (the WIDE shape, one row per
      // temperature bin with an `early` and a `late` column) rather than to
      // the long-form `long` array the areas are drawn from.
      pointerRuleX(rows, "period"),
      Plot.tip(
        rows,
        Plot.pointerX({
          x: "period",
          title: (d: Row) =>
            [
              `${Number(d.period).toFixed(0)}\u00b0C daily max`,
              `${earlyLabel}: ${Number(d.early).toFixed(2)}% of days`,
              `${lateLabel}: ${Number(d.late).toFixed(2)}% of days`,
            ].join("\n"),
          ...tipOptions(),
        }),
      ),
    ],
  });
}

/** Hot days, tropical nights and frost days per year -- three counts, one
 * line each, reshaped into long form (`kind`) so Plot's colour scale gives a
 * real legend rather than three unlabelled lines.
 */
export function thresholdSpec(rows: Row[]): Plot.PlotOptions {
  const keys: [string, string][] = [
    ["hot_days", "Hot days"],
    ["tropical_nights", "Tropical nights"],
    ["frost_days", "Frost days"],
  ];
  const colors = [series(2), series(1), series(3)];
  const long: Row[] = keys.flatMap(([key, label]) =>
    rows.map((r) => ({ year: year(r), value: r[key], kind: label })),
  );
  return themed({
    // `tickFormat` -- see `bandTrendSpec` above, the same bug and fix.
    x: { label: "Year", tickFormat: (y: number) => String(y) },
    // Zero IS meaningful here (unlike `bandTrendSpec`'s temperature axis):
    // these are counts of days, and "no frost days at all" is a real and
    // important reading, so the zero rule stays and the domain includes it.
    y: { label: "Days / year" },
    color: {
      legend: true,
      domain: keys.map(([, label]) => label),
      range: colors,
    },
    marks: [
      Plot.ruleY([0], { stroke: gridline() }),
      Plot.line(long, { x: "year", y: "value", stroke: "kind" }),
      // All three counts for the hovered year in one tip, read off the WIDE
      // rows rather than the long-form array -- same reasoning as
      // `distributionSpec`: the comparison between the three series at one
      // year is the question, so selecting only the nearest series would
      // answer less than the reader asked.
      pointerRuleX(rows, year),
      Plot.tip(
        rows,
        Plot.pointerX({
          x: year,
          title: (d: Row) =>
            [
              String(d.period),
              ...keys.map(
                ([key, label]) => `${label}: ${Number(d[key]).toFixed(0)}`,
              ),
            ].join("\n"),
          ...tipOptions(),
        }),
      ),
    ],
  });
}

/** Fastest-warming cities, cross-city and NEVER filtered by the selected city
 * (see pages/Climate.tsx's docstring for why: filtering a ranking to one city
 * destroys the comparison it exists to show). `highlight` (a city name, or
 * `""` to disable) outlines that city's own bar instead -- the ranking's
 * counterpart to `facetedStripesSpec`'s ring, both ACKNOWLEDGING the
 * selection rather than filtering to it, per `h_bar_chart`'s docstring.
 */
export function rankingSpec(
  rows: Row[],
  highlight: string = "",
): Plot.PlotOptions {
  return themed({
    marginLeft: 110,
    // Room for the value labels below, which would otherwise be clipped at the
    // frame edge.
    marginRight: 60,
    x: { label: "°C / decade", grid: true },
    y: { label: null, domain: rows.map((r) => String(r.name)) },
    marks: [
      Plot.ruleX([0], { stroke: gridline() }),
      Plot.barX(rows, {
        x: "value",
        y: "name",
        fill: series(1),
        stroke: (d: Row) =>
          String(d.name) === highlight ? inkPrimary() : "none",
        strokeWidth: 2,
      }),
      // The number at the end of each bar. This ranking spans roughly
      // 0.30-0.35°C/decade across twenty cities, so every bar is within ~15%
      // of every other and the lengths alone are visually indistinguishable --
      // the chart looked like a solid block. The labels are what make it an
      // actual ranking rather than a texture.
      // TWO decimals, not three. The query rounds this value to 2 dp in SQL
      // (`ROUND(10.0 * regr_slope(...), 2)`), so a third digit is always a
      // literal trailing zero -- fabricated precision. At 2 dp several cities
      // genuinely tie at 0.36, which is the honest reading: this data cannot
      // rank them apart, and a fake third digit would have implied it could.
      Plot.text(rows, {
        x: "value",
        y: "name",
        text: (d: Row) => Number(d.value).toFixed(2),
        textAnchor: "start",
        dx: 6,
        fill: labelInk(),
      }),
      // `pointerY`: a horizontal bar chart selects by ROW, so pointing
      // anywhere along a band -- including past the end of a short bar --
      // must select that city.
      Plot.tip(
        rows,
        Plot.pointerY({
          x: "value",
          y: "name",
          title: (d: Row) =>
            `${String(d.name)}\n${Number(d.value).toFixed(2)}\u00b0C / decade`,
          ...tipOptions(),
        }),
      ),
    ],
  });
}

/** Year x month anomaly grid, using Plot's `cell` mark -- which Recharts has
 * no equivalent of at all, so this chart does not exist in the Reflex app.
 * `rows` come wide (one row per year, columns `m1`..`m12`; see
 * queries/climate.ts's climateMonthHeatmap) and are reshaped to long form
 * here, one entry per OBSERVED month.
 *
 * A month that has not happened yet (the partial running year's tail) comes
 * back `null` from the query, and is filtered out of the long-form data
 * entirely rather than defaulting to 0 -- a 0 would render as "no anomaly
 * that month", a claim about the climate, when the true state is "no
 * observation yet", a claim about the data. Filtering means Plot's `cell`
 * mark never draws that (year, month) cell at all, which is the "absent",
 * not "zero", the brief requires.
 *
 * The colour scale is a `quantize` (n equal-width bins across the actual
 * observed range, mapped onto `theme.ts`'s diverging steps) rather than a
 * copy of queries/climate.ts's `divergingBucket`: that bucketing is tuned to
 * the ANNUAL stripes' own fixed half-range, and this chart -- monthly, and
 * with no Reflex counterpart to match -- has no fixed range of its own to
 * mirror. Colour still comes only from `theme.ts` (`divergingSteps()`), just
 * scaled to this chart's own data instead of a borrowed constant.
 */
export function monthHeatmapSpec(rows: Row[]): Plot.PlotOptions {
  const long: { year: number; month: number; anomaly: number }[] = [];
  for (const row of rows) {
    const y = Number(row.period);
    for (let m = 1; m <= 12; m++) {
      const value = row[`m${m}`];
      if (value === null || value === undefined) continue;
      long.push({ year: y, month: m, anomaly: Number(value) });
    }
  }
  const maxAbs =
    long.reduce((acc, d) => Math.max(acc, Math.abs(d.anomaly)), 0) || 1;
  const steps = divergingSteps();
  const observedYears = [...new Set(long.map((d) => d.year))].sort(
    (a, b) => a - b,
  );
  return themed({
    marginLeft: 50,
    x: {
      label: null,
      domain: MONTHS.map((_, i) => i + 1),
      tickFormat: (m: number) => MONTHS[m - 1] ?? String(m),
    },
    // `tickFormat` -- same bug as `bandTrendSpec`/`thresholdSpec` above,
    // found on this axis too by checking rather than assuming `Plot.cell`'s
    // forced band scale (see `stripesSpec`'s comment on that) was exempt:
    // it renders its own `<text>` tick labels through the same numeric
    // formatter regardless of the underlying scale type. Confirmed by
    // rendering this chart before and after: `1,950 ... 2,026` becomes
    // `1950 ... 2026`.
    // `ticks` -- the same band-scale thinning `stripesSpec` needs, on the y
    // axis this time: this grid is one row per year over ~75 years, and
    // `Plot.cell` forces a band scale, so without thinning Plot emits one tick
    // label per year and they overlap into a smear exactly as the stripes did.
    // `tickSpacing`/`ticks: <count>` do nothing on a band scale (Plot falls
    // through to `data = domain`), so the values are thinned by hand.
    y: {
      label: "Year",
      ticks: thinTicks(observedYears, 14),
      tickFormat: (y: number) => String(y),
      // No gridlines between the cells: the cells tile the plot area with no
      // gaps, so a grid would only ever draw on top of the data.
      grid: false,
    },
    color: {
      type: "quantize",
      n: steps.length,
      domain: [-maxAbs, maxAbs],
      range: steps,
      legend: true,
      // Keep the continuous ramp, but show only a handful of rounded labels.
      // Plot otherwise places every quantize boundary on one short strip and
      // the values overlap into an unreadable block.
      ticks: 5,
      tickFormat: (value: number) => `${value > 0 ? "+" : ""}${value.toFixed(1)}°`,
      label: "Anomaly (°C)",
    },
    marks: [
      Plot.cell(long, { x: "month", y: "year", fill: "anomaly", inset: 0.5 }),
      // A heatmap cell encodes its value only as a colour bucket, so without a
      // tip there is no way to read the actual anomaly for a given month.
      // Plain `Plot.pointer` (not `pointerX`/`pointerY`): both axes are
      // categorical data here, so the nearest cell in 2-D is the right target.
      Plot.tip(
        long,
        Plot.pointer({
          x: "month",
          y: "year",
          title: (d: { year: number; month: number; anomaly: number }) =>
            `${MONTHS[d.month - 1] ?? d.month} ${d.year}\n${d.anomaly > 0 ? "+" : ""}${d.anomaly.toFixed(2)}\u00b0C`,
          ...tipOptions(),
        }),
      ),
    ],
  });
}
