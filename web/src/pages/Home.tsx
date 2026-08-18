import { useEffect, useState } from "react";
import { kpis } from "../queries/crime";
import { gridline, inkMuted, inkPrimary, inkSecondary, surface } from "../theme";

// italy_dashboard/pages/home.py (25 lines, no charts) is the reference for
// WHAT this page says: a title, a subtitle, and four KPI tiles fed by
// queries.kpis() -- NOT for styling, which this app deliberately does not
// copy anywhere (see Climate.tsx's header comment). `kpis()` already exists
// in web/src/queries/crime.ts (ported in the prior query-layer plan) and
// already defaults every field to "—" until the connection is ready or a
// figure is genuinely missing, the same neutral placeholder
// `HomeState.kpi_crime` etc. start at in state.py -- so no separate
// loading/empty state is needed here, unlike Climate's three-phase gate.

type Kpis = Record<string, string>;

const EMPTY_KPIS: Kpis = { crime: "—", population: "—", unemployment: "—", inflation: "—" };

const TILES: ReadonlyArray<{ key: keyof Kpis; label: string; note: string }> = [
  { key: "crime", label: "Felony convictions", note: "latest year, total" },
  { key: "population", label: "Resident population", note: "latest 1 January" },
  { key: "unemployment", label: "Unemployment rate", note: "latest year, national rate" },
  { key: "inflation", label: "Inflation", note: "latest annual change" },
];

function StatTile({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div
      style={{
        background: surface(),
        border: `1px solid ${gridline()}`,
        borderRadius: "10px",
        padding: "1.25rem",
        flex: "1 1 200px",
        minWidth: "200px",
      }}
    >
      <p style={{ color: inkSecondary(), fontSize: "0.85em", margin: "0 0 0.35rem" }}>{label}</p>
      <p style={{ color: inkPrimary(), fontSize: "1.75em", fontWeight: 700, margin: 0 }}>{value}</p>
      <p style={{ color: inkMuted(), fontSize: "0.75em", margin: "0.35rem 0 0" }}>{note}</p>
    </div>
  );
}

export default function Home() {
  const [values, setValues] = useState<Kpis>(EMPTY_KPIS);

  useEffect(() => {
    let cancelled = false;
    void kpis().then((k) => {
      if (!cancelled) setValues(k);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div>
      <h1 style={{ color: inkPrimary(), margin: "0 0 0.35rem" }}>Italy at a glance</h1>
      <p style={{ color: inkSecondary(), margin: "0 0 1.5rem" }}>
        Key indicators from ISTAT snapshots. Open a section for detail.
      </p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "1rem" }}>
        {TILES.map((tile) => (
          <StatTile key={tile.key} label={tile.label} value={values[tile.key] ?? "—"} note={tile.note} />
        ))}
      </div>
    </div>
  );
}
