import { useEffect, useMemo, useState } from "react";
import { PlotFigure } from "../charts/plot";
import { scatterSpec } from "../charts/scatter";
import { tr, trt, useLang } from "../i18n";
import { climateCoverage } from "../queries/climate";
import { crimeClimateScatter, crimeClimateStats } from "../queries/crimeClimate";
import { crimeClimateReady } from "../queries/ready";
import { gridline, inkMuted, inkPrimary, inkSecondary, series, surface, type Mode } from "../theme";
import { Callout, Card, EmptyNote } from "../ui";

// The static frontend's climate x crime page. italy_dashboard/pages/climate_crime.py
// (its own docstring) is the reference for WHAT is shown, not for styling
// (see Climate.tsx's header comment on why this app does not chase Recharts
// pixel parity). This is the most carefully-worded page in the project: the
// raw scatter and the within-region (fixed-effects) scatter of the SAME
// relationship are shown side by side specifically because they disagree --
// the naive cross-section is confounded by "the South is hot and reports
// crime differently", and the panel view is what is left once that confound
// is removed. A chart pair built to make that point, shipped without the
// paragraph explaining it, argues the opposite of what it was built to
// argue -- see `CC_CAVEAT` below, rendered FIRST, before either chart.

type Row = Record<string, unknown>;

type Coverage = {
  capitals: string;
  capitals_total: string;
  regions: string;
  regions_total: string;
  year_start: string;
  year_end: string;
};

const EMPTY_COVERAGE: Coverage = {
  capitals: "0",
  capitals_total: "0",
  regions: "0",
  regions_total: "0",
  year_start: "—",
  year_end: "—",
};

type Stats = { raw: string; panel: string; n: string };

const EMPTY_STATS: Stats = { raw: "—", panel: "—", n: "0" };

// Every string constant below is reused VERBATIM from
// italy_dashboard/translations.py's English copy (this app has no i18n
// layer -- see Crime.tsx's header comment on that). Do not paraphrase,
// shorten, or reorder the sentences within any of them.

// cc_caveat. The load-bearing paragraph: this comparison is association
// only, ECOLOGICAL (region-level, says nothing about individuals), ANNUAL
// (the heat-aggression literature works at daily/monthly grain), and
// UNDERPOWERED (ISTAT publishes province-level offenders only from 2022) --
// and deliberately shows no p-values or confidence intervals, because with
// 21 clusters they would overstate precision.
const CC_CAVEAT =
  "Association only. This is an ECOLOGICAL comparison: it is region-level " +
  "and says nothing about individuals. It is ANNUAL, while the " +
  "heat-aggression literature works at daily and monthly grain. It is " +
  "UNDERPOWERED, bounded by ISTAT publishing province-level offenders only " +
  "from 2022. The outcome is offender counts, not rates, because population " +
  "denominators start in 2019; region fixed effects absorb the population " +
  "level but not differential regional growth. No p-values or confidence " +
  "intervals are shown: with 21 clusters they would overstate precision.";

// cc_coverage_note. Shown alongside the coverage line (same numbers
// `climateCoverage()` already gives Climate.tsx): with partial, mostly
// northern coverage, the north-south confound this page's whole argument
// rests on may not show up yet, and a tidy null result can mean too few,
// too-northern regions rather than "the confound is gone".
const CC_COVERAGE_NOTE =
  "With partial, mostly-northern coverage the confound this page relies on " +
  "may not show up yet — a tidy null result below can mean too few, " +
  "too-northern regions, not that the confound is gone.";

const CC_RAW_TITLE = "Naive view: raw cross-section";
const CC_RAW_SUB =
  "Every region-year, untransformed: absolute summer temperature against " +
  "offender counts. The hotter southern regions sit on the right, so this " +
  "mostly recovers that the South is warmer and reports crime differently " +
  "— a confound, not a finding.";

const CC_PANEL_TITLE = "Panel view: within-region deviation";
const CC_PANEL_SUB =
  "Region and year fixed effects removed, so each point is a region's " +
  "deviation from its own norm in a year that was unusual nationally.";

const CC_X_RAW = "Summer mean daily max (C)";
const CC_Y_RAW = "ln(violent offenders)";
const CC_X_PANEL = "Summer max, region and year effects removed (C)";
const CC_Y_PANEL = "ln(violent offenders), region and year effects removed";

const CC_STAT_RAW = "Raw";
const CC_STAT_PANEL = "Panel";
const CC_STAT_N = "Observations";
const CC_OBS_NOTE = "region-years, shared by both views";

// no_climate_crime, shown only when the mart itself is unavailable (the
// double spaces around the two `just` commands are the translation
// string's own formatting, kept verbatim).
const NO_CLIMATE_CRIME_TEXT =
  "The crime-climate panel needs both the offenders mart and temperature " +
  "data. Run  just refresh  and  just refresh-weather  (or  just sample), " +
  "then reload.";

function Loading() {
  return (
    <p className="loading-row" style={{ color: inkMuted(), margin: 0 }} aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      {tr("Loading data…")}
    </p>
  );
}

function StatTile({ label, value, note, testId }: { label: string; value: string; note: string; testId: string }) {
  useLang();
  return (
    <div
      style={{
        background: surface(),
        border: `1px solid ${gridline()}`,
        borderRadius: "10px",
        padding: "1rem 1.25rem",
        flex: "1 1 200px",
        minWidth: "200px",
      }}
    >
      <p style={{ color: inkSecondary(), fontSize: "0.85em", margin: "0 0 0.3rem" }}>{tr(label)}</p>
      {/* `value` comes straight from crimeClimateStats() (queries/crimeClimate.ts),
       * already formatted (`slope = +0.281, r = +0.39`) -- rendered verbatim,
       * never recomputed here, same rule as every other KPI/stat tile in
       * this app. */}
      <p data-testid={testId} style={{ color: inkPrimary(), fontSize: "1.4em", fontWeight: 700, margin: 0 }}>
        {value}
      </p>
      <p style={{ color: inkMuted(), fontSize: "0.72em", margin: "0.3rem 0 0" }}>{tr(note)}</p>
    </div>
  );
}

type Phase = "loading" | "no-data" | "ready";

export default function ClimateCrime({ mode }: { mode: Mode }) {
  const [phase, setPhase] = useState<Phase>("loading");
  const [coverage, setCoverage] = useState<Coverage>(EMPTY_COVERAGE);
  const [rawPoints, setRawPoints] = useState<Row[]>([]);
  const [panelPoints, setPanelPoints] = useState<Row[]>([]);
  const [stats, setStats] = useState<Stats>(EMPTY_STATS);
  const { lang } = useLang();

  // Mirrors ClimateCrimeState.load (state.py): coverage is fetched even when
  // the mart itself is not ready (same reasoning as ClimateState -- the
  // totals from the seed always show), and the scatters/stats are only
  // fetched once `crimeClimateReady()` is true.
  useEffect(() => {
    let cancelled = false;
    // Sequential, not Promise.all: DuckDB-WASM serialises every query on one
    // worker regardless (this project's own prior-plan finding), so this
    // costs nothing in the normal case, and a `cancelled` check between each
    // stage stops the REST of this effect from ever firing once the user has
    // navigated away, rather than every query landing on the worker ahead of
    // whichever page opens next (see the plan's final review, F2).
    void (async () => {
      const ready = await crimeClimateReady();
      if (cancelled) return;
      const cov = await climateCoverage();
      if (cancelled) return;
      setCoverage(cov as Coverage);
      if (!ready) {
        setPhase("no-data");
        return;
      }
      const scatter = await crimeClimateScatter();
      if (cancelled) return;
      const s = await crimeClimateStats();
      if (cancelled) return;
      setRawPoints(scatter.raw);
      setPanelPoints(scatter.panel);
      setStats(s as Stats);
      setPhase("ready");
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // `mode` is a dependency for the same reason as every other chart page in
  // this app: theme.ts's `series()` is read at Plot spec-build time, not
  // render time (see App.tsx's colour-mode memo-dependency finding).
  const panelSpec = useMemo(
    () =>
      scatterSpec([{ rows: panelPoints, label: tr(CC_PANEL_TITLE), color: series(1) }], {
        xKey: "x",
        yKey: "y",
        xLabel: tr(CC_X_PANEL),
        yLabel: tr(CC_Y_PANEL),
        titleKey: "region",
        // Both axes here are DE-MEANED residuals (region and year effects
        // removed), so they span a fraction of a degree / of a log point.
        // Rounding to 0-1 places would collapse most of the cloud to one value.
        xDecimals: 2,
        yDecimals: 3,
        // Zero lines on the PANEL scatter only, exactly where Reflex draws
        // them (`scatter_chart(..., zero_lines=True)` on climate_crime.py's
        // panel and nowhere else): the residuals are centred on 0, so the two
        // reference lines are where the "no effect" cross sits -- both the x
        // mean and the y mean in the same view. The raw scatter below gets
        // none, because raw levels do not cross zero by construction.
        zeroLines: true,
      }),
    [panelPoints, mode, lang],
  );
  const rawSpec = useMemo(
    () =>
      scatterSpec([{ rows: rawPoints, label: tr(CC_RAW_TITLE), color: series(2) }], {
        xKey: "x",
        yKey: "y",
        xLabel: tr(CC_X_RAW),
        yLabel: tr(CC_Y_RAW),
        titleKey: "region",
        // Raw levels, not residuals: a summer mean in degrees and a log count.
        xDecimals: 1,
        yDecimals: 2,
      }),
    [rawPoints, mode, lang],
  );

  return (
    <div>
      <h1 style={{ color: inkPrimary(), margin: "0 0 1rem" }}>{tr("Summer heat and violent crime")}</h1>

      {phase === "loading" ? (
        <Loading />
      ) : phase === "no-data" ? (
        <EmptyNote>{tr(NO_CLIMATE_CRIME_TEXT)}</EmptyNote>
      ) : (
        <>
          {/* The caveat comes FIRST, before either chart: see this file's
           * header comment and the plan's task-4 brief -- a caveat present
           * but buried below the charts satisfies a mere word-presence
           * check while still arguing the wrong thing to anyone reading top
           * to bottom. `data-testid="cc-caveat"` is asserted (via
           * `compareDocumentPosition`) to precede `data-testid="cc-panel"`
           * in tests/browser/test_static_app.py.
           *
           * `Callout` (ui.tsx), not the plain bordered `<p>` this used to be:
           * Reflex actually renders this one as a neutral gray/info callout
           * (climate_crime.py), milder than the amber treatment below, but
           * this is the single most load-bearing paragraph on the page (see
           * the header comment above) and deserves to visually stand out,
           * not blend into body text -- a deliberate, content-not-styling
           * departure from Reflex's exact severity choice, not an oversight. */}
          <div style={{ margin: "0 0 1rem" }}>
            <Callout testId="cc-caveat">{tr(CC_CAVEAT)}</Callout>
          </div>

          {/* Coverage, before either scatter: the raw view's whole argument
           * is a north-south confound, and partial, mostly-northern
           * coverage can hide it and look like a null result instead. Same
           * shape as Climate.tsx's climate-scope-note, and the same fix:
           * Reflex renders `cc_coverage_note` as an amber `rx.callout` with a
           * warning icon (climate_crime.py) -- this used to be a plain
           * bordered `<div>` with no colour or icon. The raw coverage line
           * itself stays plain text, matching Climate.tsx's identical split
           * between a plain stats line and a `Callout` for the caveat about it. */}
          <p style={{ color: inkPrimary(), fontWeight: 700, margin: "0 0 0.4rem", fontSize: "0.9em" }}>
            {trt(
              "Coverage: {capitals} of {capitals_total} capitals, {regions} of {regions_total} regions, {year_start}-{year_end}",
              coverage,
            )}
          </p>
          <div style={{ margin: "0 0 1rem" }}>
            <Callout>{tr(CC_COVERAGE_NOTE)}</Callout>
          </div>

          <div style={{ display: "flex", flexWrap: "wrap", gap: "1rem", marginBottom: "1rem" }}>
            <StatTile label={CC_STAT_PANEL} value={stats.panel} note={CC_Y_PANEL} testId="cc-stat-panel" />
            <StatTile label={CC_STAT_RAW} value={stats.raw} note={CC_Y_RAW} testId="cc-stat-raw" />
            <StatTile label={CC_STAT_N} value={stats.n} note={CC_OBS_NOTE} testId="cc-stat-n" />
          </div>

          <Card title={tr(CC_PANEL_TITLE)} subtitle={tr(CC_PANEL_SUB)}>
            <div data-testid="cc-panel">
              {panelPoints.length === 0 ? (
                <EmptyNote>{tr("No region-year observations.")}</EmptyNote>
              ) : (
                <PlotFigure spec={panelSpec} />
              )}
            </div>
          </Card>

          <Card title={tr(CC_RAW_TITLE)} subtitle={tr(CC_RAW_SUB)}>
            <div data-testid="cc-raw">
              {rawPoints.length === 0 ? (
                <EmptyNote>{tr("No region-year observations.")}</EmptyNote>
              ) : (
                <PlotFigure spec={rawSpec} />
              )}
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
