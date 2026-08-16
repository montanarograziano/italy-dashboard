# Troubleshooting

**"No data snapshot found" banner** — run `just sample` (or `just refresh`),
reload the page.

**"Data mart not built yet" on the Crime page** — `just transform` (runs
automatically at the end of `refresh` and `sample`).

**`Not found (404) — check the dataflow ID`** — the ID in `registry.yaml` is
wrong or ISTAT renamed it; re-run `just discover "keyword"`.

**`Expected CSV ... but got XML/HTML`** — the dataflow/key combination returned
no data or doesn't support CSV; broaden the key or re-check the ID.

**A dataset wrote 0 rows** — the warning names the cause: either the `filters`
codes don't exist in this flow (the log prints every real column) or the
`columns` candidates missed. Fix the registry, then `just normalize <dataset>` —
no re-download needed.

**Repeated `Attempt N/3 failed ... ()` with empty errors** — ISTAT drops
connections on oversized extractions. Narrow the `key`
(see [Data pipeline](03-data-pipeline.md#writing-a-narrow-key)); if the flow is
already narrow, it's throttling — retry later.

**A download seems stuck** — it isn't silent anymore: progress logs every 10 MB,
a 2-minute silent gap triggers a retry, and `timeout_s` abandons the dataset with
a message. If you see none of those, the run genuinely finished.

**Charts show fewer years than the data has** — check the split: some dimensions
exist only in recent years (age from 2022). If a plain "All" trend is short,
that's a slice-picker regression — see the tests in `tests/unit/test_queries.py`.

**`discover` finds nothing for an Italian word** — it searches both languages;
if there are still no hits, the dataset may live outside the SDMX API (e.g. only
on dati.istat.it or Serie Storiche).

**Docker shows suspiciously smooth charts**: you built the image after running
`just sample` instead of `just refresh`. The Docker image bakes in whatever
`data/marts` and `data/*.parquet` contained on the checkout at build time (see
[Deployment](12-deployment.md)), so a synthetic-data build looks smooth on
purpose. Rebuild after `just refresh` for real data.

**Docker build fails with "data/marts has no parquet files"**: expected, the
image no longer generates sample data as a fallback. Run `just sample` (dev
data) or `just refresh` (real data) so `data/marts/*.parquet` exists, then
retry the build.

**Numbers changed after a refresh** — ISTAT revises history; the pipeline is
idempotent for identical inputs, but inputs legitimately change upstream.
