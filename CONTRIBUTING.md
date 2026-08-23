# Contributing

Italy Dashboard is a small, solo-maintained project. Contributions are
welcome, but keep the scope in mind: it is a **read-only** statistics viewer
over a handful of Italian public data sources, built around one pipeline
(registry → normalized Parquet → dbt → marts) and two frontends (Reflex,
static DuckDB-WASM). Most useful contributions are one of:

- a new/fixed ISTAT, INPS, or USTAT dataflow ID in `ingestion/registry.yaml`
- a new registry-driven dataset or dbt mart, following the existing pattern
- a bug fix with a regression test (see `docs/07-methodology.md` for the kind
  of ISTAT data traps this project already guards against)
- documentation corrections

## Before you start

Read [`docs/09-development.md`](docs/09-development.md) and
[`docs/02-architecture.md`](docs/02-architecture.md) first — they cover the
tooling, the module boundaries, and the conventions (chart palette, i18n,
query layer) that a PR is expected to follow. For anything bigger than a
small fix, open an issue first to agree on the approach before writing code.

## Setup

```bash
just setup     # uv sync
just sample    # synthetic data, no network needed
just run       # → http://localhost:3000
```

See [`docs/01-getting-started.md`](docs/01-getting-started.md) for the full
walkthrough, including real-data ingestion.

## Before opening a PR

```bash
just check       # lint + typecheck + tests -- what CI runs
just provenance  # if you touched data/ or ingestion/registry.yaml
just compile      # if you touched the Reflex app
```

If you touched `web/`: `cd web && npm run typecheck && npm run build`, and
run `just test-conformance` if you changed a query that exists in both
`italy_dashboard/queries.py` and `web/src/queries/`.

CI (`.github/workflows/ci.yml`) runs the same checks, plus a Playwright suite,
on every PR — including from forks, with no secrets required, since the whole
suite runs offline against the committed `data/` snapshot.

## Data changes

Never commit a real-data refresh and a sample-data change in the same PR —
`just sample` produces obviously-fake numbers and must not be mistaken for a
real snapshot. If you refresh real data, run `just provenance` and mention in
the PR which datasets changed and why.

## Licensing

Code contributions are accepted under the project's [MIT license](LICENSE).
Data is **not** covered by that license — each source keeps its own terms;
see the "Data & licensing" section of [`README.md`](README.md) and
[`docs/04-datasets.md`](docs/04-datasets.md#licensing) before adding or
redistributing a dataset.

## Code of conduct

Be respectful, assume good faith, keep discussion technical. There is no
separate `CODE_OF_CONDUCT.md`; report anything that doesn't fit that bar by
opening an issue or contacting the maintainer directly.
