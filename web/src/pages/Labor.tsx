import { useEffect, useMemo, useState, type ReactNode } from "react";
import { PlotFigure } from "../charts/plot";
import { lineSeriesSpec } from "../charts/series";
import { NATIONAL, regionNames, unemploymentSeries } from "../queries/economy";
import { gridline, inkMuted, inkPrimary, inkSecondary, series, surface, type Mode } from "../theme";

// The static frontend's labor page. italy_dashboard/pages/labor.py (38
// lines, one chart) is the reference for WHAT is shown, not for styling.
// `LaborState.region` defaults to `q.NATIONAL` ("Italia (totale)", NOT the
// bare "Italia" ClimateState/queries.ITALIA use for a different mart family
// -- see queries/economy.ts's own NATIONAL comment), and the region options
// come from `region_names()`'s default view ("labor_unemployment"), the same
// list PopulationState's selector reads (both go through
// `italy_dashboard.components.region_select`, which always reads
// `AppState.regions`).

type Row = Record<string, unknown>;

function Card({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <section
      style={{
        background: surface(),
        border: `1px solid ${gridline()}`,
        borderRadius: "10px",
        padding: "1.25rem",
        marginBottom: "1rem",
      }}
    >
      <h3 style={{ color: inkPrimary(), margin: "0 0 0.25rem", fontSize: "1.05rem" }}>{title}</h3>
      <p style={{ color: inkMuted(), fontSize: "0.85em", margin: "0 0 0.75rem" }}>{subtitle}</p>
      {children}
    </section>
  );
}

function Loading() {
  return (
    <p className="loading-row" style={{ color: inkMuted(), margin: 0 }} aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      Loading data…
    </p>
  );
}

function EmptyNote({ children }: { children: ReactNode }) {
  return <p style={{ color: inkMuted(), fontStyle: "italic", margin: 0 }}>{children}</p>;
}

export default function Labor({ mode }: { mode: Mode }) {
  const [regionOptions, setRegionOptions] = useState<string[]>([NATIONAL]);
  const [region, setRegion] = useState<string>(NATIONAL);
  const [loading, setLoading] = useState(true);
  const [rows, setRows] = useState<Row[]>([]);

  // Region list: fetched once, independent of the selected region itself.
  useEffect(() => {
    let cancelled = false;
    void regionNames().then((options) => {
      if (!cancelled) setRegionOptions(options);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // Series refresh: re-runs whenever `region` changes. The `cancelled` flag
  // (not a request-id ref, unlike Climate.tsx's cascading region->city
  // fetch) is enough here -- there is only one await per region change, so
  // React tearing down the previous effect before running the next already
  // guarantees only the latest region's result is ever applied.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void unemploymentSeries(region).then((r) => {
      if (cancelled) return;
      setRows(r);
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [region]);

  // `mode` is a dependency for the same reason as Economy.tsx/Climate.tsx:
  // theme.ts's `series()` is read at spec-build time, not render time.
  const unemploymentSpec = useMemo(
    () =>
      lineSeriesSpec(rows, {
        series: [
          { key: "selected", label: "Selected region", color: series(1) },
          { key: "national", label: "National average", color: series(2) },
        ],
        yLabel: "Unemployment rate (%)",
      }),
    [rows, mode],
  );

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
        <h1 style={{ color: inkPrimary(), margin: 0 }}>Labor market</h1>
        <label style={{ color: inkSecondary(), fontSize: "0.9em" }}>
          Region{" "}
          <select
            data-testid="labor-region-select"
            value={region}
            onChange={(e) => setRegion(e.target.value)}
          >
            {regionOptions.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>
      </div>

      <Card title="Unemployment rate" subtitle="Selected region vs national average (%)">
        <div data-testid="unemployment">
          {loading ? (
            <Loading />
          ) : rows.length === 0 ? (
            <EmptyNote>No unemployment data for {region}.</EmptyNote>
          ) : (
            <PlotFigure spec={unemploymentSpec} />
          )}
        </div>
      </Card>
    </div>
  );
}
