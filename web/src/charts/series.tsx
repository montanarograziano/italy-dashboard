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
    x: { label: opts.xLabel ?? "Year", tickSize: 0 },
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

export interface StackedAreaOptions {
  series: SeriesDef[];
  xKey?: string;
  xLabel?: string;
  yLabel?: string;
}

/** Several named series stacked into one area chart (e.g. a composition
 * over time), sharing `SeriesDef` with `lineSeriesSpec` so a caller can
 * switch between "compare levels" (lines) and "compare shares of a whole"
 * (stacked area) without redefining its series list.
 *
 * A missing value becomes 0 here, unlike `lineSeriesSpec`'s null-preserving
 * `toNumberOrNull`: `Plot.stackY` accumulates each band from the ones below
 * it, and a `null` band would break every band stacked on top of it for
 * that period, not just leave its own slice blank. 0 is the correct "this
 * series contributed nothing that period" for a stack; it would be the
 * wrong "flat line at zero" for a line chart, which is why the two
 * functions do not share one coercion helper.
 */
export function stackedAreaSpec(rows: Row[], opts: StackedAreaOptions): Plot.PlotOptions {
  const xKey = opts.xKey ?? "period";
  const long = opts.series.flatMap((def) =>
    rows.map((row) => ({
      x: toNumber(row, xKey),
      value: row[def.key] === null || row[def.key] === undefined ? 0 : Number(row[def.key]),
      label: def.label,
    })),
  );
  return {
    // tickSize: 0 -- see lineSeriesSpec's comment above on why this matters
    // for both the axis rendering and Playwright's `path` waits in the tests
    // that exercise these specs.
    x: { label: opts.xLabel ?? "Year", tickSize: 0 },
    y: { label: opts.yLabel, grid: true, tickSize: 0 },
    color: { legend: true, domain: opts.series.map((s) => s.label), range: opts.series.map((s) => s.color) },
    marks: [
      Plot.areaY(long, Plot.stackY({ x: "x", y: "value", fill: "label" })),
      Plot.ruleY([0], { stroke: gridline() }),
    ],
  };
}
