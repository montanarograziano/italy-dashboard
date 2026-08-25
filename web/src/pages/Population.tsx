import { useEffect, useMemo, useState } from "react";
import { PlotFigure } from "../charts/plot";
import { lineSeriesSpec } from "../charts/series";
import { NATIONAL, foreignShareTimeseries, populationTimeseries, regionNames } from "../queries/economy";
import { inkMuted, inkPrimary, inkSecondary, series, type Mode } from "../theme";
import { Card, EmptyNote, Select } from "../ui";

// The static frontend's population page. italy_dashboard/pages/population.py
// (45 lines, two charts) is the reference for WHAT is shown, not for
// styling. Residents (millions) and foreign share (%) are different scales,
// so -- same as the Reflex page -- these are two charts, never one chart
// with a dual axis. `PopulationState.region` defaults to `q.NATIONAL`
// ("Italia (totale)"); see Labor.tsx's header comment for why that is not
// the bare "Italia" ClimateState uses, and why the region OPTIONS list is
// the same one Labor's selector reads.

type Row = Record<string, unknown>;

function Loading() {
  return (
    <p className="loading-row" style={{ color: inkMuted(), margin: 0 }} aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      Loading data…
    </p>
  );
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
    // Sequential, not Promise.all: DuckDB-WASM serialises every query on one
    // worker regardless (this project's own prior-plan finding), so this
    // costs nothing in the normal case, and the `cancelled` check between the
    // two stops the second from ever firing once the user has navigated away
    // (see the plan's final review, F2).
    void (async () => {
      const res = await populationTimeseries(region);
      if (cancelled) return;
      const share = await foreignShareTimeseries(region);
      if (cancelled) return;
      setResidents(res);
      setForeignShare(share);
      setLoading(false);
    })();
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
        valueDecimals: 2,
        valueSuffix: "M",
        // A resident headcount never approaches zero, so anchoring the axis
        // there flattened the whole series into a line at the top of the card:
        // the change this chart exists to show is a few percent of the total.
        zeroBaseline: false,
      }),
    [residents, mode],
  );
  const foreignShareSpec = useMemo(
    () =>
      lineSeriesSpec(foreignShare, {
        series: [{ key: "value", label: "Foreign share (%)", color: series(2) }],
        yLabel: "Foreign share (%)",
        valueDecimals: 2,
        valueSuffix: "%",
        // Zero KEPT here, unlike the residents chart above: this is a share of
        // a whole, so 0% is a real floor and growth from a low base should be
        // read in proportion to it, not zoomed.
      }),
    [foreignShare, mode],
  );

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
        <h1 style={{ color: inkPrimary(), margin: 0 }}>Population &amp; migration</h1>
        <label style={{ color: inkSecondary(), fontSize: "0.9em" }}>
          Region{" "}
          <Select
            data-testid="population-region-select"
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
