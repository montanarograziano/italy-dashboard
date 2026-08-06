# Development

Tooling: **uv** (packaging + venv), **just** (tasks), **ruff** (lint + format),
**pyrefly** (types), **pytest** (57 tests, all offline). Reflex is pinned
(`reflex==0.9.8`) because it releases breaking changes quickly.

## Command reference

| Command | Purpose |
|---|---|
| `just setup` | Install/sync all dependencies |
| `just run` | Run the dashboard locally |
| `just sample` | Synthetic data + marts (offline dev) |
| `just refresh [ds]` / `just fetch` | Download from ISTAT, normalize, rebuild marts |
| `just normalize [ds]` | Re-normalize existing raw CSVs (no download) |
| `just transform` | dbt build only |
| `just discover "kw"` / `just dims <ds>` | Find dataflow IDs / dimension order |
| `just notebook` | marimo playground |
| `just check` | **Lint + typecheck + tests — what CI should run** |
| `just lint` / `just fix` / `just typecheck` | Individual quality gates |
| `just test` / `test-unit` / `test-integration` / `test-live` | Test slices (`live` hits the real API, opt-in) |
| `just compile` | Fast Reflex frontend compile check |
| `just docs` | Serve this documentation locally |
| `just docker-build` / `docker-run` | Container image (run builds first) |
| `just clean` | Remove caches and build artifacts |

## Test layout

```
tests/
├── unit/          # SDMX client (httpx2.MockTransport), registry, normalize,
│                  # sample data, query layer incl. slice-picker regressions
└── integration/   # full pipeline (mocked API → parquet → queries),
                   # real dbt builds in temp dirs (incl. double-build idempotency),
                   # Reflex page construction
```

Everything runs without network; the ISTAT API is mocked at the transport level.
Live tests exist (`just test-live`) but are deselected by default.

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
