import * as Plot from "@observablehq/plot";
import { useEffect, useRef } from "react";

/** Renders an Observable Plot spec into a div.
 *
 * Plot returns a detached DOM node rather than React elements, so this is the
 * one place in the app that touches the DOM directly. Replacing rather than
 * appending matters: Plot has no update path, and appending on every render
 * would silently stack charts on top of each other.
 *
 * The `[spec]` effect dependency means a spec rebuilt inline on every render
 * (e.g. `<PlotFigure spec={{ marks: [...] }} />` written directly in JSX) is a
 * new object identity every time and would re-render the chart on every
 * parent render, including ones that touch nothing the chart depends on.
 * Callers must memoise (`useMemo`) the spec they pass in.
 *
 * `scrollable`: Plot's own stylesheet (injected into every SVG it renders)
 * sets `max-width: 100%`, which is what makes a chart shrink to fit its
 * container -- the right default for every chart at its usual width (640,
 * comfortably under the page's own max-width). A spec that intentionally
 * asks for real pixel width per data point (facetedStripesSpec's grid, sized
 * from the actual facet/year counts so a year-band is never sub-pixel) needs
 * the OPPOSITE: shrinking a 3000+px chart down to ~1000px would undo that
 * sizing and put every cell back under a pixel, invisibly, since the
 * viewBox scales uniformly. Overriding `max-width` on the rendered node
 * itself (an inline style always wins over Plot's class-scoped stylesheet
 * rule) restores the chart's real, unshrunk size; the wrapping div's own
 * `overflowX: "auto"` is what keeps that from blowing out the page layout,
 * a horizontal scrollbar on just this card instead.
 */
export function PlotFigure({ spec, scrollable = false }: { spec: Plot.PlotOptions; scrollable?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const chart = Plot.plot(spec);
    if (scrollable) chart.style.maxWidth = "none";
    node.replaceChildren(chart);
    return () => chart.remove();
  }, [spec, scrollable]);
  return <div ref={ref} style={scrollable ? { overflowX: "auto" } : undefined} />;
}
