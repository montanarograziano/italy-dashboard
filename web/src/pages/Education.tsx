import { useEffect, useMemo, useState } from "react";
import { hBarSpec } from "../charts/bar";
import { PlotFigure } from "../charts/plot";
import { dsuRanking } from "../queries/education";
import { inkMuted, inkPrimary, series, type Mode } from "../theme";
import { Card, EmptyNote } from "../ui";

type Row = Record<string, unknown>;

function Loading() {
  return (
    <p
      className="loading-row"
      style={{ color: inkMuted(), margin: 0 }}
      aria-live="polite"
    >
      <span className="spinner" aria-hidden="true" />
      Loading data…
    </p>
  );
}

export default function Education({ mode }: { mode: Mode }) {
  const [loading, setLoading] = useState(true);
  const [rows, setRows] = useState<Row[]>([]);

  useEffect(() => {
    let cancelled = false;
    void dsuRanking().then((r) => {
      if (cancelled) return;
      setRows(r);
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const rankingSpec = useMemo(
    () => hBarSpec(rows, { xLabel: "Scholarships granted", color: series(1) }),
    [rows, mode],
  );

  return (
    <div>
      <h1 style={{ color: inkPrimary(), margin: "0 0 1rem" }}>
        Education support
      </h1>
      <Card
        title="University scholarships granted"
        subtitle="Latest academic year, regional DSU grants (USTAT/MUR)"
      >
        <div data-testid="dsu-ranking">
          {loading ? (
            <Loading />
          ) : rows.length === 0 ? (
            <EmptyNote>DSU scholarship mart not built yet.</EmptyNote>
          ) : (
            <PlotFigure spec={rankingSpec} />
          )}
        </div>
      </Card>
    </div>
  );
}
