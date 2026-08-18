import * as Plot from "@observablehq/plot";
import { divergingSteps, gridline, inkPrimary, series } from "../theme";

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
  return {
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
    x: { label: "Year", tickSize: 0 },
    y: { label: "Temperature (°C)", grid: true, tickSize: 0 },
    marks: [
      Plot.areaY(rows, { x: year, y1: "t_min", y2: "t_max", fill: hue, fillOpacity: 0.16 }),
      Plot.line(rows, { x: year, y: "t_mean", stroke: hue, strokeWidth: 1.25 }),
      Plot.line(rows, { x: year, y: "t_rolling", stroke: hue, strokeWidth: 2.75 }),
      Plot.ruleY([0], { stroke: gridline() }),
    ],
  };
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
  return {
    x: { label: null },
    y: { axis: null },
    marks: [Plot.cell(rows, { x: "period", fill: "fill", inset: 0.5 })],
  };
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
export function facetedStripesSpec(rows: Row[], highlight: string = ""): Plot.PlotOptions {
  const bandsPerCity = new Map<string, number>();
  for (const r of rows) {
    const city = String(r.city);
    bandsPerCity.set(city, (bandsPerCity.get(city) ?? 0) + 1);
  }
  const facetCount = Math.max(1, bandsPerCity.size);
  const maxBandsInAnyFacet = Math.max(1, ...bandsPerCity.values());
  const width =
    FACETED_MARGIN_LEFT + FACETED_MARGIN_RIGHT + facetCount * maxBandsInAnyFacet * MIN_BAND_PX;

  return {
    width,
    marginLeft: FACETED_MARGIN_LEFT,
    marginRight: FACETED_MARGIN_RIGHT,
    fx: { label: null },
    x: { axis: null },
    y: { axis: null },
    marks: [
      // inset: 0 (not stripesSpec's 0.5) -- at this many bands per facet,
      // shaving even a single pixel off each side is the other half of what
      // produced F1's zero-width cells; the faceted grid does not need the
      // single-chart variant's inset because adjacent cells are already
      // visually separated by the gap the diverging fills create.
      Plot.cell(rows, { x: "period", fill: "fill", fx: "city", inset: 0 }),
      ...(highlight ? [Plot.frame({ fx: highlight, stroke: inkPrimary(), strokeWidth: 3 })] : []),
    ],
  };
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
    ...rows.map((r) => ({ period: r.period, share: r.early, window: earlyLabel })),
    ...rows.map((r) => ({ period: r.period, share: r.late, window: lateLabel })),
  ];
  return {
    x: { label: "Daily max (°C)" },
    y: { label: "Share of days (%)", grid: true },
    color: { legend: true, domain: [earlyLabel, lateLabel], range: [series(1), series(2)] },
    marks: [
      Plot.areaY(long, {
        x: "period",
        y: "share",
        fill: "window",
        fillOpacity: 0.28,
        stroke: "window",
        strokeWidth: 2,
      }),
      Plot.ruleY([0], { stroke: gridline() }),
    ],
  };
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
  return {
    x: { label: "Year" },
    y: { label: "Days / year", grid: true },
    color: { legend: true, domain: keys.map(([, label]) => label), range: colors },
    marks: [
      Plot.line(long, { x: "year", y: "value", stroke: "kind" }),
      Plot.ruleY([0], { stroke: gridline() }),
    ],
  };
}

/** Fastest-warming cities, cross-city and NEVER filtered by the selected city
 * (see pages/Climate.tsx's docstring for why: filtering a ranking to one city
 * destroys the comparison it exists to show). `highlight` (a city name, or
 * `""` to disable) outlines that city's own bar instead -- the ranking's
 * counterpart to `facetedStripesSpec`'s ring, both ACKNOWLEDGING the
 * selection rather than filtering to it, per `h_bar_chart`'s docstring.
 */
export function rankingSpec(rows: Row[], highlight: string = ""): Plot.PlotOptions {
  return {
    marginLeft: 110,
    x: { label: "°C / decade", grid: true },
    y: { label: null, domain: rows.map((r) => String(r.name)) },
    marks: [
      Plot.ruleX([0], { stroke: gridline() }),
      Plot.barX(rows, {
        x: "value",
        y: "name",
        fill: series(1),
        stroke: (d: Row) => (String(d.name) === highlight ? inkPrimary() : "none"),
        strokeWidth: 2,
      }),
    ],
  };
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
  const maxAbs = long.reduce((acc, d) => Math.max(acc, Math.abs(d.anomaly)), 0) || 1;
  const steps = divergingSteps();
  return {
    marginLeft: 50,
    x: {
      label: null,
      domain: MONTHS.map((_, i) => i + 1),
      tickFormat: (m: number) => MONTHS[m - 1] ?? String(m),
    },
    y: { label: "Year" },
    color: {
      type: "quantize",
      n: steps.length,
      domain: [-maxAbs, maxAbs],
      range: steps,
      legend: true,
      label: "Anomaly (°C)",
    },
    marks: [Plot.cell(long, { x: "month", y: "year", fill: "anomaly", inset: 0.5 })],
  };
}
