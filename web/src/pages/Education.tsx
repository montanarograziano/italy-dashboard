import { useEffect, useMemo, useState } from "react";
import { hBarSpec } from "../charts/bar";
import { PlotFigure } from "../charts/plot";
import { tr, useLang } from "../i18n";
import { dsuRanking } from "../queries/education";
import { inkMuted, inkPrimary, series, type Mode } from "../theme";
import { Card, DataTable, EmptyNote } from "../ui";

type Row = Record<string, unknown>;

function Loading() {
  return (
    <p
      className="loading-row"
      style={{ color: inkMuted(), margin: 0 }}
      aria-live="polite"
    >
      <span className="spinner" aria-hidden="true" />
      {tr("Loading data…")}
    </p>
  );
}

export default function Education({ mode }: { mode: Mode }) {
  const [loading, setLoading] = useState(true);
  const [rows, setRows] = useState<Row[]>([]);
  const { lang } = useLang();

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
    () =>
      hBarSpec(rows, { xLabel: tr("Scholarships granted"), color: series(1) }),
    [rows, mode, lang],
  );

  return (
    <div>
      <h1 style={{ color: inkPrimary(), margin: "0 0 1rem" }}>
        {tr("Education support")}
      </h1>
      <Card
        title={tr("University scholarships granted")}
        subtitle={tr("Latest academic year, regional DSU grants (USTAT/MUR)")}
      >
        <div data-testid="dsu-ranking">
          {loading ? (
            <Loading />
          ) : rows.length === 0 ? (
            <EmptyNote>{tr("DSU scholarship mart not built yet.")}</EmptyNote>
          ) : (
            <PlotFigure spec={rankingSpec} />
          )}
        </div>
        {!loading && rows.length > 0 && (
          <DataTable
            rows={rows}
            columns={[
              { key: "name", label: tr("Region") },
              { key: "value", label: tr("Scholarships granted") },
            ]}
            testId="dsu-ranking-table"
          />
        )}
      </Card>
    </div>
  );
}
