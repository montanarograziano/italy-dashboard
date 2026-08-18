# Deployment

Two deployments exist, of two different frontends. **Render is canonical**:
it serves the Reflex app (Python backend, server-driven state over a
websocket) and is what the dashboard's URL is meant to be. **Netlify serves
the static (TypeScript/DuckDB-WASM) frontend under `web/`**: no backend, no
websocket, every query runs client-side against parquet fetched over HTTP.
The two are separate sites with separate data-shipping rules; see
[Netlify](#netlify-the-static-frontend) below for the second one. This page
covers Render first, then Netlify.

The dashboard runs on [Render](https://render.com)'s free tier as a single
Docker container. Render gives one exposed port, terminates TLS itself, and
spins the service down when idle, none of which matches Reflex's default
shape (a compiled React frontend on 3000, a Starlette/FastAPI plus websocket
backend on 8000). This section covers how that gap is closed, what's
genuinely verified to work, and the caveats that come with the free tier.

## The single-port shape

[Caddy](https://caddyserver.com) runs inside the same container and is the
only thing Render's edge talks to. It serves the frontend, pre-exported to
static files at image-build time, and reverse-proxies the few routes that
belong to the Reflex backend:

| Route | Owner |
|---|---|
| `/_event/*` | Backend: the Socket.IO/websocket endpoint (state sync) |
| `/ping` | Backend: liveness probe, also Render's health check path |
| `/_upload` | Backend: file uploads (registered only if `rx.upload()` is used; this app doesn't use it, proxied anyway for correctness) |
| everything else | Static files from the exported frontend |

This route list was read out of the installed `reflex==0.9.8` package
(`reflex_base/constants/event.py::Endpoint`, `reflex/app.py`
`_add_default_endpoints`/`_add_optional_endpoints`), not assumed from general
Reflex docs. A version bump is the thing most likely to change it, so if
this stops working after an upgrade, check that file first. Reflex also ships
a `reflex run --single-port` flag, but in 0.9.8 it's validated and then never
wired to anything (`reflex/reflex.py`): it does not do what the name implies,
which is why this project uses the documented Caddy pattern instead.

At runtime, `scripts/start.sh` starts the Reflex backend (`reflex run
--backend-only`, bound to `127.0.0.1:8000`, unreachable from outside the
container) and Caddy (bound to `$PORT`) as sibling processes, and exits
non-zero the moment either one dies, so a crashed backend takes the
container down with it instead of leaving Caddy serving a static shell over a
dead backend.

## `API_URL`: a build-time concern, not a runtime one

The frontend's websocket/API base URL is baked into the exported static JS
bundle when `reflex export` runs (Reflex writes it to `.web/env.json`, which
Vite inlines into the built chunks): setting an env var on the *running*
container has no effect on an already-exported bundle. The Dockerfile exposes
it as a **build arg**, `API_URL`, defaulting to `http://localhost:10000`.

That default works for both cases here, for a reason worth understanding
rather than taking on faith: Reflex's own frontend runtime
(`utils/state.js::getBackendURL`) treats the hostnames `localhost`, `0.0.0.0`
and a couple of IPv6 equivalents as "same origin as the page" and rewrites
them to the page's real hostname at connection time. When the page is loaded
over **https** (Render terminates TLS in front of Caddy), it additionally
upgrades `ws:`/`http:` to `wss:`/`https:` and drops the port entirely,
assuming a load balancer in front. That's exactly Render's topology, so the
built-in default self-heals to the correct public `wss://` URL with no
override needed. It only stays completely literal under plain http (this
project's own local single-port test), which is why the baked port must
match Caddy's `$PORT` rather than Reflex's usual 8000, verified by actually
running the container and confirming the websocket connects (see
Verification below).

Render's Blueprint (`render.yaml`) **cannot** pass custom Docker build args,
confirmed against Render's Blueprint spec, which documents `dockerfilePath`
and `dockerContext` but no build-arg mechanism, so `REFLEX_API_URL` is
deliberately **not** set as a Render env var: it would be a silent no-op
against an already-built image. Override `API_URL` only if you change the
topology (custom domain quirks, a non-TLS proxy in front, etc.):

```
docker build --build-arg API_URL=https://your-domain.example .
```

## Baking in the data snapshot

`data/` is gitignored, so the image cannot fetch or generate its own data:
it bakes in whatever already exists **on the checkout you build from**:

```
just refresh              # real ISTAT data
just refresh-weather      # plus temperature, if you want it current
just docker-build         # or `just docker-serve` to also run it
```

(`just sample` for synthetic dev data works too, and is what
`docs/10-troubleshooting.md` calls out if you deploy it by mistake: the
charts look suspiciously smooth.)

Only `data/*.parquet` and `data/marts/*.parquet` are copied in, the exact
set `italy_dashboard/queries.py` reads. `data/raw/` (the raw ISTAT CSV and
Open-Meteo JSON downloads: hundreds of MB, and actively growing while the
temperature backfill runs) and `data/dbt.duckdb` (a dev scratch file) are
dbt/ingestion inputs, not runtime dependencies, so they're left out: smaller
image, and the build no longer touches a directory a live backfill is
writing into.

If `data/marts` is empty, the build fails loudly at that `COPY` step with a
message telling you to run `just refresh` or `just sample` first, rather than
silently shipping an empty dashboard. **A rebuild is how you publish updated
data**: there is no scheduled refresh or fetch-on-deploy step; redeploying
without rebuilding just redeploys the same snapshot.

## What else the image has to carry

Data is not the only thing read at runtime rather than imported. The query
layer resolves `shared/queries/<name>.sql` from disk on every call (the same
files the static frontend imports, see
[Architecture](02-architecture.md)) and `dbt/seeds/province_capitals.csv` for
the coverage denominators. A file like that is invisible to the entire test
suite when it is missing from the image: the code imports fine and the
container still raises `FileNotFoundError` on the first query. It happened
once — `shared/` was extracted out of `queries.py` and the Dockerfile was not
updated, which would have left three pages stuck on the loading placeholder in
production.

`tests/unit/test_deployment_paths.py` now derives the required set from the
code's own `Path` constants and fails if any of them stops being copied (or
gets excluded by `.dockerignore`), so the next extraction is caught by the
suite rather than by a deploy. **If you add a runtime-read file outside
`italy_dashboard/`, add a `COPY` for it** — the test will tell you.

## The dashboard currently ships partial weather coverage

The temperature backfill is still running as of this writing: about 40 of
106 province capitals and 10 of 21 regions have data. The Climate and
Climate x Crime pages surface this themselves via a coverage line rather than
silently showing an incomplete picture as complete, that's a data property,
not a deployment one, but it means **today's deploy is a partial snapshot on
purpose**, and the fix is the same rebuild-and-redeploy cycle above, once the
backfill has progressed further.

## Render setup

`render.yaml` defines the service: Docker runtime, free plan,
`healthCheckPath: /ping` (proxied straight to the backend by Caddy, so a 200
there means the whole chain is up, not just that Caddy is serving static
files). No secrets are needed or present: the app only ever reads public
ISTAT/Open-Meteo snapshots baked into the image.

## Free-tier caveats

Read these before treating this as more reliable than it is:

- **Spin-down on idle.** Render's free tier stops the container after a
  period of inactivity. The first request after that pays a full cold
  start (container boot plus Reflex backend startup) before anything
  responds.
- **Websocket disconnects on spin-down.** Reflex holds per-session state over
  that same websocket; a spin-down mid-session drops the connection and the
  user's in-progress state with it. There's no session persistence across
  that boundary on the free tier.
- **A known Reflex/Caddy interaction drops idle websockets.** See
  [reflex-dev/reflex#4236](https://github.com/reflex-dev/reflex/issues/4236):
  the single-port Caddy setup this project uses is reported to drop
  websocket connections after a period of client inactivity, independent of
  Render's own spin-down. Not specifically reproduced here, but worth
  watching for reports of "the page loads but stops updating" after a tab
  has sat idle a while.
- **512 MB RAM is not generous.** Measured locally (see Verification): the
  container idles around 190 to 220 MB serving one browser session,
  comfortably under the cap. That's a single-session baseline, not a load
  test: Reflex keeps per-session state in-process, so concurrent sessions add
  up faster than a stateless app would. Worth watching in production, not
  just trusting the local measurement.

## Verification

Local proof this actually works, using `just docker-serve`:

1. **Image builds.** `docker build` succeeds from a checkout with
   `data/marts` populated; without it, the build fails at the data-check
   step with a readable message instead of a generic Docker error.
2. **Single-port run.** `just docker-serve` (or plain `docker run -p
   10000:10000 italy-dashboard`) starts Caddy and the backend as one
   container, one exposed port.
3. **Real HTML, not a dead shell.** `/`, `/climate`, and `/climate-crime` all
   return HTTP 200 with the compiled React shell (not a 502, not an empty
   page).
4. **The websocket path is live, not just the static page.** A 200 on `/`
   only proves Caddy is up, it says nothing about the backend. Two
   independent checks against the *same running container* prove the
   backend is actually reachable and driving state through Caddy:
   - `GET /ping` through the proxy returns Reflex's own `"pong"`, meaning
     Caddy's `/ping` route successfully reached the backend process on
     `localhost:8000` inside the container.
   - The existing Playwright suite (`tests/browser/`, needs `uv sync --extra
     browser` plus `uv run playwright install chromium`) can point at an
     already-running server instead of spawning its own, via
     `BROWSER_TEST_BASE_URL`:
     ```
     BROWSER_TEST_BASE_URL=http://localhost:10000 \
       uv run pytest tests/browser -m browser
     ```
     These tests assert on values read back from the browser's own
     `getComputedStyle` on chart elements (axis tick contrast, band opacity,
     stripe colours) that only exist once the climate page's state has
     actually loaded over the websocket: a static shell with a dead backend
     would never produce them. All three passed against the container.

## Deploying

Push to the branch Render is watching, or point a new Blueprint at this repo
with `render.yaml`. There is no CI step that builds and bakes data
automatically: build locally (or in whatever pipeline you set up) from a
checkout with real data, then let Render build the image from the same
Dockerfile. Redeploy after every data refresh you want published.

## Netlify (the static frontend)

`web/` is a second, independent frontend: plain React + Observable Plot,
querying parquet directly in the browser through DuckDB-WASM, no backend at
all. It ships as a static site on [Netlify](https://netlify.com), configured
by `netlify.toml` at the repo root. **Render remains canonical** — this is a
separate deployment that now serves the same seven pages the Reflex app does
(home, economy, labor, population, crime, climate, climate × crime), built
and deployed on its own schedule.

### Routing: hash-based, and deliberately no rewrite rule

Seven pages need client-side routing, but this app uses `#/slug` hash
routes (`web/src/router.tsx`'s `useRoute`/`ROUTES`, consumed by
`App.tsx`), not real paths handled by a history-API router. The reason is
tied directly to the excluded-mart behaviour above: a real-path router
needs a server-side catch-all (Netlify's `[[redirects]] from="/*"
to="/index.html"`) so a deep link like `/crime` doesn't 404 against a
static host that only has `index.html` on disk. That catch-all would also
intercept the request for `marts/mart_climate_daily.parquet` — a genuine,
deliberate 404 (see above) — and rewrite it to a `200` with `index.html`'s
HTML content instead. `registerParquetViews` (`web/src/db.ts`) would then
hand that HTML to DuckDB-WASM's parquet reader as if it were the file,
turning a tolerated, recorded absence into a hard parse error on every
page that touches the mart, not a clean skip.

Hash routes never hit the server for a route change at all — the browser
resolves everything after `#` client-side, so there is nothing for a
rewrite rule to do and therefore no reason to add one. `netlify.toml` has
no `[[redirects]]` block, on purpose, and should stay that way; adding one
"to be safe" would silently break the one 404 this deploy relies on being
real.

### What builds

```toml
command = "python3 scripts/stage_web_data.py && npm --prefix web ci && npm --prefix web run build"
publish = "web/dist"
```

`scripts/stage_web_data.py` copies the parquet the app is allowed to ship
into `web/public-data/` (gitignored), which is what `web/vite.config.ts`'s
`publicDir` actually points at — never `data/` directly, which is 14 MB
tracked but ~850 MB on a working checkout (raw CSVs, `dbt.duckdb`, the
weather cache, every mart). The allowlist (`STAGED`) is derived from
`web/src/db.ts`'s own `PARQUET` list, so it cannot silently drift from what
the app registers; `web/package.json`'s `predev`/`prebuild` hooks run the
same script automatically, so `npm run dev`, `npm run build`, and this
Netlify command all publish identically. A from-clone `npm --prefix web run
build` now produces a **4.7 MB** `web/dist` (was 875 MB before staging was
introduced, because `publicDir` used to copy all of `data/` verbatim).

**Called with plain `python3`, not `uv run`.** Netlify's build image does
not include `uv` — checked against both the current
["Available software at build time"](https://docs.netlify.com/build/configure-builds/available-software-at-build-time/)
docs and `netlify/build-image`'s own `included_software.md`; neither lists
it, only Python itself plus pip and Pipenv. `stage_web_data.py` has zero
third-party imports (stdlib only) precisely so it doesn't need one.

### What ships, and what's deliberately excluded

`STAGED` is every dataset in `web/src/db.ts`'s `PARQUET` list **except**
`marts/mart_climate_daily` — 10 MB of the 14 MB tracked snapshot, for one
chart (the distribution histograms). `web/src/db.ts::registerParquetViews`
tolerates its absence (skips the view, records the miss, every other query
is unaffected), and the climate page's distribution card shows an
explanatory empty state instead of erroring when a city scope needs it.
Precomputing that one chart's data at build time — the spec's long-term
answer — is out of scope for this deploy; see the plan's self-review for why.

### Headers: none added, on purpose

DuckDB-WASM's `selectBundle` picks its cross-origin-isolated, multi-threaded
`coi` bundle only when the browser is actually cross-origin-isolated (needs
`Cross-Origin-Opener-Policy` + `Cross-Origin-Embedder-Policy`) **and** the
bundle set it was given includes one. `web/src/db.ts` calls
`duckdb.selectBundle(duckdb.getJsDelivrBundles())`, and
`getJsDelivrBundles()` never returns a `coi` entry at all (confirmed by
reading `@duckdb/duckdb-wasm`'s `dist/duckdb-browser.mjs` and
`dist/types/src/platform.d.ts`) — only `mvp` and `eh`. COOP/COEP would
therefore have **zero effect** on bundle selection here: the app always
resolves to the `eh` (exception-handling, single-threaded) bundle in any
browser with WebAssembly exception support, which is every current major
browser. Confirmed empirically too (see Verification): every DuckDB-WASM
request in a built, statically-served `web/dist` was for
`duckdb-eh.wasm`/`duckdb-browser-eh.worker.js`, and `window.crossOriginIsolated`
was `false`. Adding COEP anyway would only add risk: `require-corp` blocks
cross-origin subresources unless they opt in, and this page's DuckDB
wasm/workers, and the parquet extension, all load from jsDelivr/
`extensions.duckdb.org` — cross-origin CDNs this app depends on working.

### Verification

Local proof, `npm --prefix web run build` then serving `web/dist` with a
plain static file server (not `vite preview`, and — a finding worth
recording, since it is easy to assume otherwise — not Vite's own **dev**
server either: both apply an SPA fallback that returns `200` with
`index.html`'s content for a request that doesn't match any file. Reading
`htmlFallbackMiddleware` directly (`web/node_modules/vite/dist/node/chunks/`)
shows it triggers on the request's `Accept` header — absent, empty, or
`*/*` — not on the URL's file extension, and a plain `fetch()` with no
explicit `Accept` (exactly what DuckDB-WASM's httpfs reader sends) matches
that condition regardless of whether the path ends in `.parquet`. Confirmed
by hand: a bare `curl` against a running `npm run dev` gets `200`/`text/html`
for the missing mart; only forcing `Accept: application/octet-stream` gets
the real `404`. Only a plain server with no SPA fallback at all — matching
Netlify's default of no rewrite rule — gives the real status), driven with
Playwright:

- `web/dist` measured **4.8 MB** from a from-clone build (baseline was
  4.7 MB with only the climate page shipped) — six added pages contributed
  JavaScript, not data; the 13 staged parquet are unchanged.
- All seven routes (home, economy, labor, population, crime, climate,
  climate × crime) render a heading, draw real chart marks (not an empty
  chart), and repaint on the colour-mode toggle. The climate page's
  annual-series chart reaches real data on first load (~2.3s from
  navigation to marks rendered locally, including DuckDB-WASM's ~3-5 MB
  initial download — not the same as a cold Netlify edge request, but the
  right order of magnitude to expect); the climate × crime panel scatter
  draws 200+ points; home has no chart by design (four KPI tiles only) and
  is verified by heading + toggle alone.
- The colour-mode toggle actually repaints: body background
  `rgb(252, 252, 251)` (light) → `rgb(26, 26, 25)` (dark), and a stripe
  bar's `fill` resolved to `rgb(76, 77, 76)` — the dark diverging ramp's
  neutral midpoint (`#4c4d4c`), confirming the Fix 0 palette CSS actually
  switches modes in a real built bundle, not only under `vite dev`.
- The distribution card shows its explanatory text, no thrown page errors.
- Walking all seven routes, every request returned 2xx **except**
  `marts/mart_climate_daily.parquet` (and DuckDB's own glob-fallback probe
  on that same path), both `404` — no other dataset 404s, and no missing
  JS chunk or asset on any route. `tests/browser/test_static_app.py` now
  asserts this as a standing regression check, against a dedicated
  `built_static_app` fixture (`tests/browser/conftest.py`: a real
  `npm run build`, served by a plain `http.server`) rather than the rest of
  the file's usual `static_app` (Vite's dev server) — for the `Accept`-header
  reason above, `static_app` cannot tell a genuine 404 apart from Vite's own
  fallback either, so it is not a substitute for this one check.

Not yet verified: an actual deployed Netlify URL. See below.

### What's left to deploy (manual, one-time)

This repo does not create Netlify sites or push to a hosting provider. To
finish the deploy:

1. Create a Netlify site from this repository (Netlify UI: **Add new site →
   Import an existing project**, or `netlify init` with the Netlify CLI),
   pointing at the `static-app-shell` branch (or whatever branch/tag this
   lands on). Netlify will read `netlify.toml` automatically; no manual
   build-command configuration needed.
2. **The build host needs the real data.** Unlike Render (which bakes in
   whatever the building checkout has), Netlify builds from a fresh clone
   of the repo, which after a merge to the tracked branch has the 14 MB of
   git-tracked parquet checked in — that's sufficient, no extra data step
   is needed on Netlify's side, *provided the branch actually has current
   data committed* (`just refresh`/`just sample` + `just transform`,
   committed, same as any other data update).
3. Trigger the first deploy and confirm the build log actually runs
   `scripts/stage_web_data.py` before `vite build` (its stdout prints how
   many of the 13 staged datasets it found).
4. Once live, re-run the Verification checks above against the real URL —
   particularly the DuckDB-WASM bundle choice and `crossOriginIsolated`,
   which this doc predicts from source but a browser hitting Netlify's
   actual response headers is the real proof — and record the first-load
   time and the deployed URL here.
