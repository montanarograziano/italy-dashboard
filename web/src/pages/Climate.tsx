import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  bandTrendSpec,
  distributionSpec,
  facetedStripesSpec,
  monthHeatmapSpec,
  rankingSpec,
  stripesSpec,
  thresholdSpec,
} from "../charts/climate";
import { PlotFigure } from "../charts/plot";
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
import { gridline, inkMuted, inkPrimary, inkSecondary, surface } from "../theme";

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
// at Italia scope only (see `isNationalScope` below) -- a single region's
// capitals ARE the region, so there is no composition caveat to make there.
const CLIMATE_COVERAGE_NOTE =
  "Italia is an unweighted mean of the capitals covered so far, and the " +
  "temperature backfill runs in province-code order, so it fills from the " +
  "north: much of the South is still missing and the absolute level reads " +
  "colder than Italy's. The anomaly chart is far more robust to this, " +
  "because it measures each year against the same cities' own baseline.";

/** Stripes for the top-N fastest-warming cities, flattened and tagged with
 * `city` for `facetedStripesSpec`'s `fx` channel.
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

function SectionHeading({ children }: { children: ReactNode }) {
  return (
    <h2 style={{ color: inkPrimary(), fontSize: "1.25rem", margin: "1.75rem 0 0.5rem" }}>{children}</h2>
  );
}

function Card({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: ReactNode;
  children: ReactNode;
}) {
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
      {subtitle ? (
        <p style={{ color: inkMuted(), fontSize: "0.85em", margin: "0 0 0.75rem" }}>{subtitle}</p>
      ) : null}
      {children}
    </section>
  );
}

/** A plain-words placeholder for "there is nothing to draw here, and here is
 * why" -- distinct from a chart rendered with zero marks, which looks like a
 * bug rather than an honest answer. See this file's header comment on the
 * distribution card for why this is the PRIMARY path for that card, not a
 * fallback.
 */
function EmptyNote({ children }: { children: ReactNode }) {
  return <p style={{ color: inkMuted(), fontStyle: "italic", margin: 0 }}>{children}</p>;
}

function Loading() {
  return <EmptyNote>Loading…</EmptyNote>;
}

type Phase = "loading" | "no-data" | "ready";

export default function Climate() {
  const [phase, setPhase] = useState<Phase>("loading");
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
  // uncaught rejection -- see the effect below.
  const [distributionUnavailable, setDistributionUnavailable] = useState(false);

  // Initial load: mart readiness, coverage (shown even when the mart isn't
  // ready, same as ClimateState.load in state.py), and the cross-city data.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const [climateOk, regionOk] = await Promise.all([climateReady(), climateRegionReady()]);
      const cov = await climateCoverage();
      if (cancelled) return;
      setCoverage(cov as Coverage);
      if (!(climateOk && regionOk)) {
        setPhase("no-data");
        return;
      }
      const [regions, cities, top20, gridRows] = await Promise.all([
        climateRegionOptions(),
        climateCityOptions("Italia"),
        warmingRateRanking(20),
        loadStripesGrid(12),
      ]);
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
    void (async () => {
      const [annualRows, stripeRows, thresholdRows] = await Promise.all([
        isCityScope ? climateAnnualSeries(city) : climateRegionAnnualSeries(region),
        isCityScope ? climateStripes(city) : climateRegionStripes(region),
        isCityScope ? climateThresholdDays(city) : climateRegionThresholdDays(region),
      ]);
      let heatmapRows: Row[] = [];
      let distRows: Row[] = [];
      let windows: Windows | null = null;
      let distFailed = false;
      if (isCityScope) {
        heatmapRows = await climateMonthHeatmap(city);
        try {
          windows = await climateDistributionWindows(city);
          distRows = windows ? await climateDistribution(city) : [];
        } catch {
          distFailed = true;
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
      setScopeLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [phase, region, city]);

  async function handleRegionChange(next: string) {
    setRegion(next);
    setCity("All"); // city cascades from region: broaden back out, matching ClimateState.set_region
    setCityOptions(await climateCityOptions(next));
  }

  const isCityScope = city !== "All";
  const isNationalScope = region === "Italia" && !isCityScope;
  const scopeName = isCityScope ? city : region;
  // "" (never a real city name) disables the ring/outline in rankingSpec and
  // facetedStripesSpec -- both region and Italia scope select many cities at
  // once, so nothing is singled out there. See requirement 1 above.
  const highlightedCity = isCityScope ? city : "";

  const cityOutsideRankingNote = useMemo(() => {
    if (!isCityScope) return "";
    if (ranking.some((r) => String(r.name) === city)) return "";
    return `${city} is not among the top 20 fastest-warming cities, so it isn't highlighted below.`;
  }, [isCityScope, city, ranking]);

  // Every PlotFigure spec is memoised on the rows/highlight that feed it --
  // PlotFigure's effect keys on `[spec]`, so an object rebuilt on every
  // render (e.g. inline in JSX) would be a new identity every time and would
  // re-render the chart on every keystroke/scope change, not just real data
  // changes.
  const annualSpec = useMemo(() => bandTrendSpec(annual), [annual]);
  const stripesChartSpec = useMemo(() => stripesSpec(stripes), [stripes]);
  const thresholdsChartSpec = useMemo(() => thresholdSpec(thresholds), [thresholds]);
  const heatmapSpec = useMemo(() => monthHeatmapSpec(heatmap), [heatmap]);
  const distributionChartSpec = useMemo(
    () => (distributionWindows ? distributionSpec(distribution, distributionWindows) : null),
    [distribution, distributionWindows],
  );
  const rankingChartSpec = useMemo(() => rankingSpec(ranking, highlightedCity), [ranking, highlightedCity]);
  const gridChartSpec = useMemo(() => facetedStripesSpec(grid, highlightedCity), [grid, highlightedCity]);

  if (phase === "loading") {
    return <Loading />;
  }
  if (phase === "no-data") {
    return (
      <EmptyNote>
        No temperature data yet. Run <code>just refresh-weather</code> (or <code>just sample</code> for
        synthetic dev data), then reload.
      </EmptyNote>
    );
  }

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: "1rem", flexWrap: "wrap" }}>
        <h1 style={{ color: inkPrimary(), margin: 0 }}>Climate</h1>
        <label style={{ color: inkSecondary(), fontSize: "0.9em" }}>
          Region{" "}
          <select value={region} onChange={(e) => void handleRegionChange(e.target.value)}>
            {regionOptions.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>
        <label style={{ color: inkSecondary(), fontSize: "0.9em" }}>
          City{" "}
          <select value={city} onChange={(e) => setCity(e.target.value)}>
            {cityOptions.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
      </div>

      <p style={{ color: inkSecondary(), fontSize: "0.9em", fontWeight: 600 }}>
        Coverage: {coverage.capitals} of {coverage.capitals_total} capitals, {coverage.regions} of{" "}
        {coverage.regions_total} regions, {coverage.year_start}-{coverage.year_end}
      </p>

      {isNationalScope ? (
        <div
          role="alert"
          style={{
            border: `1px solid ${gridline()}`,
            borderRadius: "8px",
            padding: "0.75rem 1rem",
            color: inkSecondary(),
            fontSize: "0.9em",
          }}
        >
          {CLIMATE_COVERAGE_NOTE}
        </div>
      ) : null}

      <SectionHeading>Selected scope: {scopeName}</SectionHeading>

      <Card
        title="Annual temperature"
        subtitle="Annual mean (thin line), the min-max band each year (shaded), and a 10-year centred rolling average (heavy line)."
      >
        <div data-testid="climate-annual">
          {scopeLoading ? (
            <Loading />
          ) : annual.length === 0 ? (
            <EmptyNote>No annual temperature data for {scopeName}.</EmptyNote>
          ) : (
            <PlotFigure spec={annualSpec} />
          )}
        </div>
      </Card>

      <Card title="Anomaly against the 1981-2010 normal" subtitle="Degrees Celsius above or below the own 1981-2010 average.">
        <div data-testid="climate-stripes">
          {scopeLoading ? (
            <Loading />
          ) : stripes.length === 0 ? (
            <EmptyNote>No anomaly data for {scopeName}.</EmptyNote>
          ) : (
            <PlotFigure spec={stripesChartSpec} />
          )}
        </div>
      </Card>

      <Card
        title="Hot days, tropical nights and frost days"
        subtitle="Days per year with max ≥ 30°C, min ≥ 20°C and min ≤ 0°C."
      >
        <div data-testid="climate-thresholds">
          {scopeLoading ? (
            <Loading />
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
            <Loading />
          ) : distributionUnavailable ? (
            <EmptyNote>
              Daily temperature data isn't included in this build, so the distribution chart isn't
              available for any city.
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
            <Loading />
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
      </Card>

      <Card
        title="Warming stripes across cities"
        subtitle="Fastest-warming capitals, same colour scale in every panel. Not filtered by the selection above — the selected city's panel (if present) is ringed instead."
      >
        <div data-testid="climate-grid">
          {grid.length === 0 ? <EmptyNote>No grid data.</EmptyNote> : <PlotFigure spec={gridChartSpec} />}
        </div>
      </Card>
    </div>
  );
}
