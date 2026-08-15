# Dashboard

Reflex app (`italy_dashboard/`), served by `just run` at `localhost:3000`.

## Pages

**Home** — KPI tiles: felony convictions, resident population, national
unemployment rate, latest annual inflation.

**Crime** — the core of the product, two tabs:

- *Offenders (police reports)* — interactive explorer over `mart_offenders`.
  Filters: region, crime type, citizenship, sex, age, indicator; a **Split by**
  selector turns the trend into a multi-series chart (top 3 groups; the split
  dimension's own filter disables itself); reset button. Below the trend:
  KPI tiles (total, year-over-year, foreign share, rate ratio), **offenders per
  1,000 residents by citizenship**, foreign share over time, a horizontal top-10
  crime ranking, and the income↔rate scatter with Pearson correlations. A
  permanent methodology note anchors interpretation.
- *Convictions (courts)* — same explorer pattern over `mart_crime`
  (region, offence, sex, age).

**Population** — residents (in millions) and foreign-residents share, by region.
**Labor** — regional unemployment vs the national rate (the IT row, not an
unweighted average of regions). **Economy** — annual inflation chained across
index rebasings.

## Language

The navbar's **EN · IT** toggle switches every UI label; the preference persists
via browser storage. Translations live in `italy_dashboard/translations.py`
(plain data) with a tiny reactive helper in `i18n.py`. To change the default
language, edit `lang: str = rx.LocalStorage("en")` in `state.py`.

Data labels (crime types, regions) come from ISTAT as fetched — currently
English. Fully Italian data labels would require re-fetching with an Italian
`Accept-Language`; parked as a known option.

## Chart conventions

Charts follow a validated, colorblind-safe palette (`theme.py`) with a fixed
slot order — multi-series charts stay within the first three slots, legends
appear at two or more series, tooltips everywhere, and every chart has a
collapsible table view. Numbers too large to read are scaled at the data level
(population in millions) because the chart wrapper exposes no tick formatters.
The two crime time charts share one year spine so their x-axes align even when
one series starts later.

### Palette

`italy_dashboard/palette.py` holds four colour roles as plain data, in light
and dark: categorical (three fixed slots, never cycled, so a series keeps its
identity across the mode toggle), diverging (7 steps, cool to warm, with a
true neutral gray at the midpoint), sequential (one hue, pale to deep), and
surfaces. Every value was derived by machine search against a colour
validator, not chosen by eye, and dark steps are selected against the dark
surface rather than mechanically inverted from light (an inversion fails the
dark lightness band outright).

Validation runs as a test, in two layers, in `tests/unit/test_palette.py`:
golden tests pin every constant literally, so an edit that changes a hex fails
everywhere including CI; a second set of tests re-runs the external validator
when it is available. The split exists because the validator lives at a
machine-specific path and would otherwise skip silently, looking like
coverage where there is none.

`theme.py` wraps the raw palette in Reflex's colour-mode conditional and
exposes accessors only (`series()`, `surface()`, `ink_primary()`,
`gridline()`, `axis()`, `border()`, ...); there are no public bare light-mode
constants, and a test asserts `theme` exposes no public string besides `FONT`.
An earlier version kept both a bare constant and an accessor for the same
colour, and most call sites quietly used the bare one, so toggling dark mode
flipped the page shell but left chart gridlines and axes pinned to light-mode
hex. A handful of call sites need a *complete* CSS value interpolated into a
string (a border declaration), not a bare colour: a Reflex Var does not
survive f-string interpolation the way a plain string does, so `border_css()`
and `tooltip_border_css()` build the whole declaration under
`color_mode_cond` rather than leaving callers to assemble it themselves.

Dark mode itself uses Reflex's native `rx.color_mode_cond` and
`rx.color_mode.button`; there is no custom dark-mode machinery.

### Encodings

Warming stripes (`stripe_chart` in `components.py`) are a diverging encoding:
each bar takes its own step of the 7-step ramp via `rx.recharts.cell`, so
colour carries the anomaly value directly. The earlier version was one flat
categorical hue, which is the wrong encoding for a quantity that has a sign
and a magnitude. Small multiples repeat the same stripe chart per city on the
shared colour scale, so panels compare against each other rather than each
carrying its own axis.

A per-datum colour (one hex per bar) cannot be a build-time constant and must
still follow the colour mode, so it resolves through CSS custom properties:
`palette.diverging_css_vars()` emits `--div-0` .. `--div-6` for both `:root`
and `.dark`, injected once by `components.py::shell()`, and each stripe's
`fill` is `var(--div-N)`.

Other charts: the crime/climate scatter draws reference lines at x=0 and y=0
only on the demeaned panel-data view, where both axes are centred on zero by
construction; the raw scatter (absolute summer temperature) leaves them off
because there is no natural zero to mark. The distribution-comparison chart
overlays translucent areas so the reader sees the shift in mass rather than
two thin lines. The tooltip is styled with surface and ink tokens so it stays
legible on a dark surface instead of the recharts default white box. The line
chart's brush is opt-in (off by default) since it is a scrubber meant for long
series and would be noise on short ones. One chart composes bars and a line
on a single shared y-axis by design: a second scale would let the chart pick
its own story.

The month-by-year anomaly heatmap remains absent: Recharts has no heatmap
mark, so it needs a different charting library, not more work inside the
current one.

### Hazards for future chart work

Two things cost real implementation time and are not obvious from reading the
component code:

- **Reflex silently swallows unrecognized component props.** A kwarg that is
  not a declared field on the underlying Reflex/recharts wrapper does not
  raise; it lands in a generic `wrapperStyle` prop that recharts never reads.
  The code looks correct, render-tree tests pass, and the chart is still
  wrong in the browser. `fill_opacity` on `Area` is the case that actually
  happened here: it is not a declared field, so the translucency in the
  distribution-comparison chart never applied. The fix is `custom_attrs=
  {"camelCaseName": value}` after confirming the prop's absence with
  `Cls.get_fields()`; `_grid()`'s `strokeWidth` and the tooltip's `content_style`
  in `components.py` document worked and non-worked cases side by side.
- **Recharts children must be passed positionally, not as a `children=`
  keyword.** `Bar.create(*children, **props)` forwards `**props` into
  `Component._create(children, **props)`, so a `children=` kwarg collides
  with that positional argument and raises `TypeError: got multiple values
  for argument 'children'`. This is why `stripe_chart` passes its
  `rx.recharts.cell` foreach as a bare positional argument to
  `rx.recharts.bar(...)`.

Verification to date is render-tree tests and a frontend compile; nobody has
opened these pages in a browser yet.

## How state and queries connect

Each page has a Reflex substate that loads via `on_load` and re-queries on every
filter change. All SQL lives in `italy_dashboard/queries.py`; every call opens an
in-memory DuckDB, creates views over the current parquet files, and returns plain
dicts. No cache to invalidate: refresh the data, reload the page.
