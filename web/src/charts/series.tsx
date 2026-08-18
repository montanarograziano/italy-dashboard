import * as Plot from "@observablehq/plot";
import { gridline } from "../theme";

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
 */
export function lineSeriesSpec(rows: Row[], opts: LineSeriesOptions): Plot.PlotOptions {
  const xKey = opts.xKey ?? "period";
  const multi = opts.series.length > 1;
  const long = opts.series.flatMap((def) =>
    rows.map((row) => ({
      x: toNumber(row, xKey),
      value: toNumberOrNull(row, def.key),
      label: def.label,
    })),
  );
  return {
    // `tickSize: 0` on both axes: see climate.tsx's bandTrendSpec for the
    // full diagnosis -- Plot's axis tick dashes are unconditionally the
    // FIRST `path` elements in DOM order, and a purely horizontal/vertical
    // tick dash has a zero-height/zero-width bounding box. A Playwright
    // `wait_for_selector` on a plain `path` selector resolves to that first,
    // never-visible element and hangs for the full timeout rather than ever
    // reaching a real data mark a few siblings later -- confirmed here: the
    // element count was already correct (26/21 `path`s) while the wait still
    // timed out, the same failure mode that comment documents.
    // `tickFormat`: every caller plots a year on this axis (`xKey` always
    // defaults to "period", never overridden -- see the plan's final
    // review, F6), and Plot's default numeric tick formatter applies
    // thousands grouping to any continuous scale, rendering years as
    // `2,024` rather than `2024`. `String(y)` is the whole fix: a year is
    // never fractional, so nothing is lost by skipping Plot's default
    // formatter entirely.
    x: { label: opts.xLabel ?? "Year", tickSize: 0, tickFormat: (y: number) => String(y) },
    y: { label: opts.yLabel, grid: true, tickSize: 0 },
    color: multi
      ? { legend: true, domain: opts.series.map((s) => s.label), range: opts.series.map((s) => s.color) }
      : undefined,
    marks: [
      Plot.line(long, { x: "x", y: "value", stroke: multi ? "label" : opts.series[0]!.color }),
      Plot.ruleY([0], { stroke: gridline() }),
    ],
  };
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
