import * as Plot from "@observablehq/plot";
import { gridline } from "../theme";

type Row = Record<string, unknown>;

export interface HBarOptions {
  /** Axis label for the value (x) channel -- each caller's unit differs
   * (offenders, convictions, rate per 1,000), unlike climate.tsx's
   * `rankingSpec`, whose "°C / decade" label is specific to that one chart. */
  xLabel?: string;
  color: string;
}

/** Horizontal ranking/breakdown bar chart: one bar per row, in whatever order
 * `rows` already arrives in. Every mart query this feeds (`martBreakdown`,
 * `regionRateRanking`) returns rows pre-sorted by value DESC in SQL, so this
 * never re-sorts -- re-sorting here would risk exactly the kind of
 * slot/order mismatch `martTrendPivot`'s own docstring warns about for its
 * series slots.
 *
 * Shares climate.tsx's `rankingSpec` layout (`Plot.barX`, a wide left margin
 * for long category names) but is not that function: this chart is reused
 * across five different crime/offenders breakdowns, each with its own axis
 * label and colour, whereas `rankingSpec` hardcodes both to one climate
 * chart's needs.
 *
 * `tickSize: 0` on both axes from the start (not discovered after a hang):
 * a purely horizontal/vertical Plot axis tick dash has a zero-width or
 * zero-height bounding box, and Playwright's default `path` wait resolves to
 * that first, never-"visible" element rather than a real bar -- the same
 * trap `series.tsx`'s `lineSeriesSpec` documents and fixes the same way.
 */
export function hBarSpec(rows: Row[], opts: HBarOptions): Plot.PlotOptions {
  return {
    marginLeft: 160,
    x: { label: opts.xLabel, grid: true, tickSize: 0 },
    y: { label: null, domain: rows.map((r) => String(r.name)), tickSize: 0 },
    marks: [
      Plot.ruleX([0], { stroke: gridline() }),
      Plot.barX(rows, { x: "value", y: "name", fill: opts.color }),
    ],
  };
}
