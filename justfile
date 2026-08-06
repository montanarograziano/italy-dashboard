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

# Fetch/refresh real ISTAT data, then rebuild dbt marts
refresh *dataset:
    -uv run python -m ingestion.fetch refresh {{dataset}}
    -just transform

alias fetch := refresh

# Fetch fresh ISTAT data, then start the dashboard
fetch-and-run: refresh run

# Search ISTAT dataflows by keyword, e.g. `just discover "delitti"`
discover keyword:
    uv run python -m ingestion.fetch discover "{{keyword}}"

# Show a dataflow's dimension order, for narrowing `key` in registry.yaml
dims dataset:
    uv run python -m ingestion.fetch dims "{{dataset}}"

# Re-normalize existing raw CSVs (no download), e.g. after a mapping fix
normalize *dataset:
    uv run python -m ingestion.fetch normalize {{dataset}}

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

# Lint + typecheck + tests: what CI should run
check: lint typecheck test

# Fast compile check of the Reflex frontend (catches framework breakage)
compile:
    uv run reflex export --frontend-only --no-zip

# Build the Docker image
docker-build:
    docker build -t italy-dashboard .

# Run the Docker image with data/ mounted from the host (builds first if needed)
docker-run: docker-build
    docker run -p 3000:3000 -p 8000:8000 -v $(pwd)/data:/app/data italy-dashboard

# Remove caches and build artifacts (keeps data/ and .venv)
clean:
    rm -rf .web .states .pytest_cache .ruff_cache
    find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} +

