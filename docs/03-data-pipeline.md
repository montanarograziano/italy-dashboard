# Data pipeline

Everything is driven by `ingestion/registry.yaml` and executed through the fetch
CLI (`python -m ingestion.fetch`, wrapped by `just`).

## Commands

| Command | What it does |
|---|---|
| `just refresh [dataset]` | Download → normalize → rebuild dbt marts. All datasets or one. |
| `just normalize [dataset]` | Re-run normalization from raw CSVs already on disk — no download. Use after a mapping fix. |
| `just transform` | dbt build only (staging → marts → tests). |
| `just discover "keyword"` | Search ISTAT's catalog (Italian **and** English names) for dataflow IDs. |
| `just dims <dataset-or-flow>` | Print a dataflow's dimension order — required to write a `key`. |
| `just sample` | Synthetic snapshots + marts for offline development. |

## The registry

Each dataset is one YAML entry:

```yaml
crime_offenders:
  domain: crime
  dataflow_id: "73_230_DF_DCCV_AUTVITTPS_7"
  key: "A......."          # dotted SDMX filter, one slot per dimension
  start_period: "1970"      # API returns from whatever actually exists
  timeout_s: 2400           # hard cap; huge extractions fail loudly, not silently
  columns:                  # SDMX component → normalized column (candidates tried in order)
    territory: [REF_AREA, ITTER107]
    category: [TYPE_CRIME, TIPO_REATO]
  filters:                  # keep only rows whose component code matches
    FREQ: A
```

Things the registry machinery handles for you:

- **Candidate dimension names** — ISTAT dataflows disagree (`ITTER107` vs
  `REF_AREA`, `SEXISTAT1` vs `SEX`); each mapping is a list tried in order.
- **Combined labels** — ISTAT's SDMX-CSV (`labels=both`) packs `"CODE: Label"`
  into both headers and cell values; normalization splits them automatically.
- **Row filters** — keep only headline slices (annual frequency, totals for
  breakdowns you don't chart). Unmatched filter components are skipped with a
  warning that prints the real column list.
- **Placeholder IDs** — a `dataflow_id` starting with `TODO` is skipped with a
  hint instead of failing the run.

## Writing a narrow `key`

`key: ALL` downloads an entire dataflow — sometimes 1.5 GB, and ISTAT drops the
connection on the largest ones. The dotted key filters server-side:

1. `just dims <dataset>` → the ordered dimension list.
2. One slot per dimension, joined by `.`; empty slot = all values; `+` for
   multiple codes (`IT+ITC1+ITC2`).
3. Time is filtered by `start_period`, never in the key.

Example — inflation went from 1.5 GB to a few hundred rows with
`key: "M.IT..4.00"` (monthly, Italy, any base series, index number, all items).

## Reliability properties

- **Streaming with progress** — long downloads log every 10 MB; a server that
  goes silent for 2 minutes triggers a retry rather than hanging forever.
- **Sequential, fastest-first** — one dataset at a time; the dashboard picks up
  each dataset the moment it lands.
- **Per-dataset timeout** (`timeout_s`) — a too-big extraction is abandoned with
  an actionable message; the run continues.
- **Atomic writes** — raw CSVs and Parquet snapshots are written to `.tmp` and
  renamed. An interrupted run leaves the previous good file in place, never a
  truncated one.
- **Idempotent end to end** — every step is a full overwrite; re-running any
  command converges to the same state. dbt tests additionally enforce grain
  uniqueness on every mart, so silent duplication cannot survive a build.
- **Row-count reporting** — every normalize logs how many rows survived; zero
  rows produces a loud warning naming the likely cause.
