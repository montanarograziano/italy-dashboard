# Data-viz UX research: dovevannoinostrisoldi.com -> our React + Observable Plot dashboard

Sources: live HTML + built CSS chunks fetched 2026-08-25
(`/_next/static/immutable/chunks/288x42pykek47.css`, `0zdcoxjltc2we.css`, `2y5_bsq059n5o.css`),
pages `/`, `/spese/sanita`, `/territori`, `/confronti`, `/appalti`.
Plot API facts verified against the installed source at `web/node_modules/@observablehq/plot@0.6.17/src`.

---

## Reference site teardown (with hex tokens)

### Design tokens (verbatim from `:root`)

Light only. `<meta name="color-scheme" content="light">`, zero `prefers-color-scheme`
or `.dark` rules in the whole bundle. **There is no dark mode to copy.**

| Token | Value | Role |
| --- | --- | --- |
| `--color-bg` | `#f3f2f2` | page background (warm grey, not white) |
| `--color-surface` | `#eae9e9` | recessed surface |
| `--color-raised` | `#ffffff` | card/panel background |
| `--color-text` | `#201e1d` | ink primary (near-black, warm) |
| `--color-accent` | `#ec3013` | brand red (fills/bars only) |
| `--color-accent-700` | `#ae1800` | accent for **text/links** (7.17:1 on white) |
| `--color-divider` | `#201e1d66` | 40% ink |
| neutrals | `100 #f8f4f4` `200 #eae7e7` `300 #d7d3d3` `400 #bab6b6` `500 #9b9797` `600 #6a6666` `700 #605d5d` `800 #444141` `900 #2d2b2b` | |
| accent ramp | `100 #fff2ef` `200 #ffe0d9` `300 #ffc4b8` `400 #ff9783` `500 #ff563c` `600 #dd2b0f` `700 #ae1800` `800 #7c1405` `900 #4d170e` | choropleth uses 200/300/400/600/800 |
| semantic | positive `#1f6b46` bg `#e8f3ed` border `#b4d8c5`; warning `#8a5a06` bg `#fbf1de` border `#e6cf9d`; critical = accent-700/100/300 | status pills |

Chart colours are a **separate, explicit token set**, not the brand ramp:

```
--chart-primary:   var(--color-accent)        /* #ec3013 */
--chart-secondary: var(--color-neutral-800)   /* #444141 */
--chart-tertiary:  var(--color-neutral-500)   /* #9b9797 */
--chart-quaternary:var(--color-neutral-400)   /* #bab6b6 */
--chart-quinary:   var(--color-accent-300)    /* #ffc4b8 */
--chart-negative:  var(--color-accent-700)    /* #ae1800 */
--chart-category-blue:#2855a5  teal:#087c74  purple:#6b46a3
--chart-category-amber:#9a5b00 green:#2f6f44  slate:#405b70
```

Note the shape: **one accent + greys for "this vs context" charts**, a six-hue
categorical set held in reserve. All six categoricals are 5.0-7.2:1 on white,
i.e. they double as text colours. Nothing pastel, nothing neon.

### Elevation

There is essentially **no elevation**. Cards are flat:

```css
.panel { background: var(--color-raised); border: 1px solid var(--color-neutral-300); padding: 18px }
```

Depth = white card on `#f3f2f2` page + 1px `#d7d3d3` hairline. Shadow tokens exist
(`--shadow-sm: 0 1px 2px #2d2b2b24`, `--shadow-md: 0 3px 10px #2d2b2b29`,
`--shadow-lg: 0 12px 32px #2d2b2b38`) and opt-in classes `.elev-sm/.elev-md/.elev-lg`,
but the only thing that actually uses one is the tooltip (`--shadow-md`).

**Radii are all zero**: `--radius-sm/md/lg: 0px`. Square corners everywhere, including
buttons, inputs, tags, status pills. This is the single strongest stylistic signature
of the site: newspaper/statistical-bulletin, not SaaS.

### Typography

- One family: **Archivo** (variable 100-900) for both `--font-heading` and `--font-body`;
  fallback `system-ui, sans-serif`. Mono only for `<code>` (`ui-monospace, SFMono-Regular, Menlo`).
- `--font-heading-weight: 800`. Headings `line-height: 1.12`, `letter-spacing: -.015em`.
- Body `14px / 1.55` (13.5px under 620px).

| Element | Size | Weight | Other |
| --- | --- | --- | --- |
| brand | 24px | 700 | `-.02em` |
| `h1.page-intro` | 30px (24px mobile) | 800 | |
| hero number `.headline` | 38px | 800 | `-.03em`, `line-height 1.05`, **tabular-nums** |
| `.stat-strip` value | 24px (21px mobile) | 800 | `-.02em`, tabular-nums |
| `.panel-title` (card title) | **11px** | 800 | `uppercase`, `letter-spacing .09em`, colour `#605d5d` |
| table `thead th` | 11px | 600 | uppercase, `.08em`, colour `#6a6666` |
| table `td` | 13px | 400 | |
| bar/legend rows | 12px | | |
| micro-labels (`mapStats span`) | 10px | | uppercase `.07em`, `#6a6666` |
| notes/captions | 11-12.5px | | `#6a6666`/`#605d5d` |

Pattern worth stealing: **card titles are tiny uppercase eyebrows (11px), the number is
the headline (24-38px)**. Inverse of the usual "16px bold title, 14px body".

`font-variant-numeric: tabular-nums` appears **16 times** across the bundle: every
`.num` table cell, every stat value, every legend value, every rank/ratio figure.
No monospace font, just tabular figures on the proportional font.

### Spacing & layout

`--space-1..8`: 4/8/12/16/20/24/32px. Card padding **18px** (not on the 4px scale).
Grid gap `var(--space-4)` = 16px. Shell `max-width: 1560px`, gutter 28px -> 20px (<1100) -> 14px (<620).
Interactive targets pinned to `min-height: 44px` (buttons, inputs, `<summary>`, selects).

### Charts: there is no charting library

Every visual is hand-rolled HTML/CSS, server-rendered, zero client JS:

- **Bar list** (monthly payments): `<ul><li><span>label</span><i><b style="width:65.2%"></b></i><b class="num-tabular">7,46</b></li>`
  Grid `62px minmax(0,1fr) 38px`, track `#eae7e7`, fill `var(--color-accent)`, 10px tall, 7px gap.
  In-progress month gets a grey fill (`#9b9797`) + a sentence: "Agosto è ancora in corso: il numero salirà."
- **Donut**: an 88px `conic-gradient` div with a `mask: radial-gradient(circle, #0000 52%, #000 53%)`. Legend is a
  separate `<ul>` with 9x9px swatches, ellipsised label, tabular value. No SVG.
- **Ratio bar**: 10px track + `<i style="width:77.2%">`.
- **Choropleth**: the only SVG. 5 discrete fill classes from the accent ramp
  (`#ffe0d9 #ffc4b8 #ff9783 #dd2b0f #7c1405`) + `#eae7e7` no-data. Region stroke
  `#9b9797` 1px, hover/focus stroke `#201e1d` 2px, selected outline 2.5px,
  `vector-effect: non-scaling-stroke`, `transition: fill .14s, stroke .14s` (dropped under
  `prefers-reduced-motion`). Keyboard: Tab into the map, arrows to move, Enter to pin.
  Under `@media (hover:none)` the hover rule is neutralised and a `<select>` appears instead.
- **No axes, no gridlines, no ticks anywhere on the site.** Values are printed next to bars.

### Interaction patterns

- **No cursor-following tooltip on data.** Hover on the map only *previews* into a fixed
  detail panel beside/below the map; click or Enter *pins* it. Nothing important is
  hover-only.
- The only tooltip is a **glossary popover** on a `?` button:

  ```css
  width: 280px; background: var(--color-text) /* #201e1d */; color: #f8f4f4;
  box-shadow: var(--shadow-md); padding: 12px 14px; font-size: 12px; line-height: 1.5;
  position: absolute; top: calc(100% + 8px); right: 0;
  ```

  Anchored, not follow-cursor. 44x44 trigger with a 1px `#bab6b6` box drawn via `::before` inset 12px.
  `cursor: help`, `aria-expanded`, `data-open`/`data-positioned` for flip logic.
- **Legends are static**, never click-to-filter.
- **Every chart ships its data as a table** inside `<details class="chart-data">`
  (`border-top`, `<summary>` 44px min-height in `#ae1800` bold, `max-height: 360px` scroll).
  This is the site's answer to "the chart can't show every label".
- Row hover on tables: `background: #f8f4f4`. Nothing else moves.

### Table patterns

```css
.table            { border-collapse: collapse; width: 100%; font-size: 13px }
.table thead th   { text-align:left; font-size:11px; font-weight:600; text-transform:uppercase;
                    letter-spacing:.08em; color:#6a6666; padding:8px; border-bottom:1px solid #bab6b6 }
.table td         { padding:11px 8px; border-bottom:1px solid #eae7e7 }
.table tbody tr:hover { background:#f8f4f4 }
.table th[scope=row]  { text-align:left; font-weight:600 }   /* row header, not a td */
.table .num       { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap }
.table-scroll     { overflow-x:auto }  /* + role="region" aria-label tabindex="0" */
```

- Hairline row separators, **no zebra striping**, no vertical rules.
- Heavier `#bab6b6` rule under the header, lighter `#eae7e7` between rows.
- First column is `<th scope="row">`; a secondary line goes in a `<small>` inside it.
- **No sticky headers, no sort controls, no in-cell bars.** Ordering is decided server-side
  and stated in the card title ("Le regioni con più pagamenti per abitante"). The scroll
  container is a focusable labelled region, which is the accessibility-correct pattern.

### Number formatting

Italian locale, consistently: `11.066.679.779,02 €`, `1.236,72 €`, `77,2%`.
Currency symbol **after** with a space. Magnitude words, not SI prefixes:
`72,94 mld €`, `267,6 mln €`. Big totals in a table are shown in full precision;
the same value in a compact card is shown as `mld/mln` with 1-2 decimals. Unit lives in a
card-head note ("miliardi di €") when it would repeat on every row.

### Editorial patterns worth copying

- Every number is followed by scope in plain language: "Da gennaio a agosto 2026, in tutta Italia",
  "su 58.963.330 persone", "7.896 su 7.903 validi nel periodo".
- Every chart card carries a `?` glossary defining its own categories.
- Source freshness is a first-class panel: source name, status pill (Attiva), "Dati fino a",
  "File pubblicato il", "Scaricato da noi".
- Caveats are stated inline, not hidden: "Un pagamento non prova che il progetto sia finito."

---

## Observable Plot 0.6.17 recipes (code snippets)

All verified against installed source; line refs are to `node_modules/@observablehq/plot/src`.

### 1. Tooltips: `tip: true` shorthand, or an explicit `Plot.tip` + `pointer` transform

```js
// Shorthand: attaches a tip to this mark, using the pointer transform.
Plot.barY(rows, {x: "month", y: "value", fill: accent, tip: true})

// Explicit, for control over content and channel formatting:
Plot.plot({
  marks: [
    Plot.lineY(rows, {x: "period", y: "value", stroke: series(0)}),
    Plot.tip(rows, Plot.pointerX({
      x: "period",
      y: "value",
      title: (d) => `${d.period}\n${fmtEur(d.value)}`,  // \n = new line in the tip
      // or let Plot lay out channels and just format them:
      // format: {x: (y) => String(y), y: ",.1f", stroke: false}
    }))
  ]
})
```

- `Plot.pointer` / `Plot.pointerX` / `Plot.pointerY` (`src/interactions/pointer.js`).
  Use **`pointerX` for time series / band charts** (x is the independent variable),
  `pointerY` for horizontal ranking bars, plain `pointer` for scatter.
- `maxRadius` defaults to **40px**; raise it for sparse scatter, and note that on
  `pointerX` only the x distance counts.
- `Plot.tip` options that matter: `anchor` / `preferredAnchor` (default `"bottom"`,
  auto-flips to stay in frame), `format` (per-channel; `false`/`null` **hides** a channel),
  `textPadding` (8), `pointerSize` (12), `pathFilter` (drop shadow), `lineWidth`,
  `textOverflow`, `monospace`.
- Tips **follow the pointer** (anchored to the datum, box flips at frame edges). There is no
  built-in "pinned/anchored panel" mode. If we want the reference site's
  hover-previews-into-a-side-panel behaviour, that is our own React state, driven by
  `Plot.plot(...)`'s returned node + `pointermove`, not a Plot feature.

### 2. Crosshair

```js
Plot.crosshairX(rows, {x: "period", y: "value", color: inkMuted()})
```

`Plot.crosshair` / `crosshairX` / `crosshairY` (`src/marks/crosshair.js`) is a compound mark:
a rule pair + the x/y values printed just outside the bottom/left of the frame.
Defaults: `ruleStrokeOpacity 0.2`, `ruleStrokeWidth 1`, `maxRadius 40`,
`textStroke: "var(--plot-background)"` with `textStrokeWidth 5` (a halo). `color` sets both
`ruleStroke` and `textFill`.

### 3. Axis tick density

```js
x: {ticks: 5}                 // ~5 ticks (a count)
x: {interval: 5}              // a tick every 5 units  (NOT the same as ticks: 5)
x: {tickSpacing: 100}         // ~1 tick per 100px; default 80 on x, 35 on y
x: {ticks: "3 months"}        // temporal domains only
x: {ticks: [2015, 2020, 2025]}// explicit values
```

`src/marks/axis.js:561` -> `tickSpacing = k === "x" ? 80 : 35`, and
`ticks ?? maybeRangeInterval(interval) ?? inferTickCount(scale, tickSpacing)`.

**Band/ordinal axes are the trap.** For an ordinal scale with no `scale.interval`, the code
falls through to `data = domain` (`axis.js:612`): *every* category gets a tick, no thinning,
so 100 comuni give 100 overlapping labels. `tickSpacing` does nothing there. Fixes, in order
of laziness:

```js
// a) explicit thinned ticks
Plot.axisX(rows.map(d => d.name).filter((_, i) => i % 5 === 0), {})
// b) rotate + reserve margin
x: {tickRotate: -35}, marginBottom: 70
// c) flip to a horizontal bar chart (barX + y band) -- what the reference site effectively does
// d) truncate long labels
Plot.axisY({lineWidth: 12, textOverflow: "ellipsis-end"})
```

Per-axis overrides also live on the axis mark: `Plot.axisX({ticks, tickFormat, tickRotate,
tickSize, tickPadding, label, labelAnchor, labelArrow})`.

### 4. Theme-aware Plot

Plot injects, into every SVG it renders, a **zero-specificity** stylesheet (`src/plot.js:265`):

```css
:where(.plot-d6a7b5) { --plot-background: white; display:block; height:auto; max-width:100% }
```

`--plot-background: white` is **hardcoded** and is used by `Plot.tip`'s box fill
(`marks/tip.js:17`), `crosshair`'s text halo, tree labels and marker outlines. In dark mode an
un-overridden tip renders as a white box. Everything else (axis text, ticks, default stroke)
resolves to `currentColor`, so it inherits from the wrapping DOM.

The fix is one `style` object on the plot spec (`applyInlineStyles` -> inline style, which
always beats `:where(...)`):

```ts
const themed = (spec: Plot.PlotOptions): Plot.PlotOptions => ({
  ...spec,
  style: {
    background: "transparent",          // let the Card surface show through
    color: inkSecondary(),              // axis labels/ticks via currentColor
    "--plot-background": surface(),     // tip box fill + crosshair text halo
    fontFamily: "inherit",              // Plot defaults to 10px system sans
    fontSize: "12px",
  } as Partial<CSSStyleDeclaration>,
});
```

Because `currentMode()` reads `document.documentElement.dataset.theme` at call time, the spec
must be **rebuilt** when the theme flips: the theme value has to be a `useMemo` dependency of
every spec, and `PlotFigure`'s `[spec]` effect then re-renders the chart. Today nothing in
`charts/` reads the theme at spec-build time except colour helpers called once, so a runtime
theme toggle leaves stale colours baked into an already-rendered SVG.

0.6.17 constraints to keep in mind:

- No incremental update API. `Plot.plot()` returns a detached node; re-render = rebuild.
  `web/src/charts/plot.tsx` already does the right thing (`replaceChildren`).
- If `title`/`subtitle`/`caption` is set, `Plot.plot` returns a `<figure>`, **not** the `<svg>`.
  `plot.tsx`'s `chart.style.maxWidth = "none"` would then be set on the figure and miss the
  svg. Prefer our own React heading/caption over Plot's.
- Legends (`Plot.legend`, `color: {legend: true}`) are **static**; click-to-filter is our code.
- `interval` as a *scale* option and `interval` as an *axis* option mean different things
  (the source comments on this at `axis.js:566`).
- Tips need pointer events: don't put `pointer-events: none` on the container, and don't
  render into a node the parent re-creates on every render.

---

## Palette recommendations (light + dark, hex, with contrast ratios)

### Why our current dark theme reads flat

`shared/palette.json` dark is a **single-surface** theme: page and card are both `#1a1a1a`-ish,
so `Card`'s only depth cue is a `#2e2e2c` hairline at **1.2:1**. Nothing separates a card from
the page; nothing separates a tooltip from a card. Plus the dark categorical set is *darker*
than the light one (`#2072d0` = **3.62:1** on `#1a1a1e`, `#de5c27` = 4.68, `#00995f` = 4.73),
which is backwards: on a dark surface, series colours must get **lighter**, not darker. 3.62:1
is under the 4.5:1 you want for a thin 1px line series to be legible (WCAG 1.4.11's 3:1
non-text minimum assumes a chunky shape, not a 1px stroke).

The standard fix (Material's elevation-by-lighter-surface, GitHub Primer's canvas/default/subtle,
Apple's elevated backgrounds): **layered surfaces, elevation via a lighter surface plus a
hairline, and reduced max contrast for body text.** `#ffffff` on `#000000` is 21:1 and produces
halation on OLED; `#e6e6e6` on `#16161a` is 13.9:1 which is still ~3x AAA and far calmer.

### Light (adopt the reference site's values nearly verbatim)

| Role | Hex | Contrast |
| --- | --- | --- |
| page bg | `#f3f2f2` | |
| surface (card) | `#ffffff` | |
| surface raised (tooltip/popover) | `#201e1d` (inverted) | ink `#f8f4f4` on it: 15.4:1 |
| hairline border | `#d7d3d3` | 1.48:1 on white (decorative; fine, the surface offset carries it) |
| strong border (header rule, focus) | `#bab6b6` | 2.04:1 |
| gridline | `#eae7e7` | 1.2:1 |
| ink primary | `#201e1d` | **16.6:1** on `#fff`, 14.9:1 on `#f3f2f2` |
| ink secondary | `#605d5d` | **6.5:1** on `#fff` |
| ink muted (axis labels, captions) | `#6a6666` | **5.7:1** on `#fff`, 5.1:1 on `#f3f2f2` |
| accent (fills/bars) | `#ec3013` | |
| accent (text/links) | `#ae1800` | **7.2:1** on `#fff` |

Categorical, light, all >= 4.5:1 on `#ffffff` (so they work as text *and* as 1px strokes):
`#1f6fd0` 4.95 · `#c94b1a` 4.66 · `#1b7f5a` 4.96 · `#6b46a3` 6.93 · `#8a5a06` 5.92 · `#0f6f78` 5.89.
(The reference set `#2855a5 #087c74 #6b46a3 #9a5b00 #2f6f44 #405b70`, 5.1-7.2:1, is also fine
and slightly more muted; pick one, don't mix.)

### Dark (layered, this is the actual change)

| Role | Hex | Contrast |
| --- | --- | --- |
| page bg (canvas) | `#121214` | |
| surface-1 (card) | `#1a1a1e` | 1.08:1 vs canvas — visible as a *step*, not as contrast |
| surface-2 (tooltip, popover, hovered row, sticky header) | `#232329` | 1.11:1 vs surface-1 |
| hairline border | `#33333c` | 1.39:1 on surface-1 |
| interactive border (input, button, focusable) | `#6a6a77` | **3.26:1** on surface-1 (meets 1.4.11) |
| gridline | `#2a2a30` | 1.22:1 |
| ink primary | `#e6e6e6` | **13.9:1** on surface-1 (vs 21:1 for #fff on #000) |
| ink secondary | `#b3b3ba` | **8.3:1** |
| ink muted (axis labels) | `#9a9aa4` | **6.2:1** |
| ink on tooltip (surface-2) | `#e6e6e6` | **12.5:1** |

Categorical, dark, on `#1a1a1e`:
`#5aa9ff` 7.07 · `#ff8a5b` 7.47 · `#3ddc97` 9.82 · `#b48cff` 6.72 · `#ffcc4d` 11.56 · `#7fd4d0` 10.1.
Same hue order as light, lightened. Every one clears 4.5:1, so a 1px line is legible.

Sequential (choropleth) dark ramp on `#1a1a1e`, monotonically increasing luminance so the
legend order is unambiguous: `#1b5288` 2.16 · `#2a6fb0` 3.30 · `#4a92d4` 5.25 · `#7fb8ee` 8.26 ·
`#b8d9f7` 11.82. Reserve `#33333c` for "no data" and always label it in the legend.

Rules that come with this:

1. Elevation is **lighter surface + hairline**, never a shadow. Shadows are invisible on dark.
2. Never put a card directly on a card at the same value: page -> surface-1 -> surface-2, max 3 levels.
3. Body text caps at ~14:1. Save `#ffffff` for the one hero number per page, if at all.
4. Chart series colours are **mode-dependent** and must be read at render time, not module load.
5. Semantic colours need dark variants too: positive `#4ec98a` (7.9:1), warning `#e8b339` (already in
   `palette.json`, 9.4:1), critical `#ff6b5a` (6.4:1). `#1f6b46` / `#8f5e00` are unreadable on dark.

---

## Prioritised checklist for our dashboard

Current state (`web/src`): 5 chart spec modules, **zero** `Plot.tip`, zero `Plot.crosshair`,
zero `style:` on any spec, `Card` uses `borderRadius: 10px` + `1px solid gridline()` on
`surface()` with no page/card distinction, no tabular numerals anywhere, no data table under
any chart.

**P0 — correctness/legibility**

1. Add layered dark surfaces to `italy_dashboard/palette.py` (the generator source, not
   `palette.json` — a test asserts they match): `canvas`, `surface`, `surface_raised`,
   `border`, `border_interactive`. Regenerate via `scripts/generate_palette.py`.
2. Replace the dark categorical set (`#2072d0`/`#de5c27`/`#00995f`, 3.6-4.7:1) with the
   lightened set above (6.7-11.6:1).
3. Add a `themed(spec)` wrapper in `charts/plot.tsx` (or `theme.ts`) setting
   `style: {color, "--plot-background", background: "transparent", fontFamily: "inherit", fontSize: "12px"}`.
   Without `--plot-background` every future tip is a white box in dark mode.
4. Make theme a `useMemo` dependency of every chart spec so a mode toggle actually re-renders
   the SVG. Today the colours are frozen at first render.

**P1 — the interaction gap**
5. `tip: true` on `hBarSpec`'s `Plot.barX` and `Plot.tip(..., Plot.pointerX(...))` on
   `lineSeriesSpec` / `bandTrendSpec`. Format through `format.ts`, not d3 defaults.
6. `Plot.crosshairX` on multi-year line charts only. Not on bar charts (redundant with the tip).
7. Add `font-variant-numeric: tabular-nums` to every number: stat values, table cells,
   tip content (`Plot.tip({monospace: true})` is the blunt alternative but changes the font).

**P2 — density & structure (steal from the reference)**
8. Card restyle: page bg distinct from card bg; `borderRadius` 10px -> 0 or 4px; card title
   becomes an 11px uppercase `letter-spacing: .09em` eyebrow in `inkMuted()`, with the
   number/chart as the visual headline.
9. `<details>` data table under each chart, with the reference's `.table` rules
   (11px uppercase header, `th[scope=row]`, `.num` right-aligned tabular, hairline rows,
   no zebra, `overflow-x: auto` on a `role="region" tabindex="0"` wrapper).
10. Fix dense categorical axes before they bite: `hBarSpec` already flips to horizontal (good);
    for any x-band chart use explicit thinned `Plot.axisX(ticks)` or `tickRotate: -35`, and
    `lineWidth` + `textOverflow: "ellipsis-end"` on long y labels instead of `marginLeft: 160`.
11. Italian number formatting decision: `format.ts` deliberately mirrors Python's `str.format`
    (`584,514`), which is **wrong for an Italian-language dashboard** (`584.514`). Either the
    conformance matrix moves to `it-IT`, or the UI formats separately from the conformance
    values. Flagging, not deciding — it is a product call.

**P3 — editorial**
12. Per-card scope line under every headline number ("su 58.963.330 persone", "2015-2024").
13. A `?` glossary popover per card (anchored, `#201e1d` box, 280px, `--shadow-md`,
    44x44 trigger, `aria-expanded`), for the metric definitions currently buried in `subtitle`.
14. Source/freshness panel: dataset, status, "data through", "downloaded on".

**Explicitly not doing**

- Sticky table headers, sortable columns, in-cell bars, interactive legends: the reference site
  has none of them and is more usable for it. Add only when a specific table actually needs it.
- Shadows for elevation in dark mode.
- Any new charting dependency. Plot 0.6.17 covers every recipe above.

**Blind spots**

- The reference site is server-rendered and non-interactive by design; its "no hover tooltip"
  choice is partly a constraint, not purely a principle. Our client-side Plot charts can afford
  tips, and dropping them to imitate the reference would be cargo-culting.
- No dark mode exists there to copy, so the dark palette above is constructed from WCAG maths
  and platform conventions (Material/Primer), not from an observed reference.
- Contrast ratios were computed for flat fills. Thin 1px strokes and small text are
  perceptually weaker than their ratio suggests; verify the dark line charts on a real display.
