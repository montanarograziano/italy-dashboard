# Data playground (marimo)

```bash
just notebook    # opens notebooks/explore.py in marimo
```

The notebook attaches an in-memory DuckDB to every snapshot and mart, exactly
like the dashboard does, and gives you:

- **Catalog** — every table with row counts and columns.
- **Schema browser** — pick a table, see types and a 5-row preview.
- **SQL playground** — a SQL editor with a run button; errors render inline.
- **Quick chart** — X / Y / color / mark-type dropdowns over the last query
  result (Altair), for one-off visualizations without touching the app.
- **Example queries** — per-capita rates by citizenship, top crimes by foreign
  share, minors vs adults, and a within-region income↔rate panel correlation.

Use it for anything the dashboard doesn't pre-build: one-off cross-tabs, sanity
checks after a refresh (is the national population ~59M?), or prototyping a
query before turning it into a dbt mart. The notebook reads the same files as
the app, so what you verify here is what the dashboard shows.
