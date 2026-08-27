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

export interface VBarOptions {
  xLabel?: string;
  yLabel?: string;
  color: string;
  /** Decimal places for the value in the hover tip. Defaults to 1: the one
   * caller (inflation, a percentage-point change) reads at one decimal. */
  valueDecimals?: number;
  /** Suffix appended to the tip's value, e.g. "%". */
  valueSuffix?: string;
  /** Whether zero is a meaningful baseline. `true` by default: the sole
   * caller here is inflation, which goes NEGATIVE, so the zero line is the
   * difference between prices rising and falling (see Economy.tsx and the
   * same flag in series.tsx's `lineSeriesSpec`). */
  zeroBaseline?: boolean;
}

/** Vertical bar chart over a shared period axis: the other half of the
 * bar.tsx pair to `hBarSpec`, and the Reflex economy page's `bar_chart`
 * (components.py) -- a category axis of years, one bar per period whose
 * height is the value, single fixed colour.
 *
 * With `period` on a band axis this is strictly a time series, so the
 * interaction mirrors `lineSeriesSpec`'s: `Plot.pointerX` selects the
 * nearest bar by x-distance alone, which is the right transform for one
 * mark per year. No value labels are drawn at the bar tops (unlike
 * `hBarSpec`): a vertical bar reads against its own y-axis, so the numbers
 * are recovered from the axis and the tip rather than cluttering every bar.
 *
 * Recharts' rounded bar tops (`radius=[4,4,0,0]`) are deliberately not
 * chased -- this file's charts do not imitate Recharts pixel styling (see
 * Climate.tsx's header comment on why).
 */
export function vBarSpec(rows: Row[], opts: VBarOptions): Plot.PlotOptions {
  const decimals = opts.valueDecimals ?? 1;
  const suffix = opts.valueSuffix ?? "";
  const zeroBaseline = opts.zeroBaseline ?? true;
  return themed({
    x: { label: opts.xLabel },
    y: { label: opts.yLabel },
    marks: [
      ...(zeroBaseline ? [Plot.ruleY([0], { stroke: gridline() })] : []),
      Plot.barY(rows, { x: "period", y: "value", fill: opts.color }),
      Plot.tip(
        rows,
        Plot.pointerX({
          x: "period",
          y: "value",
          title: (d: Row) => {
            const v = Number(d.value);
            return `${String(d.period)}\n${v > 0 ? "+" : ""}${v.toFixed(decimals)}${suffix}`;
          },
          ...tipOptions(),
        }),
      ),
    ],
  });
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
