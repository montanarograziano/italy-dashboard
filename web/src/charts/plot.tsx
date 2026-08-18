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
 */
export function PlotFigure({ spec }: { spec: Plot.PlotOptions }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const chart = Plot.plot(spec);
    node.replaceChildren(chart);
    return () => chart.remove();
  }, [spec]);
  return <div ref={ref} />;
}
