import * as Plot from "@observablehq/plot";
import { gridline } from "../theme";
import { labelInk, themed, tipOptions } from "./plotTheme";

type Row = Record<string, unknown>;

export interface HBarOptions {
  /** Axis label for the value (x) channel -- each caller's unit differs
   * (offenders, convictions, rate per 1,000), unlike climate.tsx's
   * `rankingSpec`, whose "°C / decade" label is specific to that one chart. */
  xLabel?: string;
  color: string;
  /** Decimal places for the value shown at each bar's end and in its tip.
   * Defaults to 0: most callers here are counts (offenders, convictions). A
   * caller whose unit is a rate passes 2, or every region in its ranking
   * rounds to the same handful of integers. */
  valueDecimals?: number;
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
 * `tickSize: 0` on both axes is no longer set here: it is a shared default in
 * `themed()` (plotTheme.ts), which documents the Playwright `path`-wait trap
 * that made it load-bearing rather than cosmetic.
 *
 * Two additions over a bare `barX`, both aimed at the same failure this chart
 * had in practice -- a column of near-identical bars from which the reader
 * cannot recover any actual number:
 *
 * - A value label at each bar's end. This is the one that matters: when the
 *   top and bottom of a ranking differ by a few percent, the bar lengths
 *   alone carry almost no information, and the chart reads as a solid block.
 * - A `Plot.tip` under `Plot.pointerY`. `pointerY` (not plain `pointer`) is
 *   the right transform for a horizontal bar chart: it selects on y-distance
 *   alone, so pointing anywhere along a row's band selects that row --
 *   including in the empty space past a short bar's end.
 */
export function hBarSpec(rows: Row[], opts: HBarOptions): Plot.PlotOptions {
  const decimals = opts.valueDecimals ?? 0;
  const format = (v: unknown) => Number(v).toFixed(decimals);
  return themed({
    marginLeft: 160,
    // Wider than `themed()`'s default, to leave room for the value labels;
    // otherwise they render past the frame and are clipped.
    marginRight: 56,
    x: { label: opts.xLabel, grid: true },
    y: { label: null, domain: rows.map((r) => String(r.name)) },
    marks: [
      Plot.ruleX([0], { stroke: gridline() }),
      Plot.barX(rows, { x: "value", y: "name", fill: opts.color }),
      Plot.text(rows, {
        x: "value",
        y: "name",
        text: (d: Row) => format(d.value),
        textAnchor: "start",
        dx: 6,
        fill: labelInk(),
      }),
      Plot.tip(
        rows,
        Plot.pointerY({
          x: "value",
          y: "name",
          title: (d: Row) =>
            `${String(d.name)}\n${format(d.value)}${opts.xLabel ? ` ${opts.xLabel}` : ""}`,
          ...tipOptions(),
        }),
      ),
    ],
  });
}
