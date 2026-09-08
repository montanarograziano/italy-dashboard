# Development

Tooling: **uv** (packaging + venv), **just** (tasks), **ruff** (lint + format),
**pyrefly** (types), **pytest** (450+ tests, all offline). Reflex is pinned
(`reflex==0.9.8`) because it releases breaking changes quickly.

## Command reference

| Command | Purpose |
| --- | --- |
| `just setup` | Install/sync all dependencies |
| `just run` | Run the dashboard locally |
| `just sample` | Synthetic data + marts (offline dev) |
| `just refresh [ds]` / `just fetch` | Download from ISTAT, normalize, rebuild marts |
| `just normalize [ds]` | Re-normalize existing raw CSVs (no download) |
| `just transform` | dbt build only |
| `just discover "kw"` / `just dims <ds>` | Find dataflow IDs / dimension order |
| `just notebook` | marimo playground |
| `just check` | **Lint + typecheck + tests — what CI runs** |
| `just lint` / `just fix` / `just typecheck` | Individual quality gates |
| `just test` / `test-unit` / `test-integration` / `test-live` | Test slices (`live` hits the real API, opt-in) |
| `just test-browser` / `test-conformance` | Browser-rendering + Python↔TypeScript conformance suite (needs the `browser` extra) |
| `just provenance` | Verify + describe the committed `data/` snapshot (row counts, hashes, source/license) — see below |
| `just compile` | Fast Reflex frontend compile check |
| `just docs` | Serve this documentation locally |
| `just docker-build` / `docker-serve` | Container image / build and run it locally |
| `just clean` | Remove caches and build artifacts |

## CI

`.github/workflows/ci.yml` runs on every push to `main` and every pull request
(including from forks — no secrets are used, everything runs offline against
the committed snapshot). Three jobs: `python` (`just check` +
`just provenance`), `web` (`npm run typecheck` + `npm run build`), and
`browser` (`just test-browser`, gated on the first two passing since it's the
most expensive job). It never runs a live fetch — `just refresh`/
`just refresh-weather*` stay manual/cron, per docs/04-datasets.md.

## Published-data provenance

`just provenance` (`scripts/generate_provenance_manifest.py`) checks every
`git`-tracked file under `data/` — the exact snapshot a fresh clone ships —
and fails if one is missing or empty. It prints a JSON manifest with each
file's row count, SHA-256, covered period, and source/provider/license
(derived from `ingestion/registry.yaml` and the dbt `ref()`/`source()` graph,
see the script's `MART_LINEAGE`). It does **not** re-run dbt's own
not_null/unique-grain tests (`just transform` already does that).

It also reports whether the snapshot is synthetic or real, read from
`data/.provenance.json` — written by `ingestion.fetch sample`/`refresh`, so a
snapshot from before that marker existed (including the one currently
committed to this repo) honestly reports `"unknown"` rather than guessing.
Run `just sample` or `just refresh` to get an authoritative status.

## Test layout

```
tests/
├── unit/          # per-provider clients (httpx2.MockTransport), registry, normalize,
│                  # sample data, query layer incl. slice-picker regressions
├── integration/   # full pipeline (mocked APIs → parquet → dbt → queries),
│                  # real dbt builds in temp dirs (incl. double-build idempotency),
│                  # Reflex page construction
└── browser/       # Playwright: chart rendering, static-app conformance
                   # (needs the `browser` extra; deselected by default)
```

Everything except `tests/browser/` runs without network or a browser; every
provider is mocked at the transport level. Live tests exist (`just test-live`)
but are deselected by default, same as `tests/browser/` (`just test-browser`).

## Conventions worth knowing

- **Type checking**: pyrefly runs clean; two documented suppressions exist for
  Reflex-framework idioms (state class attributes, `Field` descriptor).
- **Charts**: colors come from `theme.py` slots in fixed order — never add
  ad-hoc colors; keep multi-series charts within the first three slots.
- **Translations**: every user-visible string goes through `t("key")` with
  entries in both dictionaries in `translations.py`.
- **New queries**: add to `queries.py`, return plain dicts, and let missing
  views degrade to empty lists — the UI treats empty as "not fetched yet".
- **Documentation**: this site is built with [Zensical](https://zensical.org)
  from `docs/`; pages are ordered by filename prefix.
