FROM python:3.11-slim

# uv (package manager) — copied from the official distroless image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/
# Caddy (single-port reverse proxy / static file server, see Caddyfile).
#
# The upstream binary carries the file capability cap_net_bind_service=ep so it
# can bind port 80 as an unprivileged user. That xattr survives COPY --from, and
# execve() returns EPERM when a file's capabilities are not in the process's
# bounding set. Render runs containers unprivileged with that capability
# dropped, so the copied binary failed to start there with exit 126 while
# working fine under Docker Desktop's more permissive default.
#
# Caddy does not need the capability here: it binds $PORT (10000), not 80.
# Piping through cat rewrites the bytes into a fresh root-owned file and leaves
# the xattrs behind; `cp` and `mv` would preserve them.
COPY --from=caddy:2-alpine /usr/bin/caddy /tmp/caddy-with-caps
RUN cat /tmp/caddy-with-caps > /usr/bin/caddy \
    && chmod 0755 /usr/bin/caddy \
    && chown root:root /usr/bin/caddy \
    && rm -f /tmp/caddy-with-caps

WORKDIR /app

# unzip + curl are needed by Reflex to fetch its bundled frontend toolchain
RUN apt-get update && apt-get install -y --no-install-recommends unzip curl \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first (cached layer as long as the lockfile is unchanged)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Then the application code
COPY ingestion ./ingestion
COPY italy_dashboard ./italy_dashboard
COPY dbt ./dbt
COPY rxconfig.py ./
# Reflex's frontend-side lockfile (pinned bun.lock/package.json versions), so
# the frontend build reuses the pins from `reflex init`/`reflex export` runs
# on this checkout instead of re-resolving latest npm versions on every image
# build. Tracked in git (unlike data/ and .web/), so it's just a normal COPY.
COPY reflex.lock ./reflex.lock
RUN uv sync --frozen --no-dev

# Bake the real data snapshots into the image. `data/` is GITIGNORED, so this
# image can only be built from a checkout that already has one: run
# `just refresh` (+ `just refresh-weather`/`just refresh-weather-cds`) for the
# real ISTAT/Open-Meteo snapshot, or `just sample` for synthetic dev data,
# THEN `docker build`. There is no fallback generation here anymore; a
# checkout without data produces a loud build failure below, not a silently
# empty dashboard.
#
# Only the parquet files the app actually reads (italy_dashboard/queries.py:
# data/*.parquet and data/marts/*.parquet) are copied in. data/raw/ (the raw
# ISTAT CSV / Open-Meteo JSON downloads, hundreds of MB and, mid-backfill,
# still growing) and data/dbt.duckdb (a dev scratch file) are dbt/ingestion
# inputs, not runtime dependencies, so leaving them out keeps the image small
# without changing what the dashboard serves.
COPY data/marts ./data/marts
COPY data/*.parquet ./data/
RUN find data/marts -maxdepth 1 -name '*.parquet' -print -quit | grep -q . || { \
      echo "ERROR: data/marts has no parquet files." >&2; \
      echo "This image bakes in the data snapshot at build time; it does not fetch" >&2; \
      echo "or generate data on its own. Build from a checkout where 'just refresh'" >&2; \
      echo "(real ISTAT/Open-Meteo data) or 'just sample' (synthetic dev data) has" >&2; \
      echo "already been run, so data/marts/*.parquet exists, then retry the build." >&2; \
      exit 1; \
    }

# The frontend's websocket/API base URL is baked into the exported static JS
# at THIS build step (Reflex writes it to .web/env.json, which Vite inlines
# into the bundle): a runtime env var set later has no effect on an already
# exported bundle. Default here is http://localhost:{$PORT}: Reflex's own
# frontend runtime treats "localhost" as "same origin as the page" and, when
# the page is loaded over https (Render terminates TLS in front of Caddy),
# rewrites it to wss://<public-host>/_event with no port, matching Render's
# single-origin topology exactly, no override needed there. It only stays
# literal for plain-http requests (e.g. this project's own local single-port
# test), which is why the default's port must match Caddy's $PORT below
# rather than Reflex's usual 8000. Override with `--build-arg API_URL=...`
# for any other topology (custom domain quirks, a non-TLS proxy, etc).
ARG API_URL=http://localhost:10000
ENV REFLEX_API_URL=${API_URL}

# Export the frontend to static files at build time, then discard the rest of
# .web (node_modules, the Vite/React-Router toolchain, etc.): none of it is
# needed to serve the exported bundle or to run the backend in --backend-only
# mode (which explicitly skips recompiling the frontend).
# --no-sync: the venv was already synced --frozen --no-dev above; without it,
# `uv run` re-syncs the DEFAULT dependency group (dev: pytest, ruff, pyrefly,
# marimo, pyarrow, zensical, ~120MB) back into the image on every `uv run`.
RUN uv run --no-sync reflex export --frontend-only --env prod --no-zip \
    && mkdir -p /srv/frontend \
    && cp -r .web/build/client/. /srv/frontend/ \
    && rm -rf .web

COPY Caddyfile ./Caddyfile
COPY scripts/start.sh ./scripts/start.sh
RUN chmod +x ./scripts/start.sh

# Render sets $PORT (conventionally 10000); default kept for local runs. Must
# match the port baked into API_URL above for the plain-http/local case.
ENV PORT=10000
EXPOSE 10000

CMD ["./scripts/start.sh"]
