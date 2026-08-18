import { useEffect, useMemo, useState, type ReactNode } from "react";
import { PlotFigure } from "../charts/plot";
import { lineSeriesSpec } from "../charts/series";
import { NATIONAL, foreignShareTimeseries, populationTimeseries, regionNames } from "../queries/economy";
import { gridline, inkMuted, inkPrimary, inkSecondary, series, surface, type Mode } from "../theme";

// The static frontend's population page. italy_dashboard/pages/population.py
// (45 lines, two charts) is the reference for WHAT is shown, not for
// styling. Residents (millions) and foreign share (%) are different scales,
// so -- same as the Reflex page -- these are two charts, never one chart
// with a dual axis. `PopulationState.region` defaults to `q.NATIONAL`
// ("Italia (totale)"); see Labor.tsx's header comment for why that is not
// the bare "Italia" ClimateState uses, and why the region OPTIONS list is
// the same one Labor's selector reads.

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

export default function Population({ mode }: { mode: Mode }) {
  const [regionOptions, setRegionOptions] = useState<string[]>([NATIONAL]);
  const [region, setRegion] = useState<string>(NATIONAL);
  const [loading, setLoading] = useState(true);
  const [residents, setResidents] = useState<Row[]>([]);
  const [foreignShare, setForeignShare] = useState<Row[]>([]);

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

  // Both series refresh together on region change, mirroring
  // `PopulationState._refresh` (state.py), which sets both in one call.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void Promise.all([populationTimeseries(region), foreignShareTimeseries(region)]).then(
      ([res, share]) => {
        if (cancelled) return;
        setResidents(res);
        setForeignShare(share);
        setLoading(false);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [region]);

  // `mode` is a dependency for the same reason as Economy.tsx/Labor.tsx:
  // theme.ts's `series()` is read at spec-build time, not render time.
  const residentsSpec = useMemo(
    () =>
      lineSeriesSpec(residents, {
        series: [{ key: "value", label: "Residents (millions)", color: series(1) }],
        yLabel: "Residents (millions)",
      }),
    [residents, mode],
  );
  const foreignShareSpec = useMemo(
    () =>
      lineSeriesSpec(foreignShare, {
        series: [{ key: "value", label: "Foreign share (%)", color: series(2) }],
        yLabel: "Foreign share (%)",
      }),
    [foreignShare, mode],
  );

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
        <h1 style={{ color: inkPrimary(), margin: 0 }}>Population &amp; migration</h1>
        <label style={{ color: inkSecondary(), fontSize: "0.9em" }}>
          Region{" "}
          <select
            data-testid="population-region-select"
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

      <Card title="Resident population" subtitle="Residents on 1 January">
        <div data-testid="resident">
          {loading ? (
            <Loading />
          ) : residents.length === 0 ? (
            <EmptyNote>No population data for {region}.</EmptyNote>
          ) : (
            <PlotFigure spec={residentsSpec} />
          )}
        </div>
      </Card>

      <Card title="Foreign residents share" subtitle="Foreign residents as % of resident population">
        <div data-testid="foreign-share">
          {loading ? (
            <Loading />
          ) : foreignShare.length === 0 ? (
            <EmptyNote>No foreign-share data for {region}.</EmptyNote>
          ) : (
            <PlotFigure spec={foreignShareSpec} />
          )}
        </div>
      </Card>
    </div>
  );
}
