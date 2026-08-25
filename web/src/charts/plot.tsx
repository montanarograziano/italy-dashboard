import * as Plot from "@observablehq/plot";
import { useEffect, useRef, useState } from "react";

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
  const [width, setWidth] = useState(0);

  // Measure the container and hand Plot a real pixel width.
  //
  // This fixes the most visible layout defect in the app: Plot's default width
  // is 640px, sized for a notebook cell, and nothing overrode it -- so every
  // chart rendered as a 640px block inside a ~1050px card, leaving ~40% of the
  // card as dead space to the right of the data. It cannot be fixed in CSS:
  // Plot's injected stylesheet sets `max-width: 100%`, which only ever SHRINKS
  // a chart, never grows it, so the width has to be a real number in the spec.
  //
  // A ResizeObserver rather than a one-off measurement, because the container
  // width changes without this component re-rendering: a window resize, and --
  // the case a single read gets wrong -- the appearance of the page's vertical
  // scrollbar as later cards stream in, which narrows every chart above them
  // after they have already been drawn.
  //
  // `scrollable` charts are exempt: they compute their own width from their
  // data (see facetedStripesSpec, which sizes itself so no cell falls under a
  // pixel), and clamping that to the container is the exact bug that sizing
  // exists to avoid.
  useEffect(() => {
    const node = ref.current;
    if (!node || scrollable) return;
    const observer = new ResizeObserver(([entry]) => {
      // `contentRect` excludes padding: the drawable width, not the box.
      const next = entry?.contentRect.width ?? 0;
      // Ignore sub-pixel churn. A fractional container width would otherwise
      // re-fire this and rebuild the whole SVG for a visually identical result.
      setWidth((prev) => (Math.abs(prev - next) < 1 ? prev : Math.round(next)));
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [scrollable]);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    // Before the first measurement lands there is no honest width to draw at,
    // so draw nothing rather than flash a 640px chart that immediately resizes.
    // `scrollable` specs carry their own width and never wait.
    if (!scrollable && width === 0) return;
    // The caller's own explicit `width` still wins: only a spec that does not
    // state one gets the measured container width.
    const chart = Plot.plot(scrollable ? spec : { width, ...spec });
    if (scrollable) chart.style.maxWidth = "none";
    node.replaceChildren(chart);
    return () => chart.remove();
  }, [spec, scrollable, width]);

  return <div ref={ref} style={scrollable ? { overflowX: "auto" } : { width: "100%" }} />;
}
