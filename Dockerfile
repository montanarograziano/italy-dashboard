FROM python:3.11-slim

# uv (package manager) — copied from the official distroless image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

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
RUN uv sync --frozen --no-dev

# Data snapshots are mounted at runtime (-v ./data:/app/data);
# bake sample data as a fallback so the container starts non-empty.
RUN mkdir -p data/marts && uv run python -m ingestion.fetch sample \
    && uv run dbt build --project-dir dbt --profiles-dir dbt

# Pre-build the frontend at image build time
RUN uv run reflex export --frontend-only --no-zip

EXPOSE 3000 8000

CMD ["uv", "run", "reflex", "run", "--env", "prod", "--backend-host", "0.0.0.0"]
