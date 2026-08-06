# Getting started

## Prerequisites

- [uv](https://docs.astral.sh/uv/) — `brew install uv` (manages Python and all dependencies)
- [just](https://github.com/casey/just) — `brew install just` (task runner)

Node is **not** required: Reflex downloads its own frontend toolchain on first run.
Network access to `esploradati.istat.it` is needed only when refreshing data.

## Three commands

```bash
just setup     # uv sync: creates .venv, installs everything incl. dev tools
just sample    # synthetic data + dbt marts — the app works immediately
just run       # → http://localhost:3000
```

`just sample` generates clearly-fake numbers so you can explore the UI before any
real download. The first `just run` takes a couple of minutes while Reflex sets up
its toolchain; later starts are fast.

## Real ISTAT data

```bash
just refresh   # fetch every dataset, re-normalize, rebuild all dbt marts
```

Datasets download sequentially (fastest first) with streamed progress logs, and the
snapshot updates **incrementally** — the dashboard is usable as soon as the first
dataset lands. A per-dataset timeout prevents any single extraction from hanging
the run, and every write is atomic: interrupting with Ctrl+C never corrupts files.

Single dataset: `just refresh crime_offenders`. Full command reference in
[Development](09-development.md); per-dataset details in [Datasets](04-datasets.md).

## Language

Click **EN · IT** in the navbar to switch the interface language; the choice
persists in the browser. Data labels (crime types, region names) come from ISTAT
as fetched, currently in English — see [Dashboard](06-dashboard.md#language).

## Deployment (internal)

```bash
just docker-run    # builds the image, then serves on :3000/:8000
```

Mount `data/` from the host (`-v $(pwd)/data:/app/data`, already in the recipe) so
snapshots survive restarts; refresh from the host on a schedule if desired.

!!! warning
    The dashboard has no authentication. Keep it on an internal network or behind
    a reverse proxy with auth.
