import * as Plot from "@observablehq/plot";

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
  /** Column shown in each point's native SVG `<title>` tooltip (Plot's
   * `title` mark option) -- mirrors `scatter_chart`'s `label_key` in
   * components.py (the region name), the recharts ZAxis-tooltip idiom
   * ported to Plot's own, simpler mechanism. */
  titleKey?: string;
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
 * `tickSize: 0` on both axes from the start, same reasoning as `bar.tsx`'s
 * `hBarSpec`: a purely horizontal/vertical Plot axis tick dash has a
 * zero-width or zero-height bounding box, which breaks a plain Playwright
 * `path` wait -- this project's Plot work has hit that trap on every new
 * spec file that skipped it.
 */
export function scatterSpec(series: ScatterSeriesDef[], opts: ScatterOptions): Plot.PlotOptions {
  const long: Row[] = series.flatMap((s) => s.rows.map((r) => ({ ...r, __series: s.label })));
  return {
    x: { label: opts.xLabel, grid: true, tickSize: 0 },
    y: { label: opts.yLabel, grid: true, tickSize: 0 },
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
        title: opts.titleKey,
      }),
    ],
  };
}
