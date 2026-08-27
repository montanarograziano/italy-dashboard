import { useEffect, useMemo, useState } from "react";
import { hBarSpec } from "../charts/bar";
import { PlotFigure } from "../charts/plot";
import { scatterSpec } from "../charts/scatter";
import { lineSeriesSpec } from "../charts/series";
import {
  martBreakdown,
  martTrendPivot,
  offenderForeignShare,
  offenderRates,
  offendersKpis,
  regionRateRanking,
} from "../queries/crime";
import {
  ALL,
  martLatestYear,
  martOptions,
  martProvinceOptions,
  martYears,
  REGION_SCOPE,
  type Mart,
} from "../queries/martEngine";
import { martReady } from "../queries/ready";
import { incomeCorrelations, incomeScatter, incomeYears } from "../queries/static";
import { gridline, inkMuted, inkPrimary, inkSecondary, series, surface, type Mode } from "../theme";
import { Card, DataTable, EmptyNote, Select } from "../ui";

// The static frontend's crime page. italy_dashboard/pages/crime.py (397
// lines, two tabs, 11 chart calls) is the reference for WHAT is shown, not
// for styling (see Climate.tsx's header comment on why this app does not
// chase Recharts pixel parity). This is the page the probe-driven mart
// engine (queries/martEngine.ts's `martWhere`) exists to demonstrate: every
// filter below defaults to `ALL`, which is what makes `martWhere` run its
// year-coverage probe instead of a fixed rule -- see that function's own
// docstring. Pinning every dimension away from `ALL` would make the page
// "work" while never exercising that code path.
//
// One exception to the all-`ALL` default, ported verbatim from
// `OffendersState.load` (state.py): indicators (reported vs arrested, ...)
// are alternative counts of the same people, so summing "All" of them
// double-counts -- the offenders tab defaults its `indicator` filter away
// from `ALL` to the first concrete option when there is a real choice. The
// other five offenders dimensions (region, crime, sex, age, citizenship) and
// all four convictions dimensions still default to `ALL`, so the probe still
// runs.
//
// A pinned region name always carries a level pin (`REGION_SCOPE`, 'region'
// or 'province') alongside it, on both tabs: Valle d'Aosta is both a region
// and a province, so the name alone is ambiguous -- see martEngine.ts's own
// docstring. Selecting a province narrows harder than its region and wins
// the single `region` slot, exactly like `_selections` in state.py.
//
// The income-vs-offender-rate scatter card (`OffendersState._refresh_income`,
// `_income_card` in crime.py) is independent of every other offenders
// filter -- state.py's `_refresh_income` never reads `_selections()`, just
// its own `income_year` -- so `IncomeCard` below owns its own year/data
// state entirely rather than folding into `OffendersTab`'s big filter
// effect. `incomeYears`/`incomeScatter`/`incomeCorrelations` live in
// queries/static.ts (ported in this plan's prior task, alongside
// `inflationSeries`), not queries/crime.ts -- easy to miss if only the
// crime-specific query module is checked.
//
// Collapsed relative to the Reflex reference: `_trend_chart`'s four
// rx.match branches (0/1/2/3 series) compile to four separate `line_chart`
// calls because Reflex's component tree is built ahead of time; this is one
// dynamic call per tab, sized from however many labels `martTrendPivot`
// actually returns. Also, the two `breakdown_year` selectors Reflex draws
// per tab (one before each "latest year" breakdown card, both bound to the
// same state field) are drawn once per tab here, governing both of that
// tab's breakdown charts -- there is only ever one year value to pick.

type Row = Record<string, unknown>;

const CRIME_MART: Mart = ["mart_crime", ["region", "offence", "sex", "age"]];
const OFFENDERS_MART: Mart = [
  "mart_offenders",
  ["region", "indicator", "crime", "sex", "age", "citizenship"],
];

// Reflex's exact copy (translations.py's "no_mart" EN string), reused
// verbatim by both tabs' mart-readiness gate below -- same rule as every
// other caveat/callout string in this file, and the same text
// `_no_mart_callout()` renders in the Reflex reference (crime.py).
const NO_MART_TEXT =
  "Data mart not built yet. Run  just refresh  (or  just sample), which " +
  "rebuilds the dbt marts, then reload.";

// Reflex's exact copy (translations.py's "method_note" EN string), rendered
// at the end of the offenders tab only -- crime.py:226, right after
// _income_card() -- never on the convictions tab, which has no equivalent
// call in the Reflex reference either.
const METHOD_NOTE_TEXT =
  "Counts, not rates, unless stated: compare groups only against their " +
  "population denominators. Citizenship distinguishes Italian vs foreign " +
  "nationals; residence status (regular/irregular) is not part of ISTAT " +
  "statistics. Cross-crime totals count a person once per crime type.";

// `value: null` means "no split" (the trend chart's plain single total).
// Every other value is a mart dimension name, passed straight through to
// `martTrendPivot`'s `splitBy` param (and from there to `martWhere`'s
// `skip`) -- never a capitalized UI label like state.py's `SPLIT_LABELS`
// round-trips through, since there is no i18n layer here.
interface SplitOption {
  value: string | null;
  label: string;
}

const OFFENDERS_SPLIT_OPTIONS: SplitOption[] = [
  { value: null, label: "None" },
  { value: "citizenship", label: "Citizenship" },
  { value: "sex", label: "Sex" },
  { value: "age", label: "Age" },
  { value: "region", label: "Region" },
  { value: "crime", label: "Crime" },
];

const CRIME_SPLIT_OPTIONS: SplitOption[] = [
  { value: null, label: "None" },
  { value: "sex", label: "Sex" },
  { value: "age", label: "Age" },
  { value: "region", label: "Region" },
  { value: "offence", label: "Offence" },
];

function Loading() {
  return (
    <p className="loading-row" style={{ color: inkMuted(), margin: 0 }} aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      Loading data…
    </p>
  );
}

function LabeledSelect({
  label,
  testId,
  options,
  value,
  onChange,
  disabled = false,
}: {
  label: string;
  testId: string;
  options: string[];
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <label
      style={{
        color: inkSecondary(),
        fontSize: "0.8em",
        display: "flex",
        flexDirection: "column",
        gap: "0.25rem",
      }}
    >
      {label}
      <Select data-testid={testId} value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </Select>
    </label>
  );
}

function SplitBySelect({
  testId,
  options,
  value,
  onChange,
}: {
  testId: string;
  options: SplitOption[];
  value: string | null;
  onChange: (value: string | null) => void;
}) {
  return (
    <label
      style={{
        color: inkSecondary(),
        fontSize: "0.8em",
        display: "flex",
        flexDirection: "column",
        gap: "0.25rem",
      }}
    >
      Split by
      <Select
        data-testid={testId}
        value={value ?? "none"}
        onChange={(e) => onChange(e.target.value === "none" ? null : e.target.value)}
      >
        {options.map((opt) => (
          <option key={opt.value ?? "none"} value={opt.value ?? "none"}>
            {opt.label}
          </option>
        ))}
      </Select>
    </label>
  );
}

function KpiTile({ label, value, note, testId }: { label: string; value: string; note: string; testId: string }) {
  return (
    <div
      style={{
        background: surface(),
        border: `1px solid ${gridline()}`,
        borderRadius: "10px",
        padding: "1rem 1.25rem",
        flex: "1 1 180px",
        minWidth: "180px",
      }}
    >
      <p style={{ color: inkSecondary(), fontSize: "0.8em", margin: "0 0 0.3rem" }}>{label}</p>
      {/* `value` comes straight from offendersKpis() (queries/crime.ts), already
       * formatted with Python's comma thousands separator -- rendered
       * VERBATIM, never through `Number(...).toLocaleString(...)`, which
       * would silently swap in a dot and produce a string Python never
       * emits. */}
      <p data-testid={testId} style={{ color: inkPrimary(), fontSize: "1.5em", fontWeight: 700, margin: 0 }}>
        {value}
      </p>
      <p style={{ color: inkMuted(), fontSize: "0.72em", margin: "0.3rem 0 0" }}>{note}</p>
    </div>
  );
}

type OffendersOptions = {
  region: string[];
  indicator: string[];
  crime: string[];
  sex: string[];
  age: string[];
  citizenship: string[];
};

const EMPTY_OFFENDERS_OPTIONS: OffendersOptions = {
  region: [ALL],
  indicator: [ALL],
  crime: [ALL],
  sex: [ALL],
  age: [ALL],
  citizenship: [ALL],
};

const EMPTY_OFFENDERS_KPIS: Record<string, string> = {
  total: "—",
  yoy: "—",
  share: "—",
  rate_ratio: "—",
};

function OffendersTab({ mode }: { mode: Mode }) {
  const [options, setOptions] = useState<OffendersOptions>(EMPTY_OFFENDERS_OPTIONS);
  const [provinceOptions, setProvinceOptions] = useState<string[]>([ALL]);
  const [years, setYears] = useState<string[]>([]);
  const [latestYear, setLatestYear] = useState("—");

  const [region, setRegion] = useState(ALL);
  const [province, setProvince] = useState(ALL);
  const [indicator, setIndicator] = useState(ALL);
  const [crime, setCrime] = useState(ALL);
  const [sex, setSex] = useState(ALL);
  const [age, setAge] = useState(ALL);
  const [citizenship, setCitizenship] = useState(ALL);
  const [splitBy, setSplitBy] = useState<string | null>(null);
  const [breakdownYear, setBreakdownYear] = useState("");

  const [loading, setLoading] = useState(true);
  const [trendRows, setTrendRows] = useState<Row[]>([]);
  const [trendLabels, setTrendLabels] = useState<string[]>([]);
  const [byCrime, setByCrime] = useState<Row[]>([]);
  const [rates, setRates] = useState<Row[]>([]);
  const [ranking, setRanking] = useState<Row[]>([]);
  const [share, setShare] = useState<Row[]>([]);
  const [kpi, setKpi] = useState<Record<string, string>>(EMPTY_OFFENDERS_KPIS);

  // `null` = still checking, `false` = confirmed absent, `true` = confirmed
  // present. Mirrors OffendersState.load's `self.mart_ready =
  // q.mart_ready(q.OFFENDERS_MART)` guard (state.py), checked before
  // anything else -- every effect below is gated on this being `true`, so a
  // missing mart never fires a query against a view that was never
  // registered (see F3 in the plan's final review: previously every one of
  // these ran regardless, leaving an unhandled rejection and an indefinite
  // spinner rather than the `_no_mart_callout()` the Reflex reference shows).
  const [martOk, setMartOk] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    void martReady(OFFENDERS_MART).then((ok) => {
      if (!cancelled) setMartOk(ok);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // Options, years and the latest-year caption: fetched once the mart is
  // confirmed ready. Mirrors OffendersState.load's initial reads (state.py),
  // including the default-away-from-ALL indicator guard documented at the
  // top of this file.
  useEffect(() => {
    if (martOk !== true) return;
    let cancelled = false;
    // Sequential, not Promise.all: DuckDB-WASM serialises every query on one
    // worker regardless (this project's own prior-plan finding, recorded in
    // db.ts's registerParquetViews -- concurrent dispatch only adds queueing
    // overhead, never real parallelism), so firing these one at a time costs
    // nothing in the normal case and stops the later ones from ever being
    // sent at all once the user has navigated away mid-effect (see the plan's
    // final review, F2: a `Promise.all` here fires every query before
    // `cancelled` can ever be observed true).
    void (async () => {
      const opts = await martOptions(OFFENDERS_MART);
      if (cancelled) return;
      const yrs = await martYears(OFFENDERS_MART);
      if (cancelled) return;
      const latest = await martLatestYear(OFFENDERS_MART);
      if (cancelled) return;
      setOptions({
        region: opts.region ?? [ALL],
        indicator: opts.indicator ?? [ALL],
        crime: opts.crime ?? [ALL],
        sex: opts.sex ?? [ALL],
        age: opts.age ?? [ALL],
        citizenship: opts.citizenship ?? [ALL],
      });
      setYears(yrs);
      setLatestYear(latest);
      if (yrs.length > 0) setBreakdownYear(yrs[0]!);
      if (opts.indicator && opts.indicator.length > 2) setIndicator(opts.indicator[1]!);
    })();
    return () => {
      cancelled = true;
    };
  }, [martOk]);

  // Province options cascade from the region, and a region change always
  // broadens the province selection back to "All" -- mirrors
  // OffendersState.set_region_filter doing both together. Runs on mount too
  // (region starts at ALL), which is what supplies the initial province list
  // without a second, separate fetch. Gated on martOk for the same reason as
  // the effect above: `martProvinceOptions` is a DISTINCT over the whole
  // mart, one of the more expensive queries on this page, and firing it
  // against a mart that doesn't exist is pure waste.
  useEffect(() => {
    if (martOk !== true) return;
    let cancelled = false;
    setProvince(ALL);
    void martProvinceOptions(OFFENDERS_MART, region).then((opts) => {
      if (!cancelled) setProvinceOptions(opts);
    });
    return () => {
      cancelled = true;
    };
  }, [region, martOk]);

  // Every derived chart/KPI refreshes together whenever any filter changes --
  // mirrors OffendersState._refresh, called after every individual setter in
  // the Reflex reference.
  useEffect(() => {
    if (martOk !== true) return;
    let cancelled = false;
    setLoading(true);
    const usingProvince = province !== ALL;
    const selections: Record<string, string> = {
      region: usingProvince ? province : region,
      [REGION_SCOPE]: usingProvince ? "province" : "region",
      indicator,
      crime,
      sex,
      age,
      citizenship,
    };
    // Sequential, not Promise.all -- see the options effect above for why:
    // this is the effect the plan's final review measured directly (F2),
    // firing six queries at once on every filter change, then leaving all
    // six queued on DuckDB-WASM's one worker even after the user has
    // navigated to a different page entirely. A `cancelled` check between
    // each one means at most the single query already in flight at the
    // moment of navigation still runs to completion -- not all six.
    void (async () => {
      const trend = await martTrendPivot(OFFENDERS_MART, selections, splitBy);
      if (cancelled) return;
      const crimeBreakdown = await martBreakdown(OFFENDERS_MART, "crime", selections, 10, breakdownYear || null);
      if (cancelled) return;
      // Rates and the region ranking use resident-population denominators,
      // which exist per REGION only (not per province), and the raw
      // citizenship/crime filter values -- mirrors OffendersState._refresh's
      // identical choice to route these two around the province-aware
      // `selections` object above.
      const ratesRows = await offenderRates(region, crime);
      if (cancelled) return;
      const rankingRows = await regionRateRanking(breakdownYear || null, citizenship, crime);
      if (cancelled) return;
      const shareRows = await offenderForeignShare(selections);
      if (cancelled) return;
      const kpis = await offendersKpis(selections);
      if (cancelled) return;
      const [rows, labels] = trend;
      setTrendRows(rows);
      setTrendLabels(labels);
      setByCrime(crimeBreakdown);
      setRates(ratesRows);
      setRanking(rankingRows);
      setShare(shareRows);
      setKpi(kpis);
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [region, province, indicator, crime, sex, age, citizenship, splitBy, breakdownYear, martOk]);

  // `mode` is a dependency of every memo below: theme.ts's accessors
  // (series/gridline) are read at spec-build time, not render time -- see
  // App.tsx's docstring.
  const trendSpec = useMemo(() => {
    const seriesDefs =
      trendLabels.length === 0
        ? [{ key: "value", label: "Offenders", color: series(1) }]
        : trendLabels.map((label, i) => ({ key: `s${i + 1}`, label, color: series(i + 1) }));
    // Offenders are a headcount: no decimals, zero is a real floor.
    return lineSeriesSpec(trendRows, { series: seriesDefs, yLabel: "Offenders", valueDecimals: 0 });
  }, [trendRows, trendLabels, mode]);

  const ratesSpec = useMemo(
    () =>
      lineSeriesSpec(rates, {
        series: [
          { key: "s1", label: "Italians", color: series(1) },
          { key: "s2", label: "Foreigners", color: series(2) },
        ],
        yLabel: "Offenders per 1,000 residents",
        // A rate per 1,000 sits in the low single-to-double digits here, so
        // whole numbers would discard most of the gap between the two series
        // this chart exists to compare.
        valueDecimals: 2,
      }),
    [rates, mode],
  );

  const rankingSpec = useMemo(
    // Same unit as `ratesSpec`, so the same precision: hBarSpec defaults to 0
    // decimals for the count breakdowns, which would round every region in
    // this ranking to the same handful of integers.
    () => hBarSpec(ranking, { xLabel: "Offenders per 1,000", color: series(2), valueDecimals: 2 }),
    [ranking, mode],
  );

  const shareSpec = useMemo(
    () =>
      lineSeriesSpec(share, {
        series: [{ key: "value", label: "Foreign share (%)", color: series(2) }],
        yLabel: "Foreign share (%)",
        valueDecimals: 1,
        valueSuffix: "%",
      }),
    [share, mode],
  );

  const byCrimeSpec = useMemo(() => hBarSpec(byCrime, { xLabel: "Offenders", color: series(1) }), [byCrime, mode]);

  function resetFilters() {
    setRegion(ALL);
    setProvince(ALL);
    setCrime(ALL);
    setSex(ALL);
    setAge(ALL);
    setCitizenship(ALL);
    setSplitBy(null);
    setIndicator(options.indicator.length > 2 ? options.indicator[1]! : ALL);
  }

  // Mirrors `data_gate(has_loaded, mart_ready, <content>, _no_mart_callout())`
  // in the Reflex reference (crime.py) -- checked before any of the content
  // below, which assumes the mart exists.
  if (martOk === null) {
    return <Loading />;
  }
  if (martOk === false) {
    return <EmptyNote>{NO_MART_TEXT}</EmptyNote>;
  }

  return (
    <div>
      <p style={{ color: inkMuted(), fontSize: "0.85em", margin: "0 0 1rem" }}>
        Alleged offenders reported by the police. Data through {latestYear}.
      </p>

      <Card title="Explore" subtitle="Filter, or split by one dimension (top 3 groups shown)">
        <div style={{ display: "flex", flexWrap: "wrap", gap: "1em", alignItems: "flex-end" }}>
          <LabeledSelect
            label="Region"
            testId="crime-offenders-region-select"
            options={options.region}
            value={region}
            onChange={setRegion}
            disabled={splitBy === "region"}
          />
          <LabeledSelect
            label="Province"
            testId="crime-offenders-province-select"
            options={provinceOptions}
            value={province}
            onChange={setProvince}
            disabled={splitBy === "region"}
          />
          <LabeledSelect
            label="Indicator"
            testId="crime-offenders-indicator-select"
            options={options.indicator}
            value={indicator}
            onChange={setIndicator}
          />
          <LabeledSelect
            label="Crime"
            testId="crime-offenders-crime-select"
            options={options.crime}
            value={crime}
            onChange={setCrime}
            disabled={splitBy === "crime"}
          />
          <LabeledSelect
            label="Citizenship"
            testId="crime-offenders-citizenship-select"
            options={options.citizenship}
            value={citizenship}
            onChange={setCitizenship}
            disabled={splitBy === "citizenship"}
          />
          <LabeledSelect
            label="Sex"
            testId="crime-offenders-sex-select"
            options={options.sex}
            value={sex}
            onChange={setSex}
            disabled={splitBy === "sex"}
          />
          <LabeledSelect
            label="Age"
            testId="crime-offenders-age-select"
            options={options.age}
            value={age}
            onChange={setAge}
            disabled={splitBy === "age"}
          />
          <SplitBySelect
            testId="crime-offenders-split-select"
            options={OFFENDERS_SPLIT_OPTIONS}
            value={splitBy}
            onChange={setSplitBy}
          />
        </div>
        <button
          type="button"
          onClick={resetFilters}
          style={{
            marginTop: "0.75rem",
            background: "none",
            border: "none",
            color: inkMuted(),
            cursor: "pointer",
            fontSize: "0.8em",
            padding: 0,
          }}
        >
          Reset filters
        </button>
      </Card>

      <div data-testid="crime-offenders-kpis" style={{ marginBottom: "1rem" }}>
        {loading ? (
          <Loading />
        ) : (
          <div style={{ display: "flex", flexWrap: "wrap", gap: "1em" }}>
            <KpiTile
              label="Offenders"
              value={kpi.total!}
              note="latest year, current filters"
              testId="crime-kpi-total"
            />
            <KpiTile label="Year-over-year" value={kpi.yoy!} note="change vs previous year" testId="crime-kpi-yoy" />
            <KpiTile
              label="Foreign share"
              value={kpi.share!}
              note="of offenders, latest year"
              testId="crime-kpi-share"
            />
            <KpiTile
              label="Rate ratio"
              value={kpi.rate_ratio!}
              note="foreign vs italian per-capita rate"
              testId="crime-kpi-rate-ratio"
            />
          </div>
        )}
      </div>

      <Card title="Offenders over time" subtitle="Annual totals for the current filters">
        <div data-testid="crime-offenders-trend">
          {loading ? (
            <Loading />
          ) : trendRows.length === 0 ? (
            <EmptyNote>No data for the current filters.</EmptyNote>
          ) : (
            <PlotFigure spec={trendSpec} />
          )}
        </div>
        {/*
         * Table gated the same way Reflex gates it (crime.py's
         * `rx.cond(s.series_count == 0, ...)`): with a split active the rows
         * carry s1/s2/s3 columns whose labels depend on the split chosen, and
         * Reflex hides the table there entirely rather than label them
         * conditionally -- mirrored as-is.
         */}
        {!loading && trendRows.length > 0 && trendLabels.length === 0 && (
          <DataTable
            rows={trendRows}
            columns={[
              { key: "period", label: "Year" },
              { key: "value", label: "Offenders" },
            ]}
            testId="crime-offenders-trend-table"
          />
        )}
      </Card>

      <Card
        title="Offenders per 1,000 residents, by citizenship"
        subtitle="Each group divided by its own population -- the honest comparison. Foreign-resident denominators are available from 2019."
      >
        <div data-testid="crime-offenders-rates">
          {loading ? (
            <Loading />
          ) : rates.length === 0 ? (
            <EmptyNote>No rate data for this selection.</EmptyNote>
          ) : (
            <PlotFigure spec={ratesSpec} />
          )}
        </div>
        {!loading && rates.length > 0 && (
          <DataTable
            rows={rates}
            columns={[
              { key: "period", label: "Year" },
              { key: "s1", label: "Italians" },
              { key: "s2", label: "Foreigners" },
            ]}
            testId="crime-offenders-rates-table"
          />
        )}
      </Card>

      <Card
        title="Regions compared (per 1,000)"
        subtitle="All regions, offenders per 1,000 residents of the selected group, selected year. Population-normalized -- denominators exist from 2019."
      >
        <LabeledSelect
          label="Year"
          testId="crime-offenders-year-select"
          options={years}
          value={breakdownYear}
          onChange={setBreakdownYear}
        />
        <div data-testid="crime-offenders-ranking" style={{ marginTop: "0.75rem" }}>
          {loading ? (
            <Loading />
          ) : ranking.length === 0 ? (
            <EmptyNote>No ranking data for {breakdownYear || "this year"}.</EmptyNote>
          ) : (
            <PlotFigure spec={rankingSpec} />
          )}
        </div>
        {!loading && ranking.length > 0 && (
          <DataTable
            rows={ranking}
            columns={[
              { key: "name", label: "Region" },
              { key: "value", label: "Offenders per 1,000" },
            ]}
            testId="crime-offenders-ranking-table"
          />
        )}
      </Card>

      <Card title="Foreign share of offenders" subtitle="% of alleged offenders who are foreign nationals">
        <div data-testid="crime-offenders-share">
          {loading ? (
            <Loading />
          ) : share.length === 0 ? (
            <EmptyNote>No share data for this selection.</EmptyNote>
          ) : (
            <PlotFigure spec={shareSpec} />
          )}
        </div>
        {!loading && share.length > 0 && (
          <DataTable
            rows={share}
            columns={[
              { key: "period", label: "Year" },
              { key: "value", label: "Foreign share (%)" },
            ]}
            testId="crime-offenders-share-table"
          />
        )}
      </Card>

      <Card title="By type of crime" subtitle="Selected year, current filters -- top 10 (same year as above)">
        <div data-testid="crime-offenders-by-crime">
          {loading ? (
            <Loading />
          ) : byCrime.length === 0 ? (
            <EmptyNote>No breakdown data for {breakdownYear || "this year"}.</EmptyNote>
          ) : (
            <PlotFigure spec={byCrimeSpec} />
          )}
        </div>
        {!loading && byCrime.length > 0 && (
          <DataTable
            rows={byCrime}
            columns={[
              { key: "name", label: "Type of crime" },
              { key: "value", label: "Offenders" },
            ]}
            testId="crime-offenders-by-crime-table"
          />
        )}
      </Card>

      <IncomeCard mode={mode} />

      <p data-testid="crime-method-note" style={{ color: inkMuted(), fontSize: "0.8em" }}>
        {METHOD_NOTE_TEXT}
      </p>
    </div>
  );
}

// Reflex's exact copy (translations.py's "income_missing" EN string),
// reused verbatim rather than paraphrased: it names the real `just discover`
// / `just refresh income_regional` recovery steps, which this app has no
// business inventing its own wording for.
const INCOME_MISSING_TEXT =
  'Income data not fetched yet: find the dataflow with just discover "reddito disponibile", ' +
  "set it in registry.yaml, then just refresh income_regional.";

// Reflex's exact copy (translations.py's "income_caveat" EN string).
const INCOME_CAVEAT_TEXT =
  "Interpret with care: income correlates with urbanization, police presence, and reporting " +
  "propensity. A regional association is not evidence about individuals (ecological fallacy).";

/** Income vs offender rate, by region -- independent of every other filter
 * on this tab (mirrors `OffendersState._refresh_income`, which never reads
 * `_selections()`), so this owns its own year/data state entirely rather
 * than joining `OffendersTab`'s big combined-filter effect.
 *
 * `ready` mirrors `OffendersState.income_ready` (`bool(income_years())`):
 * whether the income mart has ANY usable year at all, independent of
 * whether the currently selected year happens to have rows -- the
 * `income_missing` callout is for "the mart was never built", not for
 * "this one year is empty" (which the scatter's own `EmptyNote` covers).
 */
function IncomeCard({ mode }: { mode: Mode }) {
  const [years, setYears] = useState<string[]>([]);
  const [yearsLoaded, setYearsLoaded] = useState(false);
  const [year, setYear] = useState("");
  const [dataLoading, setDataLoading] = useState(true);
  const [itl, setItl] = useState<Row[]>([]);
  const [frg, setFrg] = useState<Row[]>([]);
  const [corrItl, setCorrItl] = useState("—");
  const [corrFrg, setCorrFrg] = useState("—");

  useEffect(() => {
    let cancelled = false;
    void incomeYears().then((yrs) => {
      if (cancelled) return;
      setYears(yrs);
      setYearsLoaded(true);
      if (yrs.length > 0) setYear(yrs[0]!);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!year) return;
    let cancelled = false;
    setDataLoading(true);
    // Sequential, not Promise.all -- see OffendersTab's identical note above.
    void (async () => {
      const scatter = await incomeScatter(year);
      if (cancelled) return;
      const corr = await incomeCorrelations(year);
      if (cancelled) return;
      setItl(scatter.ITL ?? []);
      setFrg(scatter.FRG ?? []);
      setCorrItl(corr.ITL ?? "—");
      setCorrFrg(corr.FRG ?? "—");
      setDataLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [year]);

  const ready = years.length > 0;

  const scatterSpecMemo = useMemo(
    () =>
      scatterSpec(
        [
          { rows: itl, label: "Italians", color: series(1) },
          { rows: frg, label: "Foreigners", color: series(2) },
        ],
        {
          xKey: "income",
          yKey: "rate",
          xLabel: "Income per capita (EUR)",
          yLabel: "Offenders per 1,000",
          titleKey: "region",
          // Euros to the whole unit; rates at the same 2 places the rate charts
          // above use.
          xDecimals: 0,
          yDecimals: 2,
        },
      ),
    [itl, frg, mode],
  );

  return (
    <Card
      title="Income vs offender rate (regions)"
      subtitle="Each dot is a region: income per capita (x) vs offenders per 1,000 residents of the group (y). Ecological correlation -- region-level association, not individual behavior."
    >
      {!yearsLoaded ? (
        <Loading />
      ) : !ready ? (
        <div data-testid="crime-income-missing">
          <EmptyNote>{INCOME_MISSING_TEXT}</EmptyNote>
        </div>
      ) : (
        <div>
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: "1.5em",
              alignItems: "flex-end",
              marginBottom: "0.75rem",
            }}
          >
            <LabeledSelect
              label="Year"
              testId="crime-income-year-select"
              options={years}
              value={year}
              onChange={setYear}
            />
            <div>
              <p style={{ color: inkSecondary(), fontSize: "0.8em", margin: "0 0 0.2rem" }}>
                Correlation (Italians)
              </p>
              {/* `corrItl`/`corrFrg` come straight from incomeCorrelations() (queries/static.ts),
               * already formatted (e.g. "r = +0.42 (n=18)" or "—") -- rendered verbatim, same
               * rule as the KPI tiles above: never reformatted. */}
              <p
                data-testid="crime-income-corr-italians"
                style={{ color: inkPrimary(), fontWeight: 600, margin: 0 }}
              >
                {corrItl}
              </p>
            </div>
            <div>
              <p style={{ color: inkSecondary(), fontSize: "0.8em", margin: "0 0 0.2rem" }}>
                Correlation (Foreigners)
              </p>
              <p
                data-testid="crime-income-corr-foreigners"
                style={{ color: inkPrimary(), fontWeight: 600, margin: 0 }}
              >
                {corrFrg}
              </p>
            </div>
          </div>
          <div data-testid="crime-income-scatter">
            {dataLoading ? (
              <Loading />
            ) : itl.length === 0 && frg.length === 0 ? (
              <EmptyNote>No income/rate data for {year}.</EmptyNote>
            ) : (
              <PlotFigure spec={scatterSpecMemo} />
            )}
          </div>
          <p style={{ color: inkMuted(), fontSize: "0.75em", margin: "0.75rem 0 0" }}>
            {INCOME_CAVEAT_TEXT}
          </p>
        </div>
      )}
    </Card>
  );
}

type CrimeOptions = {
  region: string[];
  offence: string[];
  sex: string[];
  age: string[];
};

const EMPTY_CRIME_OPTIONS: CrimeOptions = { region: [ALL], offence: [ALL], sex: [ALL], age: [ALL] };

function ConvictionsTab({ mode }: { mode: Mode }) {
  const [options, setOptions] = useState<CrimeOptions>(EMPTY_CRIME_OPTIONS);
  const [provinceOptions, setProvinceOptions] = useState<string[]>([ALL]);
  const [years, setYears] = useState<string[]>([]);
  const [latestYear, setLatestYear] = useState("—");

  const [region, setRegion] = useState(ALL);
  const [province, setProvince] = useState(ALL);
  const [offence, setOffence] = useState(ALL);
  const [sex, setSex] = useState(ALL);
  const [age, setAge] = useState(ALL);
  const [splitBy, setSplitBy] = useState<string | null>(null);
  const [breakdownYear, setBreakdownYear] = useState("");

  const [loading, setLoading] = useState(true);
  const [trendRows, setTrendRows] = useState<Row[]>([]);
  const [trendLabels, setTrendLabels] = useState<string[]>([]);
  const [byOffence, setByOffence] = useState<Row[]>([]);
  const [byRegion, setByRegion] = useState<Row[]>([]);

  // Same mart-readiness gate as OffendersTab above, against CRIME_MART
  // instead of OFFENDERS_MART -- mirrors CrimeState.load's
  // `self.mart_ready = q.mart_ready(q.CRIME_MART)` guard and this tab's own
  // `data_gate(has_loaded, mart_ready, ..., _no_mart_callout())` in the
  // Reflex reference (crime.py's `_convictions_tab`).
  const [martOk, setMartOk] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    void martReady(CRIME_MART).then((ok) => {
      if (!cancelled) setMartOk(ok);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // Options, years and the latest-year caption: fetched once the mart is
  // confirmed ready. Mirrors CrimeState.load's initial reads (state.py); the
  // crime mart has no indicator-style dimension, so (unlike the offenders
  // tab) every filter here defaults to plain ALL, no exception.
  useEffect(() => {
    if (martOk !== true) return;
    let cancelled = false;
    // Sequential, not Promise.all -- see OffendersTab's identical note above.
    void (async () => {
      const opts = await martOptions(CRIME_MART);
      if (cancelled) return;
      const yrs = await martYears(CRIME_MART);
      if (cancelled) return;
      const latest = await martLatestYear(CRIME_MART);
      if (cancelled) return;
      setOptions({
        region: opts.region ?? [ALL],
        offence: opts.offence ?? [ALL],
        sex: opts.sex ?? [ALL],
        age: opts.age ?? [ALL],
      });
      setYears(yrs);
      setLatestYear(latest);
      if (yrs.length > 0) setBreakdownYear(yrs[0]!);
    })();
    return () => {
      cancelled = true;
    };
  }, [martOk]);

  // Province options cascade from the region; see OffendersTab's identical
  // effect above for why the reset lives here rather than in the region
  // select's own onChange.
  useEffect(() => {
    if (martOk !== true) return;
    let cancelled = false;
    setProvince(ALL);
    void martProvinceOptions(CRIME_MART, region).then((opts) => {
      if (!cancelled) setProvinceOptions(opts);
    });
    return () => {
      cancelled = true;
    };
  }, [region, martOk]);

  useEffect(() => {
    if (martOk !== true) return;
    let cancelled = false;
    setLoading(true);
    const usingProvince = province !== ALL;
    const selections: Record<string, string> = {
      region: usingProvince ? province : region,
      [REGION_SCOPE]: usingProvince ? "province" : "region",
      offence,
      sex,
      age,
    };
    // Sequential, not Promise.all -- see OffendersTab's identical note above.
    void (async () => {
      const trend = await martTrendPivot(CRIME_MART, selections, splitBy);
      if (cancelled) return;
      const offenceBreakdown = await martBreakdown(CRIME_MART, "offence", selections, 10, breakdownYear || null);
      if (cancelled) return;
      const regionBreakdown = await martBreakdown(CRIME_MART, "region", selections, 25, breakdownYear || null);
      if (cancelled) return;
      const [rows, labels] = trend;
      setTrendRows(rows);
      setTrendLabels(labels);
      setByOffence(offenceBreakdown);
      setByRegion(regionBreakdown);
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [region, province, offence, sex, age, splitBy, breakdownYear, martOk]);

  const trendSpec = useMemo(() => {
    const seriesDefs =
      trendLabels.length === 0
        ? [{ key: "value", label: "Convictions", color: series(1) }]
        : trendLabels.map((label, i) => ({ key: `s${i + 1}`, label, color: series(i + 1) }));
    // Convictions are a headcount, same as the offenders trend above.
    return lineSeriesSpec(trendRows, { series: seriesDefs, yLabel: "Convictions", valueDecimals: 0 });
  }, [trendRows, trendLabels, mode]);

  const byOffenceSpec = useMemo(
    () => hBarSpec(byOffence, { xLabel: "Convictions", color: series(1) }),
    [byOffence, mode],
  );
  const byRegionSpec = useMemo(() => hBarSpec(byRegion, { xLabel: "Convictions", color: series(1) }), [byRegion, mode]);

  // Mirrors `data_gate(has_loaded, mart_ready, <content>, _no_mart_callout())`
  // in the Reflex reference (crime.py) -- see OffendersTab's identical gate
  // above.
  if (martOk === null) {
    return <Loading />;
  }
  if (martOk === false) {
    return <EmptyNote>{NO_MART_TEXT}</EmptyNote>;
  }

  return (
    <div>
      <p style={{ color: inkMuted(), fontSize: "0.85em", margin: "0 0 1rem" }}>
        Felonies of persons convicted by final judgement. Data through {latestYear}.
      </p>

      <Card title="Explore" subtitle="Filter, or split by one dimension (top 3 groups shown)">
        <div style={{ display: "flex", flexWrap: "wrap", gap: "1em", alignItems: "flex-end" }}>
          <LabeledSelect
            label="Region"
            testId="crime-convictions-region-select"
            options={options.region}
            value={region}
            onChange={setRegion}
            disabled={splitBy === "region"}
          />
          <LabeledSelect
            label="Province"
            testId="crime-convictions-province-select"
            options={provinceOptions}
            value={province}
            onChange={setProvince}
            disabled={splitBy === "region"}
          />
          <LabeledSelect
            label="Offence"
            testId="crime-convictions-offence-select"
            options={options.offence}
            value={offence}
            onChange={setOffence}
            disabled={splitBy === "offence"}
          />
          <LabeledSelect
            label="Sex"
            testId="crime-convictions-sex-select"
            options={options.sex}
            value={sex}
            onChange={setSex}
            disabled={splitBy === "sex"}
          />
          <LabeledSelect
            label="Age"
            testId="crime-convictions-age-select"
            options={options.age}
            value={age}
            onChange={setAge}
            disabled={splitBy === "age"}
          />
          <SplitBySelect
            testId="crime-convictions-split-select"
            options={CRIME_SPLIT_OPTIONS}
            value={splitBy}
            onChange={setSplitBy}
          />
        </div>
      </Card>

      <Card title="Convictions over time" subtitle="Annual totals for the current filters">
        <div data-testid="crime-convictions-trend">
          {loading ? (
            <Loading />
          ) : trendRows.length === 0 ? (
            <EmptyNote>No data for the current filters.</EmptyNote>
          ) : (
            <PlotFigure spec={trendSpec} />
          )}
        </div>
        {/* Same no-split gate as the offenders trend table (see the comment
         * there): s1/s2/s3 rows under a split have labels Reflex never prints. */}
        {!loading && trendRows.length > 0 && trendLabels.length === 0 && (
          <DataTable
            rows={trendRows}
            columns={[
              { key: "period", label: "Year" },
              { key: "value", label: "Convictions" },
            ]}
            testId="crime-convictions-trend-table"
          />
        )}
      </Card>

      <Card title="By offence type" subtitle="Selected year, current filters -- top 10">
        <LabeledSelect
          label="Year"
          testId="crime-convictions-year-select"
          options={years}
          value={breakdownYear}
          onChange={setBreakdownYear}
        />
        <div data-testid="crime-convictions-by-offence" style={{ marginTop: "0.75rem" }}>
          {loading ? (
            <Loading />
          ) : byOffence.length === 0 ? (
            <EmptyNote>No breakdown data for {breakdownYear || "this year"}.</EmptyNote>
          ) : (
            <PlotFigure spec={byOffenceSpec} />
          )}
        </div>
        {!loading && byOffence.length > 0 && (
          <DataTable
            rows={byOffence}
            columns={[
              { key: "name", label: "Offence type" },
              { key: "value", label: "Convictions" },
            ]}
            testId="crime-convictions-by-offence-table"
          />
        )}
      </Card>

      <Card title="By region" subtitle="Totals by region, selected year, current filters (same year as above)">
        <div data-testid="crime-convictions-by-region">
          {loading ? (
            <Loading />
          ) : byRegion.length === 0 ? (
            <EmptyNote>No regional data for {breakdownYear || "this year"}.</EmptyNote>
          ) : (
            <PlotFigure spec={byRegionSpec} />
          )}
        </div>
        {!loading && byRegion.length > 0 && (
          <DataTable
            rows={byRegion}
            columns={[
              { key: "name", label: "Region" },
              { key: "value", label: "Convictions" },
            ]}
            testId="crime-convictions-by-region-table"
          />
        )}
      </Card>
    </div>
  );
}

export default function Crime({ mode }: { mode: Mode }) {
  const [tab, setTab] = useState<"offenders" | "convictions">("offenders");

  const tabs: ReadonlyArray<["offenders" | "convictions", string]> = [
    ["offenders", "Offenders (police reports)"],
    ["convictions", "Convictions (courts)"],
  ];

  return (
    <div>
      <h1 style={{ color: inkPrimary(), margin: "0 0 1rem" }}>Crime</h1>
      <div style={{ display: "flex", gap: "1.25rem", marginBottom: "1.25rem", borderBottom: `1px solid ${gridline()}` }}>
        {tabs.map(([key, label]) => (
          <button
            key={key}
            type="button"
            data-testid={`crime-tab-${key}`}
            onClick={() => setTab(key)}
            style={{
              color: tab === key ? inkPrimary() : inkSecondary(),
              fontWeight: tab === key ? 700 : 400,
              background: "transparent",
              border: "none",
              borderBottom: tab === key ? `2px solid ${inkPrimary()}` : "2px solid transparent",
              padding: "0.5rem 0.1rem",
              marginBottom: "-1px",
              cursor: "pointer",
              fontSize: "0.95em",
            }}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "offenders" ? <OffendersTab mode={mode} /> : <ConvictionsTab mode={mode} />}
    </div>
  );
}
