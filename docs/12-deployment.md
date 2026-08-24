# Deployment

**One deployment exists: GitHub Pages**, serving the static
(TypeScript/DuckDB-WASM) frontend under `web/` — no backend, no websocket,
every query runs client-side against Parquet fetched over HTTP, so there is
no cold start and nothing to keep warm. The Reflex app (Python backend,
server-driven state over a websocket) is a **local-only reference
implementation**: it is not hosted anywhere, it never was on Pages (a static
host cannot run a Python backend or hold a websocket open), and the Netlify
and Render deployments that used to host the static frontend and the Reflex
app respectively have both been retired — see "Why hosting was dropped"
below for what that leaves as the one real gap in the public demo. This page
covers GitHub Pages first, then how to run the Reflex app locally.

## GitHub Pages

**Live:** <https://montanarograziano.github.io/italy-dashboard/> — a GitHub
Pages *project site* (this repo has no custom domain attached, and neither
does the account's `montanarograziano.github.io` user site, so the project
URL is the plain `https://<owner>.github.io/<repo>/` shape, not something to
assume without checking: a custom domain on either repo would change it).
Deploys from `origin/main` via `.github/workflows/pages.yml` on every push,
using GitHub's own Actions-based Pages pipeline
(`actions/configure-pages` → build → `actions/upload-pages-artifact` →
`actions/deploy-pages`) — no third-party build host involved.

`web/` is a second, independent frontend: plain React + Observable Plot,
querying Parquet directly in the browser through DuckDB-WASM, no backend at
all. It serves the same eight pages the Reflex app does (home, crime,
population, education, climate, climate × crime, labor, economy).

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
needs a server-side catch-all (a rewrite rule sending every path back to
`/index.html`) so a deep link like `/crime` doesn't 404 against a static
host that only has `index.html` on disk. That catch-all would also intercept
the request for `marts/mart_climate_daily.parquet` — a genuine, deliberate
404 (see below) — and rewrite it to a `200` with `index.html`'s HTML content
instead. `registerParquetViews` (`web/src/db.ts`) would then hand that HTML
to DuckDB-WASM's parquet reader as if it were the file, turning a tolerated,
recorded absence into a hard parse error on every page that touches the
mart, not a clean skip.

Hash routes never hit the server for a route change at all — the browser
resolves everything after `#` client-side, so there is nothing for a rewrite
rule to do and therefore no reason to add one. GitHub Pages has no
rewrite-rule mechanism to reach for even if this app wanted one (unlike, say,
Netlify's `[[redirects]]`, deliberately never used by this app's previous
Netlify build either, for the same reason) — hash routing needs no server
configuration on ANY static host, which is exactly why moving hosts never
touched this at all.

### The one thing that DOES change across hosts: the path prefix

A GitHub Pages *project* site (this one) is served under `/italy-dashboard/`,
not site root — unlike a plain domain root, which is where this frontend's
previous Netlify build served from. `web/vite.config.ts` has no hardcoded
`base`; instead `.github/workflows/pages.yml` passes `--base` to `vite
build` from `actions/configure-pages`'s own `base_path` output
(`/italy-dashboard` today; `""` if this repo ever grows a custom domain), so
the build always matches wherever Pages actually serves it, no matter how
that changes later.

Getting this right required one real code fix, not just a build flag:
`registerParquetViews` (`web/src/db.ts`) used to build every parquet URL off
`window.location.origin` directly — correct at site root, silently wrong
under a path prefix, since it would request
`{origin}/economy_inflation.parquet` instead of
`{origin}/italy-dashboard/economy_inflation.parquet`. It now reads
`import.meta.env.BASE_URL` (the same value Vite bakes in from `--base`) and
prefixes every parquet URL with it, so the same source works unmodified at
root (local dev) or under a subpath (GitHub Pages).
`tests/browser/test_pages_subpath.py` is the standing regression check: a
real `vite build --base=/italy-dashboard/`, served from under that exact
prefix with no SPA fallback, asserting every first-party request (bundle,
parquet) actually resolves under `/italy-dashboard/` and that the
deliberately-excluded mart still genuinely 404s there too, not just at root.
`.github/workflows/ci.yml`'s `web` job also runs this exact subpath build
(`--base=/italy-dashboard/`) as a fast typecheck-adjacent signal, before the
slower browser suite spends real time on it.

### What builds

```yaml
# .github/workflows/pages.yml (build job, abbreviated)
- uses: actions/configure-pages@...   # -> steps.pages.outputs.base_path
- run: npm ci
  working-directory: web
- run: npm run build -- --base="${PAGES_BASE_PATH}/"
  working-directory: web
  env:
    PAGES_BASE_PATH: ${{ steps.pages.outputs.base_path }}
- uses: actions/upload-pages-artifact@...
  with:
    path: web/dist
```

`scripts/stage_web_data.py` copies the Parquet the app is allowed to ship
into `web/public-data/` (gitignored), which is what `web/vite.config.ts`'s
`publicDir` actually points at — never `data/` directly, which is small when
tracked but grows to hundreds of MB on a working checkout once raw CSVs, the
dbt scratch database, and the weather cache are on disk. The allowlist
(`STAGED`) is derived from `web/src/db.ts`'s own `PARQUET` list (16 datasets
as of this writing), so it cannot silently drift from what the app registers;
`web/package.json`'s `predev`/`prebuild` hooks run the same script
automatically before `npm run build` above, so `npm run dev`, `npm run
build`, and this workflow all publish identically. Staging keeps `web/dist`
small regardless of how big the underlying `data/` checkout is — the fix it
replaced copied `data/` verbatim through `publicDir` and produced an 875 MB
build; a from-clone build against the sample snapshot committed to this repo
measures **1.2 MB**. The exact figure moves with whatever real data is
committed at the time — the point verified here is the order of magnitude,
not a number to pin.

Builds against the git-tracked `data/marts` snapshot committed to `main` — no
ISTAT/INPS/USTAT fetch, no dbt run, happens in this workflow; the data is
whatever was last committed.

### What ships, and what's deliberately excluded

`STAGED` is every dataset in `web/src/db.ts`'s `PARQUET` list **except**
`marts/mart_climate_daily` (15 of 16, as of this writing) — kept off the
static build for one chart (the distribution histograms) because of its size
relative to the others. `web/src/db.ts::registerParquetViews` tolerates its
absence (skips the view, records the miss, every other query is unaffected),
and the climate page's distribution card shows an explanatory empty state
instead of erroring when a city scope needs it. Precomputing that one
chart's data at build time is a possible long-term answer, not done here.

### Headers: none needed

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
browser. Moot for GitHub Pages specifically, too: Pages has no mechanism to
set custom response headers at all, so there is no COOP/COEP knob to reach
for even if it mattered. Adding it anyway would only add risk:
`require-corp` blocks cross-origin subresources unless they opt in, and this
page's DuckDB wasm/workers, and the parquet extension, all load from
jsDelivr/`extensions.duckdb.org` — cross-origin CDNs this app depends on
working.

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
GitHub Pages' own default of no rewrite rule — gives the real status),
driven with Playwright:

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
- The same four checks, again, under the `/italy-dashboard/` path prefix
  GitHub Pages actually serves from — `tests/browser/test_pages_subpath.py`
  (see "The one thing that DOES change across hosts" above).

**Deployed and live** at the URL above — verified directly, unauthenticated,
across all eight routes on both a 1280×800 desktop and a 390×844 mobile
viewport: every route renders its real heading and real chart marks, zero
console errors, and the only non-2xx responses across the whole walk are
`marts/mart_climate_daily.parquet` and its glob-fallback probe (both under
the `/italy-dashboard/` prefix, as expected). Verified against commit
`75a4356`'s deploy, workflow run
[32663327088](https://github.com/montanarograziano/italy-dashboard/actions/runs/32663327088).

### Initial setup (already done for the URL above; reference for a fork)

1. GitHub → repo **Settings → Pages → Build and deployment → Source**:
   **GitHub Actions** (not "Deploy from a branch" — that source ignores this
   repo's workflow entirely and tries to serve whatever is on a branch
   verbatim, which is not what this repo publishes).
2. Push (or re-run) `.github/workflows/pages.yml` on `main`; the `deploy` job
   reports the live URL in its own summary (and in `steps.deployment.outputs.
   page_url`, surfaced as this workflow's `environment: github-pages` URL in
   the Actions UI).
3. **The build needs real data checked in.** The workflow builds from a
   fresh checkout of `main`, so whatever `data/marts` snapshot is committed
   there is what ships — no fetch-on-deploy step, a push is how you publish
   (`just refresh`/`just sample` + `just transform`, committed, same as any
   other data update).
4. To publish a data update: commit the refreshed snapshot to `main` and
   push; the workflow rebuilds and redeploys automatically.

## Running the Reflex app locally

The Reflex app (compiled React frontend on 3000, a Starlette/FastAPI plus
websocket backend on 8000 by default) is not hosted publicly. It runs two
ways: directly via `uv`/`just` for day-to-day development, or as a single
Docker container that reproduces the same single-port shape a real host
would need — useful for verifying a deploy-shaped build without actually
deploying it anywhere.

### Day-to-day: `just run`

```
just setup     # uv sync: creates .venv, installs everything
just sample    # instant synthetic data (fake numbers, clearly labeled)
just run       # -> http://localhost:3000
```

`just run` (`uv run reflex run`) starts frontend and backend as one
integrated dev process with hot reload — this is what
[Getting started](01-getting-started.md) walks through in full, including
`just fetch-and-run` for real data.

### The single-port Docker shape

For anything closer to a real deploy — one container, one port, no dev
tooling — the Dockerfile bakes the frontend and backend into a single image
served through [Caddy](https://caddyserver.com):

```
just docker-build   # docker build -t italy-dashboard .
just docker-serve   # build, then: docker run --rm -p 10000:10000 italy-dashboard
```

`just docker-serve` depends on `docker-build`, so one command does both; it
serves `http://localhost:10000` once Caddy and the backend are both up.
`PORT` defaults to `10000` (`ENV PORT=10000` in the Dockerfile) but is fully
configurable — the Caddyfile listens on `:{$PORT}`, so `docker run -p
8080:8080 -e PORT=8080 italy-dashboard` works identically on a different
port.

Caddy runs inside the container and is the only thing the exposed port talks
to. It serves the frontend, pre-exported to static files at image-build
time, and reverse-proxies the few routes that belong to the Reflex backend:

| Route | Owner |
| --- | --- |
| `/_event/*` | Backend: the Socket.IO/websocket endpoint (state sync) |
| `/ping` | Backend: liveness probe |
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
container down with it instead of leaving Caddy serving a static shell over
a dead backend.

### `API_URL`: a build-time concern, not a runtime one

The frontend's websocket/API base URL is baked into the exported static JS
bundle when `reflex export` runs (Reflex writes it to `.web/env.json`, which
Vite inlines into the built chunks): setting an env var on the *running*
container has no effect on an already-exported bundle. The Dockerfile
exposes it as a **build arg**, `API_URL`, defaulting to
`http://localhost:10000`.

That default works for a plain local run, for a reason worth understanding
rather than taking on faith: Reflex's own frontend runtime
(`utils/state.js::getBackendURL`) treats the hostnames `localhost`, `0.0.0.0`
and a couple of IPv6 equivalents as "same origin as the page" and rewrites
them to the page's real hostname at connection time. It stays completely
literal under plain http (this project's local single-port container), which
is why the baked port must match Caddy's `$PORT`, verified by actually
running the container and confirming the websocket connects (see
Verification below). Override `API_URL` only if you change the port or put
something else in front (a reverse proxy, TLS termination, a different
domain):

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
silently shipping an empty dashboard. **A rebuild is how you update the
image**: there is no scheduled refresh or fetch-on-run step; rerunning
without rebuilding just reruns the same snapshot.

### What else the image has to carry

Data is not the only thing read at runtime rather than imported. The query
layer resolves `shared/queries/<name>.sql` from disk on every call (the same
files the static frontend imports, see
[Architecture](02-architecture.md)) and `dbt/seeds/province_capitals.csv` for
the coverage denominators. A file like that is invisible to the entire test
suite when it is missing from the image: the code imports fine and the
container still raises `FileNotFoundError` on the first query. It happened
once — `shared/` was extracted out of `queries.py` and the Dockerfile was not
updated, which would have left three pages stuck on the loading placeholder.

`tests/unit/test_deployment_paths.py` now derives the required set from the
code's own `Path` constants and fails if any of them stops being copied (or
gets excluded by `.dockerignore`), so the next extraction is caught by the
suite rather than by a broken image. **If you add a runtime-read file
outside `italy_dashboard/`, add a `COPY` for it** — the test will tell you.

### Climate coverage in a built image is whatever the backfill has reached

The temperature backfill (see [Datasets](04-datasets.md#weather_daily-temperature-non-istat))
progresses over days to weeks, not in one run. The Climate and Climate × Crime
pages surface their current coverage themselves via a coverage line rather
than silently presenting a partial snapshot as complete — that's a data
property, not a deployment one, but it means a given image can legitimately
be a partial snapshot, and the fix is the same rebuild cycle above, once the
backfill has progressed further.

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

## Why hosting was dropped

A static Pages frontend is a better public demo than a free-tier server that
cold-starts on the first request after idle and can drop its websocket
mid-session (both real caveats of the old Render deployment; see the git
history of this file if you need the specifics). Netlify hosted the exact
same static output GitHub Pages does now, so keeping both was pure
duplication with no functional upside. Running the Reflex app as a second
public deployment was never a hard requirement either: it's the reference
implementation of the server-driven shape, valuable to be able to run and
inspect, not something that needs to stay live for anyone else to trust the
numbers — the data, the SQL, and the provenance manifest (`just provenance`)
are already public in this repository.

**The Reflex app cannot run on GitHub Pages at all** — a static host has no
Python runtime and no way to hold a websocket open — so collapsing to one
deployment target necessarily means the Reflex app is local-only now, not a
choice made independently of the Pages migration.

**The one real functional gap this leaves in the public demo:** the Reflex
app has a live EN/IT toggle and `web/` (what GitHub Pages serves) is
English-only. That gap already existed before this cleanup — see "GitHub
Pages" above, "English-only, unlike the Reflex app" — dropping the other two
hosted deployments doesn't create it, but it does mean there is no longer a
public URL where the Italian UI can be seen live; `just run` or `just
docker-serve` are the only ways to see it now.
