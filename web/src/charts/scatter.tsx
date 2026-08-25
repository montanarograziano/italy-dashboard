import * as Plot from "@observablehq/plot";
import { themed, tipOptions } from "./plotTheme";

type Row = Record<string, unknown>;

/** One coloured group of points, e.g. one citizenship's regions -- shares the
 * `label`/`color` half of series.tsx's `SeriesDef` shape, but carries its OWN
 * row set (`rows`) instead of a shared-row `key`: unlike a line chart's
 * columns-of-one-table shape, `income_scatter`'s two groups are two SEPARATE
 * row sets (queries/static.ts's `incomeScatter` already splits them by
 * citizenship code), so there is no single wide row to pull two keys out of.
 */
export interface ScatterSeriesDef {
  rows: Row[];
  label: string;
  color: string;
}

export interface ScatterOptions {
  /** Column holding the x value, read from every series' own rows. */
  xKey: string;
  /** Column holding the y value. */
  yKey: string;
  xLabel?: string;
  yLabel?: string;
  /** Column naming each point (the region name) -- mirrors `scatter_chart`'s
   * `label_key` in components.py.
   *
   * This used to be passed as Plot's `title` mark option, which renders a
   * native SVG `<title>` element: the BROWSER's tooltip, which needs a ~1s
   * motionless hover to appear, cannot be styled, and shows only the label,
   * never the x/y values. It is now the heading of a real `Plot.tip`, which
   * appears immediately and carries the coordinates too. */
  titleKey?: string;
  /** Decimals for the x value shown in the tip. */
  xDecimals?: number;
  /** Decimals for the y value shown in the tip. */
  yDecimals?: number;
}

/** A two-(or-more)-group scatter, one coloured dot series per group sharing
 * one x/y axis pair -- the shape `income_scatter`'s Italians-vs-foreigners
 * split needs, and the only scatter this app draws, so this is not
 * generalised beyond what that one caller (Crime.tsx's income card) uses.
 *
 * Reshapes every series' rows into one long array carrying a `__series`
 * label field and draws ONE `Plot.dot` call with `fill: "__series"` -- the
 * same technique `series.tsx`'s `lineSeriesSpec` uses for its multi-series
 * branch. This matters, not just style: passing each series' `color` as a
 * literal `fill` (bypassing the channel) would leave the `color` scale
 * declared but unused, and Plot only actually renders the legend it backs
 * for a scale a mark's channel refers to -- a legend with no dots feeding it
 * is exactly the kind of "looks right, isn't wired up" bug this project has
 * hit before (see App.tsx's colour-mode memo-dependency finding).
 *
 * `tickSize: 0` on both axes is no longer set here: it is a shared default in
 * `themed()` (plotTheme.ts), which documents the Playwright `path`-wait trap
 * that makes it load-bearing rather than cosmetic.
 */
export function scatterSpec(series: ScatterSeriesDef[], opts: ScatterOptions): Plot.PlotOptions {
  const long: Row[] = series.flatMap((s) => s.rows.map((r) => ({ ...r, __series: s.label })));
  const xd = opts.xDecimals ?? 0;
  const yd = opts.yDecimals ?? 1;
  return themed({
    x: { label: opts.xLabel, grid: true },
    y: { label: opts.yLabel, grid: true },
    color: {
      legend: true,
      domain: series.map((s) => s.label),
      range: series.map((s) => s.color),
    },
    marks: [
      Plot.dot(long, {
        x: opts.xKey,
        y: opts.yKey,
        fill: "__series",
        // A little transparency plus a slightly larger radius: this scatter
        // overplots heavily (two citizenship groups over the same ~100
        // regions), and fully opaque dots hide how many points share a spot.
        fillOpacity: 0.75,
        r: 4,
      }),
      // Plain `Plot.pointer`, not `pointerX`/`pointerY`: in a scatter BOTH
      // coordinates are data, so the nearest point in 2-D is the one the
      // reader means. `maxRadius` is raised from Plot's 40px default because
      // this cloud is sparse at its edges, where the default leaves the
      // outliers -- the most interesting points in a correlation chart --
      // unhoverable.
      Plot.tip(
        long,
        Plot.pointer({
          x: opts.xKey,
          y: opts.yKey,
          maxRadius: 60,
          title: (d: Row) =>
            [
              opts.titleKey ? String(d[opts.titleKey]) : "",
              String(d.__series),
              `${opts.xLabel ?? "x"}: ${Number(d[opts.xKey]).toFixed(xd)}`,
              `${opts.yLabel ?? "y"}: ${Number(d[opts.yKey]).toFixed(yd)}`,
            ]
              .filter(Boolean)
              .join("\n"),
          ...tipOptions(),
        }),
      ),
    ],
  });
}
