# Deployment

Two public deployments exist, of two different frontends, with two different
purposes. **Netlify is the primary public demo**: it serves the static
(TypeScript/DuckDB-WASM) frontend under `web/` — no backend, no websocket,
every query runs client-side against Parquet fetched over HTTP, so there is no
cold start and nothing to keep warm. **Render is secondary**: it serves the
full Reflex app (Python backend, server-driven state over a websocket), kept
running as the reference implementation of the server-driven version of this
dashboard, with the free-tier caveats that come with that shape. The two are
separate sites with separate data-shipping rules; this page covers Netlify
first, then Render.

## Netlify (primary public demo)

**Live:** <https://italy-dashboard.netlify.app> (verified reachable, HTTP 200,
as of this writing). Deploys from `origin/main` on Netlify's own schedule
(a push to `main`, or a manual redeploy), so it can briefly lag behind a
local checkout with commits not yet pushed — it is a fresh build from the
repo, not a copy of whatever machine last edited these docs.

`web/` is a second, independent frontend: plain React + Observable Plot,
querying Parquet directly in the browser through DuckDB-WASM, no backend at
all. It ships as a static site on [Netlify](https://netlify.com), configured
by `netlify.toml` at the repo root, and serves the same eight pages the Reflex
app does (home, crime, population, education, climate, climate × crime,
labor, economy), built and deployed on its own schedule.

**English-only, unlike the Reflex app.** The Reflex app's navbar has an EN/IT
toggle (`italy_dashboard/translations.py` + `i18n.py`, persisted via
`rx.LocalStorage`); this frontend has no equivalent — every UI string is the
English literal baked into each `web/src/pages/*.tsx` file. Porting
`translations.py`, plus a second toggle and its own persistence, is a real
feature (every page's copy, not a config flag), so it is tracked here as a
known gap rather than added as part of an unrelated fix. Data labels (region,
crime, offence names) are English in both frontends regardless, straight from
ISTAT as fetched — see [Dashboard: Language](06-dashboard.md#language).

### Routing: hash-based, and deliberately no rewrite rule

Eight pages need client-side routing, but this app uses `#/slug` hash
routes (`web/src/router.tsx`'s `useRoute`/`ROUTES`, consumed by
`App.tsx`), not real paths handled by a history-API router. The reason is
tied directly to the excluded-mart behaviour below: a real-path router
needs a server-side catch-all (Netlify's `[[redirects]] from="/*"
to="/index.html"`) so a deep link like `/crime` doesn't 404 against a
static host that only has `index.html` on disk. That catch-all would also
intercept the request for `marts/mart_climate_daily.parquet` — a genuine,
deliberate 404 (see below) — and rewrite it to a `200` with `index.html`'s
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

`scripts/stage_web_data.py` copies the Parquet the app is allowed to ship
into `web/public-data/` (gitignored), which is what `web/vite.config.ts`'s
`publicDir` actually points at — never `data/` directly, which is small when
tracked but grows to hundreds of MB on a working checkout once raw CSVs, the
dbt scratch database, and the weather cache are on disk. The allowlist
(`STAGED`) is derived from `web/src/db.ts`'s own `PARQUET` list (16 datasets
as of this writing), so it cannot silently drift from what the app registers;
`web/package.json`'s `predev`/`prebuild` hooks run the same script
automatically, so `npm run dev`, `npm run build`, and this Netlify command all
publish identically. Staging keeps `web/dist` small regardless of how big the
underlying `data/` checkout is — the fix it replaced copied `data/` verbatim
through `publicDir` and produced an 875 MB build; a from-clone build against
the sample snapshot committed to this repo measures **1.2 MB**. The exact
figure moves with whatever real data is committed at the time — the point
verified here is the order of magnitude, not a number to pin.

**Called with plain `python3`, not `uv run`.** Netlify's build image does
not include `uv` — checked against both the current
["Available software at build time"](https://docs.netlify.com/build/configure-builds/available-software-at-build-time/)
docs and `netlify/build-image`'s own `included_software.md`; neither lists
it, only Python itself plus pip and Pipenv. `stage_web_data.py` has zero
third-party imports (stdlib only) precisely so it doesn't need one.

### What ships, and what's deliberately excluded

`STAGED` is every dataset in `web/src/db.ts`'s `PARQUET` list **except**
`marts/mart_climate_daily` (15 of 16, as of this writing) — kept off the
static build for one chart (the distribution histograms) because of its size
relative to the others. `web/src/db.ts::registerParquetViews` tolerates its
absence (skips the view, records the miss, every other query is unaffected),
and the climate page's distribution card shows an explanatory empty state
instead of erroring when a city scope needs it. Precomputing that one
chart's data at build time is a possible long-term answer, not done here.

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
browser. Confirmed empirically too: every DuckDB-WASM request in a built,
statically-served `web/dist` was for
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

- All eight routes (home, crime, population, education, climate,
  climate × crime, labor, economy) render a heading, draw real chart marks
  (not an empty chart), and repaint on the colour-mode toggle. Home has no
  chart by design (KPI tiles only) and is verified by heading + toggle alone.
- The colour-mode toggle actually repaints: body background switches between
  the light and dark surface tokens, and a stripe bar's `fill` resolves to
  the dark diverging ramp's neutral midpoint — confirming the palette CSS
  custom properties switch modes in a real built bundle, not only under
  `vite dev`.
- The distribution card shows its explanatory text, no thrown page errors.
- Walking all eight routes, every request returns 2xx **except**
  `marts/mart_climate_daily.parquet` (and DuckDB's own glob-fallback probe
  on that same path), both `404` — no other dataset 404s, and no missing
  JS chunk or asset on any route. `tests/browser/test_static_app.py` asserts
  this as a standing regression check, against a dedicated `built_static_app`
  fixture (`tests/browser/conftest.py`: a real `npm run build`, served by a
  plain `http.server`) rather than the rest of the file's usual `static_app`
  (Vite's dev server) — for the `Accept`-header reason above, `static_app`
  cannot tell a genuine 404 apart from Vite's own fallback either, so it is
  not a substitute for this one check.

**Deployed and live** at <https://italy-dashboard.netlify.app> (see "Live"
above). The checks above are this project's LOCAL build verification, run
before any deploy against a plain static server standing in for Netlify's own
(no-rewrite-rule) behaviour — they are not re-run against production in this
doc item-by-item; the live site is Netlify's own build of whatever commit
`origin/main` is at when it last deployed, which can legitimately be a few
commits behind a local checkout (this repo does not auto-push).

### Initial setup (already done for the URL above; reference for a fork)

This repo does not create Netlify sites or push to a hosting provider itself
— the steps below are what actually stood up the live URL above, kept here so
forking this repo (or standing up a second Netlify site) doesn't require
reverse-engineering them:

1. Create a Netlify site from this repository (Netlify UI: **Add new site →
   Import an existing project**, or `netlify init` with the Netlify CLI),
   pointing at the `main` branch. Netlify will read `netlify.toml`
   automatically; no manual build-command configuration needed.
2. **The build host needs the real data.** Unlike Render (which bakes in
   whatever the building checkout has), Netlify builds from a fresh clone of
   the repo, which is sufficient *provided the tracked branch actually has
   current data committed* (`just refresh`/`just sample` + `just transform`,
   committed, same as any other data update).
3. Confirm the build log actually runs `scripts/stage_web_data.py` before
   `vite build` (its stdout prints how many of the staged datasets it
   found) — every subsequent push to `main` redeploys the same way
   automatically, with no further manual steps.
4. To publish a data update: commit the refreshed snapshot to `main` and
   push; Netlify rebuilds and redeploys on its own. There is no
   fetch-on-deploy step, same as Render below — a rebuild is how you
   publish, not a running process that stays current on its own.

## Render (secondary: the full Reflex implementation)

**Live:** <https://italy-dashboard.onrender.com> (verified reachable, HTTP
200, as of this writing; expect a cold-start delay on the free tier's first
request after idle — see Free-tier caveats below). Like Netlify, this rebuilds
and redeploys from `origin/main` on its own trigger, not on every local
commit, so a fix that only exists in an unpushed local checkout is not live
here yet.

The dashboard also runs on [Render](https://render.com)'s free tier as a
single Docker container, as a working reference for the server-driven
(Python backend, websocket state) version of this app — not the deployment
this project points people to first. Render gives one exposed port,
terminates TLS itself, and spins the service down when idle, none of which
matches Reflex's default shape (a compiled React frontend on 3000, a
Starlette/FastAPI plus websocket backend on 8000). This section covers how
that gap is closed, what's genuinely verified to work, and the caveats that
come with the free tier.

### The single-port shape

[Caddy](https://caddyserver.com) runs inside the same container and is the
only thing Render's edge talks to. It serves the frontend, pre-exported to
static files at image-build time, and reverse-proxies the few routes that
belong to the Reflex backend:

| Route | Owner |
| --- | --- |
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

### `API_URL`: a build-time concern, not a runtime one

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

### Baking in the data snapshot

`data/` is gitignored, so the image cannot fetch or generate its own data:
it bakes in whatever already exists **on the checkout you build from**:

```
just refresh              # real data (ISTAT, INPS, MUR/USTAT)
just refresh-weather      # plus temperature, if you want it current
just docker-build         # or `just docker-serve` to also run it
```

(`just sample` for synthetic dev data works too, and is what
`docs/10-troubleshooting.md` calls out if you deploy it by mistake: the
charts look suspiciously smooth.)

Only `data/*.parquet` and `data/marts/*.parquet` are copied in, the exact
set `italy_dashboard/queries.py` reads. `data/raw/` (the raw CSV/JSON
downloads: potentially hundreds of MB, and actively growing while a
temperature backfill runs) and `data/dbt.duckdb` (a dev scratch file) are
dbt/ingestion inputs, not runtime dependencies, so they're left out: smaller
image, and the build no longer touches a directory a live backfill is
writing into.

If `data/marts` is empty, the build fails loudly at that `COPY` step with a
message telling you to run `just refresh` or `just sample` first, rather than
silently shipping an empty dashboard. **A rebuild is how you publish updated
data**: there is no scheduled refresh or fetch-on-deploy step; redeploying
without rebuilding just redeploys the same snapshot.

### What else the image has to carry

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

### Climate coverage on this deployment is whatever the backfill has reached

The temperature backfill (see [Datasets](04-datasets.md#weather_daily-temperature-non-istat))
progresses over days to weeks, not in one run. The Climate and Climate × Crime
pages surface their current coverage themselves via a coverage line rather
than silently presenting a partial snapshot as complete — that's a data
property, not a deployment one, but it means a given deploy can legitimately
be a partial snapshot, and the fix is the same rebuild-and-redeploy cycle
above, once the backfill has progressed further.

### Render setup

`render.yaml` defines the service: Docker runtime, free plan,
`healthCheckPath: /ping` (proxied straight to the backend by Caddy, so a 200
there means the whole chain is up, not just that Caddy is serving static
files). No secrets are needed or present: the app only ever reads public
snapshots baked into the image.

### Free-tier caveats

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

This is exactly why Netlify, not Render, is the deployment this project
points people to first: none of the above applies to a static site.

### Verification

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
5. **Every route hydrates clean, and the `Caddyfile`'s `try_files` resolves
   each route to its OWN prerendered file.** `tests/browser/
   test_render_deploy_shape.py` (needs `caddy` on `PATH`, e.g. `brew install
   caddy`; skips itself with a clear reason otherwise) spins up this exact
   shape — a real `reflex export --frontend-only`, a separate backend-only
   process, and Caddy reading this repo's own checked-in `Caddyfile` — and
   asserts zero React errors (hydration mismatches included) on a fresh,
   direct load of every route, that a direct route load actually renders
   THAT route's content rather than silently falling back to home's, and
   that a genuinely unknown path reaches the branded 404 page
   (`italy_dashboard/pages/not_found.py`). This is the regression test for a
   real defect: `try_files {path} /index.html` alone never matches Reflex's
   exported `<route>.html`/`<route>/index.html` files, so it fell straight to
   serving home's markup for every other route's direct load, which React
   Router then hydrated against the real (different) URL — a guaranteed
   React error #418 on every route but `/`, reproduced locally against this
   exact build before the `try_files` fix landed.

### Deploying

Push to the branch Render is watching, or point a new Blueprint at this repo
with `render.yaml`. There is no CI step that builds and bakes data
automatically: build locally (or in whatever pipeline you set up) from a
checkout with real data, then let Render build the image from the same
Dockerfile. Redeploy after every data refresh you want published.
