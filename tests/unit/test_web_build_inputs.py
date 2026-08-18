"""The static build must ship the datasets it queries and nothing else.

`publicDir` used to point at all of `data/`, which is 843 MB locally and 14 MB
on a fresh clone -- so a local build and a CI build published different things,
and the local one shipped an 800 MB scratch cache. The allowlist is derived
from what the TypeScript actually registers, so it cannot drift from the app.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_TS = REPO_ROOT / "web" / "src" / "db.ts"

# 10 MB of the 14 MB tracked, for one chart. The spec excludes it from the
# static deploy and precomputes that chart's data at build time instead.
EXCLUDED_FROM_STATIC_BUILD = {"marts/mart_climate_daily"}


def _registered_paths() -> set[str]:
    body = re.search(r"const PARQUET = \[(.*?)\]", DB_TS.read_text(), re.S)
    assert body, "could not find the PARQUET list in db.ts"
    return set(re.findall(r'"([^"]+)"', body.group(1)))


def test_the_staged_data_matches_what_the_app_registers():
    from scripts.stage_web_data import STAGED

    assert _registered_paths() - EXCLUDED_FROM_STATIC_BUILD == STAGED


def test_no_scratch_data_is_staged():
    from scripts.stage_web_data import STAGED

    forbidden = [
        p for p in STAGED if "raw" in p or p.endswith("dbt.duckdb") or "weather_daily" in p
    ]
    assert not forbidden, forbidden
