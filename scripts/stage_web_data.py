"""Stage the parquet the static frontend is allowed to ship into a directory
Vite's `publicDir` publishes, deriving the allowlist from `web/src/db.ts`
itself so it cannot silently drift from what the app actually registers.

Why this exists: `web/vite.config.ts`'s `publicDir` used to point straight at
`data/`, which is 14 MB of git-tracked parquet on a fresh clone but ~850 MB on
a working checkout (raw CSVs, `dbt.duckdb`, the weather cache, every mart
including the 10 MB `mart_climate_daily`) -- so a local build and a from-clone
build published wildly different things, and the local one shipped the whole
scratch cache. Staging a small directory with exactly `STAGED` in it, and
pointing `publicDir` there instead, makes both builds identical and small.

`mart_climate_daily` is deliberately excluded: the design spec keeps it off
the static deploy (10 MB for one chart), and `registerParquetViews`
(web/src/db.ts) already tolerates an absent parquet file -- it skips the view
and records the miss rather than failing the whole connection, and the
climate page's distribution card shows an explanatory empty state instead of
erroring (see italy_dashboard's Task 3 report).

No third-party imports on purpose: this only copies files, so it must not
need `uv sync` (or any dependency install) to run. That matters most on
the GitHub Pages build image (`.github/workflows/pages.yml`), which has no
reason to carry `uv` at all when it only needs `python3` -- see
docs/12-deployment.md.

Run directly (`python3 scripts/stage_web_data.py`) or via the `predev`/
`prebuild` npm hooks in `web/package.json`, so both `npm run dev` (and
therefore `just test-conformance`, which drives the dev server) and
`npm run build` publish the same staged directory.
"""

from __future__ import annotations

import argparse
import filecmp
import json
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_snapshot import validate_manifest  # type: ignore[import-not-found]

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
DB_TS = REPO_ROOT / "web" / "src" / "db.ts"

# Where Vite's publicDir points (web/vite.config.ts). Gitignored: this is a
# derived, regeneratable directory, never a source of truth.
STAGING_DIR = REPO_ROOT / "web" / "public-data"

# 10 MB of the 14 MB tracked, for one chart. The spec excludes it from the
# static deploy; Task 3's distribution card explains itself instead of
# erroring when this table is absent.
EXCLUDED_FROM_STATIC_BUILD = {"marts/mart_climate_daily"}


def _registered_paths() -> set[str]:
    """The parquet stems `web/src/db.ts`'s own PARQUET list registers.

    Reading db.ts's source rather than hardcoding a mirror list here is the
    whole point: the two cannot drift, because there is only one list.
    """
    body = re.search(r"const PARQUET = \[(.*?)\]", DB_TS.read_text(), re.S)
    assert body, "could not find the PARQUET list in db.ts"
    return set(re.findall(r'"([^"]+)"', body.group(1)))


STAGED: set[str] = _registered_paths() - EXCLUDED_FROM_STATIC_BUILD


def stage(*, strict: bool = False) -> list[str]:
    """Sync the staging directory; strict mode gates production first.

    Returns missing paths in development mode. Strict mode fails before any
    copy, so production cannot publish a partial static snapshot.

    Syncs in place rather than wiping and recopying: `npm run dev` and
    `npm run build` both re-stage via their pre-hooks, so a second dev server
    or a build started while another Vite server is live would otherwise
    delete the parquet files mid-request (DuckDB-WASM range reads then hang
    and pages never render). Unchanged files are left untouched, changed ones
    are swapped in atomically, and stale ones are removed.
    """
    if strict:
        manifest_path = DATA_DIR / "release-manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            errors = validate_manifest(manifest)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"release gate refused: {exc}") from exc
        if errors:
            raise RuntimeError("release gate refused: " + "; ".join(errors))
    STAGING_DIR.mkdir(parents=True, exist_ok=True)

    missing: list[str] = []
    expected: set[Path] = set()
    for rel in sorted(STAGED):
        src = DATA_DIR / f"{rel}.parquet"
        if not src.exists():
            missing.append(rel)
            continue
        dest = STAGING_DIR / f"{rel}.parquet"
        expected.add(dest)
        if dest.is_file() and filecmp.cmp(src, dest, shallow=False):
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(f".{dest.name}.tmp")
        shutil.copy2(src, tmp)
        os.replace(tmp, dest)

    for path in sorted(STAGING_DIR.rglob("*"), reverse=True):
        if path.is_file() and path not in expected:
            path.unlink()
        elif path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    return missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="require sealed production manifest")
    args = parser.parse_args(argv)
    try:
        missing = stage(strict=args.strict)
    except RuntimeError as exc:
        print(f"stage_web_data: {exc}", file=sys.stderr)
        return 1
    print(
        f"stage_web_data: staged {len(STAGED) - len(missing)}/{len(STAGED)} dataset(s) into {STAGING_DIR}"
    )
    if missing:
        print(f"stage_web_data: not present in this checkout, skipped: {sorted(missing)}")
        if args.strict:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
