import { useEffect, useMemo, useRef, useState } from "react";
import provinceCapitalsCsv from "../../../dbt/seeds/province_capitals.csv?raw";
import {
  bandTrendSpec,
  distributionSpec,
  monthHeatmapSpec,
  rankingSpec,
  stripesSpec,
  thresholdSpec,
} from "../charts/climate";
import { PlotFigure } from "../charts/plot";
import { unavailableTables } from "../db";
import {
  climateCoverage,
  climateMonthHeatmap,
  climateStripes,
  climateThresholdDays,
  warmingRateRanking,
} from "../queries/climate";
import {
  climateCityOptions,
  climateRegionAnnualSeries,
  climateRegionOptions,
  climateRegionStripes,
  climateRegionThresholdDays,
} from "../queries/climateScope";
import { climateReady, climateRegionReady } from "../queries/ready";
import { climateAnnualSeries, climateDistribution, climateDistributionWindows } from "../queries/static";
import { gridline, inkMuted, inkPrimary, inkSecondary, type Mode } from "../theme";
import { Callout, Card, DataTable, EmptyNote, SectionHeading, Select } from "../ui";

// The static frontend's climate page. italy_dashboard/pages/climate.py is the
// reference for WHAT is shown and HOW it is grouped (an Italia -> region ->
// city scope cascade, a "Selected scope" section, then a cross-city "Across
// Italy" section) -- not for styling, which this app deliberately does not
// copy (Observable Plot was chosen over Recharts precisely so charts here can
// use marks suited to statistical display, not to match Recharts pixel for
// pixel).
//
// Two behaviours carried over from that page as CORRECTNESS requirements, not
// styling choices (see that file's `_across_italy_section` docstring):
//
//   1. The cross-city ranking and the stripes grid are NEVER filtered by the
//      selected city -- filtering a ranking to one city destroys the
//      comparison it exists to show. They ACKNOWLEDGE the selection instead
//      (an outlined bar, a ringed panel), via `highlightedCity` below.
//   2. When the selected city is in neither, `cityOutsideRankingNote` says so
//      in words -- otherwise 30 of the 50 covered capitals produce no visible
//      signal anywhere on the page, which reads as broken rather than as "not
//      in the top 20".

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

type Windows = [number, number, number, number];

// Reused verbatim from italy_dashboard/translations.py's `climate_coverage_note`
// (English copy): the backfill runs in province-code order, i.e. from the
// north, so an unweighted mean of whatever capitals are covered so far and
// labelled "Italia" understates how incomplete the picture still is. Stated
// at Italia scope only (see `isNationalScope` below).
const CLIMATE_COVERAGE_NOTE =
  "Italia is an unweighted mean of the capitals covered so far, and the " +
  "temperature backfill runs in province-code order, so it fills from the " +
  "north: much of the South is still missing and the absolute level reads " +
  "colder than Italy's. The anomaly chart is far more robust to this, " +
  "because it measures each year against the same cities' own baseline.";

// A REGION's total capital count, from the same seed climateCoverage()
// (queries/climate.ts) reads for the national total -- imported directly
// here (not added to queries/climate.ts, which this branch's review asked
// not be touched) because no ported function returns a PER-region count,
// only the national aggregate. "A single region's capitals are the region"
// is only true when every one of them is covered: Toscana is 1 of 10 capitals,
// Puglia 1 of 6, Marche 1 of 5 -- each of those, unqualified, is one city
// wearing a region's name, the same shape of wrong number the Italia note
// above exists to prevent. `climateCityOptions(region)` (already consumed
// below for the City dropdown) already returns exactly the capitals COVERED
// in a region, so the "of how many" half is the only piece derived here.
function regionCapitalTotals(): Map<string, number> {
  const lines = provinceCapitalsCsv.trim().split("\n").slice(1); // drop header
  const totals = new Map<string, number>();
  for (const line of lines) {
    const regionName = line.split(",")[4]!; // region_name column
    totals.set(regionName, (totals.get(regionName) ?? 0) + 1);
  }
  return totals;
}

const REGION_CAPITAL_TOTALS = regionCapitalTotals();

function regionCompositionNote(region: string, covered: number, total: number): string {
  return (
    `${region} here means ${covered} of ${total} capitals covered so far, not the ` +
    `whole region: the rest of ${region} has no temperature data in this snapshot yet.`
  );
}

/** Stripes for the top-N fastest-warming cities, flattened and tagged with
 * `city` for the responsive small-multiples grid.
 *
 * Built here, not in the query layer: `climate_stripes_grid` (queries.py:1129)
 * was deliberately not ported to `web/src/queries/` (see that file's own
 * comment on the composite) because Observable Plot's native faceting
 * replaces the hand-assembled small-multiples grid, so this page builds the
 * grid directly from `warmingRateRanking` + `climateStripes`, mirroring
 * `climate_stripes_grid`'s own filter: a city `climateStripes` returns
 * nothing for (no complete years) is dropped rather than faceted as an empty
 * panel.
 */
async function loadStripesGrid(limit: number): Promise<Row[]> {
  const top = await warmingRateRanking(limit);
  const perCity = await Promise.all(
    top.map(async (r) => {
      const city = String(r.name);
      const rows = await climateStripes(city);
      return rows.map((row) => ({ ...row, city }));
    }),
  );
  return perCity.filter((rows) => rows.length > 0).flat();
}

/** What the page is waiting for, so the wait can say which.
 *
 * These two are genuinely distinguishable and worth distinguishing: "engine" is
 * DuckDB-WASM fetching its worker, wasm and parquet extension from jsDelivr,
 * which is most of the wait on a cold load and explains why nothing has appeared
 * yet; "data" means the engine is up and the queries are running, so something is
 * about to. The boundary is real rather than cosmetic -- the readiness check is
 * the first call that forces `getConnection()`, so it resolving IS the engine
 * being ready.
 */
type LoadStage = "engine" | "data";

const LOAD_STAGE_LABEL: Record<LoadStage, string> = {
  engine: "Starting the query engine…",
  data: "Loading data…",
};

function Loading({ stage }: { stage: LoadStage }) {
  return (
    <p className="loading-row" style={{ color: inkMuted(), margin: 0 }} aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      {LOAD_STAGE_LABEL[stage]}
    </p>
  );
}

type Phase = "loading" | "no-data" | "ready";

export default function Climate({ mode }: { mode: Mode }) {
  const [phase, setPhase] = useState<Phase>("loading");
  const [loadStage, setLoadStage] = useState<LoadStage>("engine");
  const [coverage, setCoverage] = useState<Coverage>(EMPTY_COVERAGE);

  const [regionOptions, setRegionOptions] = useState<string[]>([]);
  const [region, setRegion] = useState<string>("Italia");
  const [cityOptions, setCityOptions] = useState<string[]>(["All"]);
  const [city, setCity] = useState<string>("All");

  // Cross-city: fetched once when the mart is ready, never re-fetched on a
  // scope change (see this file's header comment, requirement 1).
  const [ranking, setRanking] = useState<Row[]>([]);
  const [grid, setGrid] = useState<Row[]>([]);

  // Scope-dependent ("Selected scope" section): re-fetched whenever
  // `region`/`city` changes. `scopeLoading` is what keeps a scope change from
  // flashing "ready and empty" for the split second between picking a new
  // city and its data arriving -- see the module-level PlotFigure/theme
  // note on loading vs. empty vs. ready being three distinct states.
  const [scopeLoading, setScopeLoading] = useState(true);
  const [annual, setAnnual] = useState<Row[]>([]);
  const [stripes, setStripes] = useState<Row[]>([]);
  const [thresholds, setThresholds] = useState<Row[]>([]);
  const [heatmap, setHeatmap] = useState<Row[]>([]);
  const [distribution, setDistribution] = useState<Row[]>([]);
  const [distributionWindows, setDistributionWindows] = useState<Windows | null>(null);
  // mart_climate_daily is excluded from the static deploy (see db.ts's
  // registerParquetViews docstring); a query that needs it fails loudly
  // rather than returning an empty result. This is the ONE place that
  // failure is expected and turned into an explanatory card instead of an
  // uncaught rejection -- see the effect below. `distributionErrored` is the
  // OTHER outcome: a real failure (a network blip, a malformed row, a broken
  // port) that is NOT the table being absent -- `unavailableTables` (db.ts)
  // is what tells the two apart, so a transient error no longer renders the
  // same "isn't included in this build" claim a deliberate exclusion does.
  const [distributionUnavailable, setDistributionUnavailable] = useState(false);
  const [distributionErrored, setDistributionErrored] = useState(false);

  // Guards handleRegionChange's await: two region changes fired in quick
  // succession race, and with no ordering guarantee the FIRST request's
  // `climateCityOptions` can resolve after the second's, overwriting the
  // already-current options with stale ones. Only the most recent call's
  // result is applied.
  const regionRequestRef = useRef(0);

  // Initial load: mart readiness, coverage (shown even when the mart isn't
  // ready, same as ClimateState.load in state.py), and the cross-city data.
  useEffect(() => {
    let cancelled = false;
    // Sequential throughout, not Promise.all: DuckDB-WASM serialises every
    // query on one worker regardless (this project's own prior-plan finding,
    // recorded in db.ts's registerParquetViews), so batching several at once
    // costs nothing in the normal case and only adds queueing overhead --
    // and a `cancelled` check between each one means a user who navigates
    // away mid-load stops this effect from firing its REMAINING queries at
    // all, rather than every one of them landing on the worker ahead of
    // whichever page is opened next (see the plan's final review, F2).
    void (async () => {
      const climateOk = await climateReady();
      if (cancelled) return;
      const regionOk = await climateRegionReady();
      if (cancelled) return;
      // The engine is up: those two calls are the first to force getConnection().
      setLoadStage("data");
      const cov = await climateCoverage();
      if (cancelled) return;
      setCoverage(cov as Coverage);
      if (!(climateOk && regionOk)) {
        setPhase("no-data");
        return;
      }
      const regions = await climateRegionOptions();
      if (cancelled) return;
      const cities = await climateCityOptions("Italia");
      if (cancelled) return;
      const top20 = await warmingRateRanking(20);
      if (cancelled) return;
      const gridRows = await loadStripesGrid(12);
      if (cancelled) return;
      setRegionOptions(regions);
      setCityOptions(cities);
      setRanking(top20);
      setGrid(gridRows);
      setPhase("ready");
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Scope refresh: city scope uses the per-capital marts (climateAnnualSeries
  // etc.), region/Italia scope uses the region mart's counterparts -- exactly
  // ClimateState._refresh's branch in state.py. The distribution card and the
  // month heatmap are CITY ONLY (queries.climate_distribution/_windows and
  // climateMonthHeatmap both need a specific capital_city; a region name
  // simply matches no row for the heatmap, and the distribution windows query
  // is skipped outright rather than run against a name that can't match).
  useEffect(() => {
    if (phase !== "ready") return;
    let cancelled = false;
    setScopeLoading(true);
    const isCityScope = city !== "All";
    // Sequential, not Promise.all -- see the initial-load effect above for why.
    void (async () => {
      const annualRows = await (isCityScope ? climateAnnualSeries(city) : climateRegionAnnualSeries(region));
      if (cancelled) return;
      const stripeRows = await (isCityScope ? climateStripes(city) : climateRegionStripes(region));
      if (cancelled) return;
      const thresholdRows = await (isCityScope ? climateThresholdDays(city) : climateRegionThresholdDays(region));
      if (cancelled) return;
      let heatmapRows: Row[] = [];
      let distRows: Row[] = [];
      let windows: Windows | null = null;
      let distFailed = false;
      let distErrored = false;
      if (isCityScope) {
        heatmapRows = await climateMonthHeatmap(city);
        if (cancelled) return;
        try {
          windows = await climateDistributionWindows(city);
          if (cancelled) return;
          distRows = windows ? await climateDistribution(city) : [];
        } catch (err) {
          // Claim exclusion only when the table really is unavailable in
          // this build -- any other failure (a network blip, a malformed
          // row, a genuine port bug) is a real error, not a deliberate
          // product decision, and must not render the same sentence one
          // produces.
          if (unavailableTables.has("mart_climate_daily")) {
            distFailed = true;
          } else {
            distErrored = true;
            console.error(`climate distribution query failed for ${city}:`, err);
          }
        }
      }
      if (cancelled) return;
      setAnnual(annualRows);
      setStripes(stripeRows);
      setThresholds(thresholdRows);
      setHeatmap(heatmapRows);
      setDistribution(distRows);
      setDistributionWindows(windows);
      setDistributionUnavailable(distFailed);
      setDistributionErrored(distErrored);
      setScopeLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [phase, region, city]);

  async function handleRegionChange(next: string) {
    const requestId = ++regionRequestRef.current;
    setRegion(next);
    setCity("All"); // city cascades from region: broaden back out, matching ClimateState.set_region
    const options = await climateCityOptions(next);
    if (requestId === regionRequestRef.current) {
      setCityOptions(options);
    }
  }

  const isCityScope = city !== "All";
  const isNationalScope = region === "Italia" && !isCityScope;
  const scopeName = isCityScope ? city : region;
  // "" (never a real city name) disables the outline in rankingSpec; region
  // and Italia scope select many cities at once, so nothing is singled out
  // there. See requirement 1 above.
  const highlightedCity = isCityScope ? city : "";

  // A region scope (not Italia, not a city) whose covered capitals are fewer
  // than the region actually has -- see regionCompositionNote's definition
  // above for why this matters. `cityOptions` already IS the covered count
  // (climateCityOptions(region), fetched for the City dropdown), minus its
  // leading "All" sentinel; the total comes from the seed CSV, never
  // hardcoded. A fully-covered region (the other nine of twelve) shows
  // nothing extra here, same as Italia would if the whole country were in.
  const regionCapitalTotal =
    !isCityScope && region !== "Italia" ? (REGION_CAPITAL_TOTALS.get(region) ?? 0) : 0;
  const regionCapitalCovered = !isCityScope && region !== "Italia" ? Math.max(0, cityOptions.length - 1) : 0;
  const isPartialRegionScope =
    !isCityScope && region !== "Italia" && regionCapitalTotal > 0 && regionCapitalCovered < regionCapitalTotal;

  const cityOutsideRankingNote = useMemo(() => {
    if (!isCityScope) return "";
    if (ranking.some((r) => String(r.name) === city)) return "";
    return `${city} is not among the top 20 fastest-warming cities, so it isn't highlighted below.`;
  }, [isCityScope, city, ranking]);

  // Every PlotFigure spec is memoised on the rows/highlight that feed it --
  // PlotFigure's effect keys on `[spec]`, so an object rebuilt on every
  // render (e.g. inline in JSX) would be a new identity every time and would
  // re-render the chart on every keystroke/scope change, not just real data
  // changes. `mode` is a dependency of every one of them for a second
  // reason: theme.ts's accessors (series/gridline/inkPrimary/divergingSteps)
  // are read once, at spec-build time, so a colour-mode toggle that changes
  // neither the rows nor the highlight would otherwise never rebuild the
  // spec, leaving the chart's Plot-baked colours stuck on whichever mode was
  // active on first render (only the CSS-driven `var(--div-N)` paths were
  // ever exempt from this).
  const annualSpec = useMemo(() => bandTrendSpec(annual), [annual, mode]);
  const stripesChartSpec = useMemo(() => stripesSpec(stripes), [stripes, mode]);
  const thresholdsChartSpec = useMemo(() => thresholdSpec(thresholds), [thresholds, mode]);
  const heatmapSpec = useMemo(() => monthHeatmapSpec(heatmap), [heatmap, mode]);
  const distributionChartSpec = useMemo(
    () => (distributionWindows ? distributionSpec(distribution, distributionWindows) : null),
    [distribution, distributionWindows, mode],
  );
  const rankingChartSpec = useMemo(
    () => rankingSpec(ranking, highlightedCity),
    [ranking, highlightedCity, mode],
  );
  const stripesByCity = useMemo(() => {
    const grouped = new Map<string, Row[]>();
    for (const row of grid) {
      const name = String(row.city);
      const rows = grouped.get(name) ?? [];
      rows.push(row);
      grouped.set(name, rows);
    }
    return [...grouped.entries()];
  }, [grid]);

  // The heading renders unconditionally, regardless of `phase` -- a
  // heading is not data and should never wait on a query. Previously
  // `<h1>Climate</h1>` lived inside the "ready" branch only, so `main h1`
  // meant "the data arrived", not "the route rendered": under DuckDB-WASM
  // query contention from an abandoned previous page (see the plan's final
  // review, F2), that made `main h1` a multi-second-to-30-second wait
  // instead of an instant one, which is what made
  // `test_every_nav_link_reaches_a_page_that_renders` flaky rather than the
  // environment-load coincidence it was first taken for.
  return (
    <div>
      <h1 style={{ color: inkPrimary(), margin: "0 0 1rem" }}>Climate</h1>
      {phase === "loading" ? (
        <Loading stage={loadStage} />
      ) : phase === "no-data" ? (
        <EmptyNote>
          No temperature data yet. Run <code>just refresh-weather</code> (or <code>just sample</code> for
          synthetic dev data), then reload.
        </EmptyNote>
      ) : (
        <>
        <div style={{ display: "flex", alignItems: "center", gap: "1rem", flexWrap: "wrap" }}>
          <label style={{ color: inkSecondary(), fontSize: "0.9em" }}>
            Region{" "}
            <Select
              data-testid="climate-region-select"
              value={region}
              onChange={(e) => void handleRegionChange(e.target.value)}
            >
              {regionOptions.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </Select>
          </label>
          <label style={{ color: inkSecondary(), fontSize: "0.9em" }}>
            City{" "}
            <Select data-testid="climate-city-select" value={city} onChange={(e) => setCity(e.target.value)}>
              {cityOptions.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </Select>
          </label>
        </div>

        <p style={{ color: inkSecondary(), fontSize: "0.9em", fontWeight: 600 }}>
          Coverage: {coverage.capitals} of {coverage.capitals_total} capitals, {coverage.regions} of{" "}
          {coverage.regions_total} regions, {coverage.year_start}-{coverage.year_end}
        </p>

        {isNationalScope || isPartialRegionScope ? (
          // A data-quality caveat about the aggregate above (a northern-weighted
          // "Italia" mean, or a region whose covered capitals are a fraction of
          // the whole) -- Reflex's counterpart is an amber `rx.callout` with a
          // warning icon (climate.py), which is exactly what `Callout` (ui.tsx)
          // restores here; this used to be a plain bordered `<div>`, visually
          // identical to a neutral "no data" message, and easy to miss.
          <Callout testId="climate-scope-note">
            {isNationalScope
              ? CLIMATE_COVERAGE_NOTE
              : regionCompositionNote(region, regionCapitalCovered, regionCapitalTotal)}
          </Callout>
        ) : null}

        <SectionHeading>Selected scope: {scopeName}</SectionHeading>

        <Card
          title="Annual temperature"
          subtitle="Annual mean (thin line), the min-max band each year (shaded), and a 10-year centred rolling average (heavy line)."
        >
          <div data-testid="climate-annual">
            {scopeLoading ? (
              <Loading stage="data" />
            ) : annual.length === 0 ? (
              <EmptyNote>No annual temperature data for {scopeName}.</EmptyNote>
            ) : (
              <PlotFigure spec={annualSpec} />
            )}
          </div>
          {!scopeLoading && annual.length > 0 && (
            <DataTable
              rows={annual}
              columns={[
                { key: "period", label: "Year" },
                { key: "t_min", label: "Min (mean of daily minima)" },
                { key: "t_mean", label: "Mean" },
                { key: "t_max", label: "Max (mean of daily maxima)" },
              ]}
              testId="climate-annual-table"
            />
          )}
        </Card>

        <Card title="Anomaly against the 1981-2010 normal" subtitle="Degrees Celsius above or below the own 1981-2010 average.">
          <div data-testid="climate-stripes">
            {scopeLoading ? (
              <Loading stage="data" />
            ) : stripes.length === 0 ? (
              <EmptyNote>No anomaly data for {scopeName}.</EmptyNote>
            ) : (
              <PlotFigure spec={stripesChartSpec} />
            )}
          </div>
          {!scopeLoading && stripes.length > 0 && (
            <DataTable
              rows={stripes}
              columns={[
                { key: "period", label: "Year" },
                { key: "anomaly", label: "Anomaly (°C)" },
              ]}
              testId="climate-stripes-table"
            />
          )}
        </Card>

        <Card
          title="Hot days, tropical nights and frost days"
          subtitle="Days per year with max ≥ 30°C, min ≥ 20°C and min ≤ 0°C."
        >
          <div data-testid="climate-thresholds">
            {scopeLoading ? (
              <Loading stage="data" />
            ) : thresholds.length === 0 ? (
              <EmptyNote>No threshold-day data for {scopeName}.</EmptyNote>
            ) : (
              <PlotFigure spec={thresholdsChartSpec} />
            )}
          </div>
        </Card>

        <Card
          title="Distribution of daily maxima"
          subtitle={
            isCityScope && distributionChartSpec
              ? "Share of days per 2°C bucket, the city's record split into an early and a late window."
              : undefined
          }
        >
          <div data-testid="climate-distribution">
            {!isCityScope ? (
              <EmptyNote>
                Daily histograms need a single city: the regional mart holds yearly aggregates, not daily
                readings. Pick a city above to see it.
              </EmptyNote>
            ) : scopeLoading ? (
              <Loading stage="data" />
            ) : distributionUnavailable ? (
              <EmptyNote>
                Daily temperature data isn't included in this build, so the distribution chart isn't
                available for any city.
              </EmptyNote>
            ) : distributionErrored ? (
              <EmptyNote>
                Couldn't load the daily-maxima distribution for {city} just now. Reloading the page may help.
              </EmptyNote>
            ) : !distributionChartSpec ? (
              <EmptyNote>{city} doesn't have two complete years of daily data to compare yet.</EmptyNote>
            ) : (
              <PlotFigure spec={distributionChartSpec} />
            )}
          </div>
        </Card>

        <Card
          title="Month-by-month anomaly"
          subtitle={isCityScope && heatmap.length > 0 ? "Each cell is one month's anomaly against 1981-2010; unobserved months are left blank, not zero." : undefined}
        >
          <div data-testid="climate-heatmap">
            {!isCityScope ? (
              <EmptyNote>The month-by-month grid needs a single city too — pick one above to see it.</EmptyNote>
            ) : scopeLoading ? (
              <Loading stage="data" />
            ) : heatmap.length === 0 ? (
              <EmptyNote>No monthly data for {city}.</EmptyNote>
            ) : (
              <PlotFigure spec={heatmapSpec} />
            )}
          </div>
        </Card>

        <SectionHeading>Across Italy</SectionHeading>
        {cityOutsideRankingNote ? <EmptyNote>{cityOutsideRankingNote}</EmptyNote> : null}

        <Card
          title="Fastest-warming cities"
          subtitle="Degrees Celsius per decade, ordinary least squares over annual means. Not filtered by the selection above — the selected city (if any) is outlined instead."
        >
          <div data-testid="climate-ranking">
            {ranking.length === 0 ? <EmptyNote>No ranking data.</EmptyNote> : <PlotFigure spec={rankingChartSpec} />}
          </div>
          {ranking.length > 0 && (
            <DataTable
              rows={ranking}
              columns={[
                { key: "name", label: "City" },
                { key: "value", label: "°C / decade" },
              ]}
              testId="climate-ranking-table"
            />
          )}
        </Card>

        <Card
          title="Warming stripes across cities"
          subtitle="Fastest-warming capitals, same colour scale in every panel. Not filtered by the selection above — the selected city's panel (if present) is ringed instead."
        >
          <div data-testid="climate-grid">
            {stripesByCity.length === 0 ? (
              <EmptyNote>No grid data.</EmptyNote>
            ) : (
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
                  gap: "1.25rem 1rem",
                }}
              >
                {stripesByCity.map(([name, rows]) => (
                  <section
                    key={name}
                    data-testid="climate-stripe-panel"
                    style={{
                      border: `1px solid ${name === highlightedCity ? inkPrimary() : gridline()}`,
                      borderRadius: "6px",
                      padding: "0.6rem 0.6rem 0.25rem",
                    }}
                  >
                    <h3
                      data-testid="climate-stripe-city"
                      style={{
                        color: inkSecondary(),
                        fontSize: "0.85rem",
                        fontWeight: 600,
                        margin: 0,
                      }}
                    >
                      {name}
                    </h3>
                    <PlotFigure spec={stripesSpec(rows, 90)} />
                  </section>
                ))}
              </div>
            )}
          </div>
        </Card>
        </>
      )}
    </div>
  );
}
