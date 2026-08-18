import { useEffect, useMemo, useState } from "react";
import { PlotFigure } from "../charts/plot";
import { lineSeriesSpec } from "../charts/series";
import { inflationSeries } from "../queries/static";
import { inkMuted, inkPrimary, series, type Mode } from "../theme";
import { Card, EmptyNote } from "../ui";

// The static frontend's economy page. italy_dashboard/pages/economy.py (27
// lines, one chart, no region selector -- inflation_series() takes none) is
// the reference for WHAT is shown, not for styling (see Climate.tsx's header
// comment on why this app does not chase Recharts pixel parity).

type Row = Record<string, unknown>;

function Loading() {
  return (
    <p className="loading-row" style={{ color: inkMuted(), margin: 0 }} aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      Loading data…
    </p>
  );
}

export default function Economy({ mode }: { mode: Mode }) {
  const [loading, setLoading] = useState(true);
  const [inflation, setInflation] = useState<Row[]>([]);

  useEffect(() => {
    let cancelled = false;
    void inflationSeries().then((rows) => {
      if (cancelled) return;
      setInflation(rows);
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // Memoised on `mode` too, not just `inflation` -- theme.ts's `series()` is
  // read at spec-build time, so a colour-mode toggle that changes neither
  // `inflation` nor anything else this page owns would otherwise never
  // rebuild the spec, leaving the line's colour stuck on whichever mode was
  // active on first render (see App.tsx's docstring on the same bug, fixed
  // once already on the climate page).
  const inflationSpec = useMemo(
    () =>
      lineSeriesSpec(inflation, {
        series: [{ key: "value", label: "Change (%)", color: series(1) }],
        yLabel: "Change (%)",
      }),
    [inflation, mode],
  );

  return (
    <div>
      <h1 style={{ color: inkPrimary(), margin: "0 0 1rem" }}>Economy &amp; prices</h1>
      <Card
        title="Inflation (consumer prices)"
        subtitle="Annual average change of the general index (%)"
      >
        <div data-testid="inflation">
          {loading ? (
            <Loading />
          ) : inflation.length === 0 ? (
            <EmptyNote>No inflation data.</EmptyNote>
          ) : (
            <PlotFigure spec={inflationSpec} />
          )}
        </div>
      </Card>
    </div>
  );
}
