import { useEffect, useMemo, useState } from "react";
import { PlotFigure } from "../charts/plot";
import { lineSeriesSpec } from "../charts/series";
import { NATIONAL, naspiSeries, regionNames, unemploymentSeries } from "../queries/economy";
import { inkMuted, inkPrimary, inkSecondary, series, type Mode } from "../theme";
import { Card, EmptyNote, Select } from "../ui";

// The static frontend's labor page. italy_dashboard/pages/labor.py (58
// lines, TWO charts -- unemployment AND the NASPI recipients card) is the
// reference for WHAT is shown, not for styling.
// `LaborState.region` defaults to `q.NATIONAL` ("Italia (totale)", NOT the
// bare "Italia" ClimateState/queries.ITALIA use for a different mart family
// -- see queries/economy.ts's own NATIONAL comment), and the region options
// come from `region_names()`'s default view ("labor_unemployment"), the same
// list PopulationState's selector reads (both go through
// `italy_dashboard.components.region_select`, which always reads
// `AppState.regions`).
//
// NASPI mirrors Reflex's state.py gate exactly: the query's INTERNAL guard
// returns [] when mart_naspi.parquet is absent, and `naspi_ready`/the
// reflexive `rx.cond` holds the card until rows exist -- so a snapshot whose
// labor mart predates NASPI shows no card at all rather than an "empty"
// one. The unemployment card renders regardless; here `naspiLoading` then
// `naspi.length` reproduces that gating.

type Row = Record<string, unknown>;

function Loading() {
  return (
    <p className="loading-row" style={{ color: inkMuted(), margin: 0 }} aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      Loading data…
    </p>
  );
}

export default function Labor({ mode }: { mode: Mode }) {
  const [regionOptions, setRegionOptions] = useState<string[]>([NATIONAL]);
  const [region, setRegion] = useState<string>(NATIONAL);
  const [loading, setLoading] = useState(true);
  const [rows, setRows] = useState<Row[]>([]);
  const [naspiLoading, setNaspiLoading] = useState(true);
  const [naspi, setNaspi] = useState<Row[]>([]);

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

  // Same region-driven refresh for the NASPI card, sharing the `cancelled`
  // counter-race pattern: only the latest region's result may be applied.
  useEffect(() => {
    let cancelled = false;
    setNaspiLoading(true);
    void naspiSeries(region).then((r) => {
      if (cancelled) return;
      setNaspi(r);
      setNaspiLoading(false);
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
        valueDecimals: 1,
        valueSuffix: "%",
        // Zero baseline kept (the default): a rate is a share, so 0% is a real
        // floor and the selected-vs-national gap reads against it.
      }),
    [rows, mode],
  );

  // NASPI recipients: selected region vs the national total, summed over both
  // sex rows. Counts, not rates -- so whole numbers without a unit, and the
  // zero baseline stays (a headcount's floor is 0). Chart legend labels
  // mirror Reflex's line_chart call (selected_region / national_avg); the
  // collapsible table's column headings use the shorter selected_count/
  // national_count forms ("Selected"/"National").
  const naspiSpec = useMemo(
    () =>
      lineSeriesSpec(naspi, {
        series: [
          { key: "selected", label: "Selected region", color: series(1) },
          { key: "national", label: "National average", color: series(2) },
        ],
        yLabel: "Recipients",
        valueDecimals: 0,
      }),
    [naspi, mode],
  );

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
        <h1 style={{ color: inkPrimary(), margin: 0 }}>Labor market</h1>
        <label style={{ color: inkSecondary(), fontSize: "0.9em" }}>
          Region{" "}
          <Select
            data-testid="labor-region-select"
            value={region}
            onChange={(e) => setRegion(e.target.value)}
          >
            {regionOptions.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </Select>
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

      {/* Gated on rows, like Reflex's `rx.cond(LaborState.naspi_ready, ...)`:
       * a labor snapshot that predates the NASPI mart simply shows no card. */}
      {naspiLoading ? null : naspi.length === 0 ? null : (
        <Card title="NASPI benefit recipients" subtitle="Unemployment-benefit claimants, selected region vs national total (INPS)">
          <div data-testid="naspi">
            <PlotFigure spec={naspiSpec} />
          </div>
        </Card>
      )}
    </div>
  );
}
