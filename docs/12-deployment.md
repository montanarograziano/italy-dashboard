# Deployment

The dashboard runs on [Render](https://render.com)'s free tier as a single
Docker container. Render gives one exposed port, terminates TLS itself, and
spins the service down when idle, none of which matches Reflex's default
shape (a compiled React frontend on 3000, a Starlette/FastAPI plus websocket
backend on 8000). This page covers how that gap is closed, what's genuinely
verified to work, and the caveats that come with the free tier.

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
