import * as Plot from "@observablehq/plot";
import { gridline } from "../theme";
import { tr } from "../i18n";
import { pointerRuleX, themed, tipOptions } from "./plotTheme";

// Generic time-series chart specs, shared by every page whose query returns
// one row per period plus one or more numeric columns (economy's inflation,
// labor's unemployment, population's residents/foreign share -- and, per the
// plan, whatever Tasks 3-4 add on top). Pure functions from rows to a Plot
// spec, same split as charts/climate.tsx: nothing here queries the database
// or touches the DOM, which is what makes PlotFigure (plot.tsx) the only
// place that does either.
//
// Colour always comes from a caller-supplied `SeriesDef.color` (itself read
// from theme.ts's `series()` at the call site) -- never a literal hex here.
// Axis ink, typography, gridline colour, tick sizing and margins all come
// from `themed()` (plotTheme.ts) rather than being restated per spec.

type Row = Record<string, unknown>;

/** One named, coloured column to plot against the shared x-axis. */
export interface SeriesDef {
  key: string;
  label: string;
  color: string;
}

export interface LineSeriesOptions {
  series: SeriesDef[];
  /** Column holding the x value. Defaults to "period", the field name every
   * ported time-series query (inflationSeries, unemploymentSeries, ...)
   * uses. */
  xKey?: string;
  xLabel?: string;
  yLabel?: string;
  /** Decimal places shown in the hover tip. Each caller's unit has its own
   * natural precision -- a percentage point (inflation, unemployment, foreign
   * share) reads as 1-2 decimals, a resident headcount as 0. */
  valueDecimals?: number;
  /** Suffix appended to the tip's value, e.g. "%" -- the unit belongs next to
   * the number in a tooltip, where there is no axis label in view to carry
   * it. */
  valueSuffix?: string;
  /** Whether zero is a meaningful baseline for this quantity. `true` (the
   * default) keeps the `Plot.ruleY([0])` zero line, which also forces 0 into
   * the y domain -- correct for a rate that can go negative (inflation) or a
   * count. `false` drops it, letting the domain fit the data: see
   * `bandTrendSpec` in climate.tsx for the same distinction and why it
   * matters (a 20-24 degree C series plotted from 0 is a flat line in the top
   * 15% of the chart). */
  zeroBaseline?: boolean;
}

const toNumber = (row: Row, key: string): number => Number(row[key]);

/** A missing/null value stays null (Plot's line mark skips a null y rather
 * than bridging across it -- see bandTrendSpec's own note on this in
 * climate.tsx), it is never coerced to 0, which would claim "zero" about a
 * period the data genuinely has nothing for. */
const toNumberOrNull = (row: Row, key: string): number | null => {
  const value = row[key];
  return value === null || value === undefined ? null : Number(value);
};

/** One or more named series against a shared period axis: economy's single
 * inflation line, labor's selected-vs-national pair, population's residents
 * or foreign-share line.
 *
 * Reshapes `rows` (one row per period, one column per series) into long
 * form, the same technique `thresholdSpec` (climate.tsx) uses for its three
 * named counts -- a single `Plot.line` call then gets a real colour legend
 * for free from Plot's own colour scale when there is more than one series,
 * instead of one un-labelled `Plot.line` call per column. With exactly one
 * series there is nothing to legend, so `color` is left undefined and the
 * literal `SeriesDef.color` is passed straight to `stroke` as a constant
 * (Plot's `isColor` check recognises it as a literal, not a column
 * reference, the same mechanism `rankingSpec`'s `fill: series(1)` relies
 * on).
 *
 * Interaction: a `Plot.dot` + `Plot.tip` pair under `Plot.pointerX`, plus a
 * `pointerRuleX` guide line. `pointerX` (not plain `pointer`) is the right transform
 * for a time series -- it selects on x-distance alone, so the nearest YEAR is
 * found wherever in the card's height the cursor happens to be, rather than
 * requiring the reader to trace the line itself. The dot is what makes the
 * selection visible; without it the tip appears with nothing marking which
 * datum it describes.
 */
export function lineSeriesSpec(
  rows: Row[],
  opts: LineSeriesOptions,
): Plot.PlotOptions {
  const xKey = opts.xKey ?? "period";
  const multi = opts.series.length > 1;
  const decimals = opts.valueDecimals ?? 1;
  const suffix = opts.valueSuffix ?? "";
  const zeroBaseline = opts.zeroBaseline ?? true;
  const long = opts.series.flatMap((def) =>
    rows.map((row) => ({
      x: toNumber(row, xKey),
      value: toNumberOrNull(row, def.key),
      label: def.label,
    })),
  );

  // Only the points the pointer transform can actually select. A null value
  // has no y position, so leaving it in would let `pointerX` "select" a year
  // whose tip then reads `null` -- a gap in the data must stay a gap in the
  // interaction too.
  const selectable = long.filter((d) => d.value !== null);

  return themed({
    // `tickFormat`: every caller plots a year on this axis (`xKey` always
    // defaults to "period", never overridden -- see the plan's final review,
    // F6), and Plot's default numeric tick formatter applies thousands
    // grouping to any continuous scale, rendering years as `2,024` rather
    // than `2024`. `String(y)` is the whole fix: a year is never fractional,
    // so nothing is lost by skipping Plot's default formatter entirely.
    x: { label: opts.xLabel ?? tr("Year"), tickFormat: (y: number) => String(y) },
    y: { label: opts.yLabel },
    color: multi
      ? {
          legend: true,
          domain: opts.series.map((s) => s.label),
          range: opts.series.map((s) => s.color),
        }
      : undefined,
    marks: [
      ...(zeroBaseline ? [Plot.ruleY([0], { stroke: gridline() })] : []),
      // strokeWidth 2, up from Plot's 1.5 default. Not cosmetic: every
      // categorical colour in this palette sits UNDER 4.5:1 against its own
      // card surface (measured: light 2.74-4.30:1, dark 3.63-4.75:1), and
      // WCAG's 3:1 non-text minimum assumes a chunky shape rather than a hairline
      // stroke. The hues themselves are not changed here on purpose -- they were
      // selected by a colourblind-separation validator (see
      // italy_dashboard/palette.py) that is no longer available on this machine,
      // so re-picking them blind would trade a measurable contrast gain for an
      // unverifiable regression in colourblind distinctness. A wider stroke buys
      // real legibility at zero risk to that property.
      Plot.line(long, {
        x: "x",
        y: "value",
        stroke: multi ? "label" : opts.series[0]!.color,
        strokeWidth: 2,
      }),
      pointerRuleX(selectable, "x"),
      // The selected point. `fill` carries the series identity (a channel
      // reference when multi, a literal colour when single -- Plot's `isColor`
      // check tells them apart), and `stroke` is deliberately NOT used for
      // that: it is spent on a halo in the card colour so the marker reads as
      // sitting ON TOP of the line rather than as a kink in it. An earlier
      // version of this passed `stroke: "label"` for the multi case and then
      // overwrote it with the halo two lines later, silently dropping the
      // series colour from the marker -- fill is the channel that has to
      // carry it.
      Plot.dot(
        selectable,
        Plot.pointerX({
          x: "x",
          y: "value",
          fill: multi ? "label" : opts.series[0]!.color,
          r: 3.5,
          stroke: "var(--plot-background)",
          strokeWidth: 2,
        }),
      ),
      Plot.tip(
        selectable,
        Plot.pointerX({
          x: "x",
          y: "value",
          title: (d: { x: number; value: number; label: string }) =>
            [
              String(d.x),
              `${multi ? `${d.label}: ` : ""}${d.value.toFixed(decimals)}${suffix}`,
            ].join("\n"),
          ...tipOptions(),
        }),
      ),
    ],
  });
}

// A `stackedAreaSpec` companion to `lineSeriesSpec` used to live here (Task 2
// of the static-app-remaining-pages plan built it on the promise that Tasks
// 3-4 would reuse it for a "compare shares of a whole" chart). Neither did
// -- population's foreign-share chart is a single series (a % of the total,
// not several parts summing to one), which a stacked area has nothing to
// stack against, and the Reflex reference (`population.py`) draws it as a
// plain line for the same reason -- so it was 22 lines of Plot spec with
// zero call sites and an untested behavioural decision (0-coercion for
// missing values, deliberately different from this file's other spec).
// Deleted per the plan's final review (F5) rather than kept "for later":
// add it back the day a real stacked-composition chart needs it, with a
// test that actually exercises the 0-coercion this time.
