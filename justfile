# Italy Dashboard — task runner
# Install just: https://github.com/casey/just  (brew install just)
# All recipes run through uv, so no manual venv activation is needed.

# List available recipes
default:
    @just --list --unsorted

# Install/sync all dependencies (incl. dev tools)
setup:
    uv sync --all-groups --all-extras

# Run the dashboard locally (http://localhost:3000)
run:
    uv run reflex run

# Generate synthetic sample data (fake numbers, dev only), then build marts
sample:
    uv run python -m ingestion.fetch sample
    just transform

# Fetch/refresh real ISTAT data, then rebuild dbt marts. A failure on one
# dataset doesn't stop the others (see ingestion/fetch.py:cmd_refresh -- one
# bad dataset must not sink the rest) and transform still runs afterwards so
# the snapshot rebuilds from whatever DID land -- but the recipe itself must
# still fail loudly if refresh OR transform failed, so CI/cron callers see a
# nonzero exit instead of a silently incomplete snapshot.
refresh *dataset:
    #!/usr/bin/env bash
    set -uo pipefail
    status=0
    uv run python -m ingestion.fetch refresh {{dataset}} || status=$?
    just transform || status=$?
    exit "$status"

alias fetch := refresh

# Fetch fresh ISTAT data, then start the dashboard
fetch-and-run: refresh run

# Search ISTAT dataflows by keyword, e.g. `just discover "delitti"`
discover keyword:
    uv run python -m ingestion.fetch discover "{{keyword}}"

# Show a dataflow's dimension order, for narrowing `key` in registry.yaml
dims dataset:
    uv run python -m ingestion.fetch dims "{{dataset}}"

# Rebuild the province-capitals seed (geocodes once; REVIEW the CSV before committing)
build-capitals:
    uv run python -m ingestion.capitals

# Fetch ERA5-Land daily temperatures for every province capital, then rebuild marts
# `just refresh-weather ITC45` refetches one city (after a coordinate fix)
refresh-weather *province:
    uv run python -m ingestion.weather refresh {{province}}
    just transform

# Bulk ERA5-Land backfill from Copernicus CDS, then rebuild marts. Requires the
# `cds` extra (`uv sync --extra cds`) and a CDS account with the ERA5-Land
# licence accepted (credentials in ~/.cdsapirc). `just refresh-weather-cds 1950 1979`
# backfills one year range; with no args it covers 1950 up to the last fully
# published month (ERA5-Land lags reality, see docs/04-datasets.md).
refresh-weather-cds *years:
    uv run python -m ingestion.cds refresh {{years}}
    just transform

# Re-normalize existing raw CSVs (no download), e.g. after a mapping fix
normalize *dataset:
    uv run python -m ingestion.fetch normalize {{dataset}}

# Rebuild the weather snapshot from cached decade chunks alone (no download),
# so a quota-limited backfill is usable before all 106 capitals finish
normalize-weather:
    uv run python -m ingestion.weather normalize
    just transform

# Serve the project documentation locally (zensical, hot reload)
docs:
    uv run zensical serve

# Build the static documentation site into site/
docs-build:
    uv run zensical build

# Open the marimo data playground (catalog + SQL + charts on the snapshot)
notebook:
    uv run marimo edit notebooks/explore.py

# Run the dbt models: raw CSVs -> staging -> marts (data/marts/*.parquet)
transform:
    mkdir -p data/marts
    uv run dbt build --project-dir dbt --profiles-dir dbt

# Generate and open the dbt documentation (model lineage, columns, tests)
dbt-docs:
    uv run dbt docs generate --project-dir dbt --profiles-dir dbt
    uv run dbt docs serve --project-dir dbt --profiles-dir dbt --port 8080

# dbt with any args, e.g. `just dbt docs generate`
dbt *args:
    uv run dbt {{args}} --project-dir dbt --profiles-dir dbt

# Run linter (no changes)
lint:
    uv run ruff check .
    uv run ruff format --check .

# Auto-fix lint issues and format the codebase
fix:
    uv run ruff check --fix .
    uv run ruff format .

# Type-check with pyrefly
typecheck:
    uv run pyrefly check

# Run the test suite (offline; excludes live API tests)
test *args:
    uv run pytest {{args}}

# Run only unit tests / only integration tests
test-unit:
    uv run pytest tests/unit

test-integration:
    uv run pytest tests/integration -m integration

# Run the live ISTAT API tests (requires network to esploradati.istat.it)
test-live:
    uv run pytest -m live

# Run the browser rendering tests (needs `uv sync --extra browser` and
# `uv run playwright install chromium`; boots a real prod-mode app instance)
test-browser:
    uv run pytest tests/browser -m browser

# Verify the committed data/ snapshot: every mart present, nonempty, hashed,
# and attributed to a source/provider/license -- see the script's own
# docstring for what this deliberately does NOT duplicate (dbt's grain tests)
provenance:
    uv run python scripts/generate_provenance_manifest.py

# Lint + typecheck + tests: what CI's `python` job runs (.github/workflows/ci.yml)
check: lint typecheck test

# Fast compile check of the Reflex frontend (catches framework breakage)
compile:
    uv run reflex export --frontend-only --no-zip

# Build the Docker image. Bakes in the data/ snapshot that exists on THIS
# checkout at build time (see Dockerfile): run `just refresh`/`just sample`
# first if data/marts is empty; the build fails loudly rather than shipping
# an empty dashboard.
docker-build:
    docker build -t italy-dashboard .

# Build and run the production image locally on a single port: the same
# shape as the Render deploy (Caddy + backend behind one $PORT, static
# frontend baked in, no host data mount, no dev/hot-reload). Serves
# http://localhost:10000 once Caddy and the backend are both up.
docker-serve: docker-build
    docker run --rm -p 10000:10000 italy-dashboard

# Regenerate the shared artifacts the static frontend consumes (palette, conformance)
generate-shared:
    uv run python scripts/generate_palette.py
    uv run python scripts/generate_conformance_expected.py

# Serve the static frontend locally (the GitHub Pages deploy target) with Vite's
# dev server and hot reload. `predev` stages data/ into web/public automatically.
# Opens on http://localhost:5173 — hash-routed, e.g. /#/climate.
serve-web:
    cd web && npm run dev

# Serve a production-mode build of the static frontend: `vite build` (via `npm run
# build`, whose `prebuild` also stages data/) then `vite preview` -- the closest
# local stand-in for the exact artifacts GitHub Pages serves. http://localhost:4173
# by default.
preview-web:
    cd web && npm run build
    cd web && npm run preview

# Type-check the static frontend (Vite/esbuild strips types without checking them)
typecheck-web:
    cd web && npm run typecheck

# Run the Python-versus-TypeScript conformance suite (needs `cd web && npm install`).
# Includes `typecheck-web` as one of its tests, so a type error fails here too.
test-conformance:
    uv run pytest tests/browser/test_conformance.py -m browser -v

# Remove caches and build artifacts (keeps data/ and .venv)
clean:
    rm -rf .web .states .pytest_cache .ruff_cache
    find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} +

