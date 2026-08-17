# Shared SQL

Every file here is read by BOTH frontends: the Reflex app through
`italy_dashboard.queries.load_sql()`, and the static app through Vite's `?raw`
import. A change here changes both.

## Rules

1. **Positional `?` parameters only.** DuckDB's Python client and its WASM build
   both accept `?`. Named parameters work on one side and fail on the other.
2. **Every file carries a header comment** naming its parameters in order and
   stating what it returns. Positional parameters are unreadable otherwise.
3. **No orphans.** A test asserts every file is referenced from the Python side,
   and that every file is either imported by the TypeScript side or listed in
   `NOT_YET_CONSUMED_BY_TS` (`tests/unit/test_shared_sql.py`). That list may
   only shrink: porting a query fails the test until its entry is removed. If a
   query falls out of use, delete the file rather than leaving it to rot.
4. **Only genuinely static SQL lives here.** Queries that build their SQL at
   runtime stay in code, and are kept honest by the conformance suite instead.
