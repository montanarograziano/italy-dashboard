"""The static build must ship the datasets it queries and nothing else.

`publicDir` used to point at all of `data/`, which is 843 MB locally and 14 MB
on a fresh clone -- so a local build and a CI build published different things,
and the local one shipped an 800 MB scratch cache. The allowlist is derived
from what the TypeScript actually registers, so it cannot drift from the app.

The two tests above this docstring's original scope compared two
identically-derived string sets and never touched the filesystem or
`vite.config.ts` -- so the actual regression (`publicDir` pointed back at
`data/`, reproducing the 875 MB build) passed all 11 tests here at the time.
The tests below exercise the real behaviour: `stage()` copying real files on
a real filesystem, and `vite.config.ts`'s own `publicDir` literal resolving to
where `stage()` actually writes.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_TS = REPO_ROOT / "web" / "src" / "db.ts"
VITE_CONFIG = REPO_ROOT / "web" / "vite.config.ts"

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


def test_vite_config_public_dir_points_at_the_staging_directory_not_data():
    """The 875 MB -> 4.7 MB fix IS `publicDir` pointing at the staged copy
    instead of `data/` -- reproduced by the final reviewer by pointing it back
    at `../data` and observing the (then-only) tests above stay green. This
    reads the literal directory name out of `vite.config.ts` itself and
    resolves it the same way Vite/Node would, so it fails the moment that
    literal changes, rather than only failing if someone also edits a second,
    unrelated copy of a constant.
    """
    from scripts.stage_web_data import STAGING_DIR

    match = re.search(r'publicDir:\s*resolve\(__dirname,\s*"([^"]+)"\)', VITE_CONFIG.read_text())
    assert match, 'could not find a `publicDir: resolve(__dirname, "...")` line in vite.config.ts'
    configured = (VITE_CONFIG.parent / match.group(1)).resolve()
    assert configured == STAGING_DIR.resolve(), (
        f"vite.config.ts's publicDir resolves to {configured}, not the staging "
        f"directory scripts/stage_web_data.py actually populates ({STAGING_DIR}) -- "
        f"this is exactly the `publicDir` pointed back at `data/` regression."
    )


def test_stage_copies_exactly_the_allowed_parquet_and_nothing_else(tmp_path, monkeypatch):
    """Exercises `stage()`'s real filesystem behaviour, not a second copy of
    the string-set comparison above. Builds a synthetic `data/` containing one
    fake parquet per `STAGED` entry, plus the excluded mart and an unrelated
    scratch file neither `STAGED` nor any app query names, then asserts the
    staged output holds exactly (and only) the allowed set, with real content
    copied rather than merely touched.
    """
    import scripts.stage_web_data as stage_web_data

    fake_data = tmp_path / "data"
    fake_staging = tmp_path / "public-data"

    extra_paths = {"marts/mart_climate_daily", "raw/some_scratch_cache"}
    for rel in sorted(stage_web_data.STAGED | extra_paths):
        dest = fake_data / f"{rel}.parquet"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(f"fake-parquet-bytes:{rel}".encode())

    monkeypatch.setattr(stage_web_data, "DATA_DIR", fake_data)
    monkeypatch.setattr(stage_web_data, "STAGING_DIR", fake_staging)
    missing = stage_web_data.stage()

    assert missing == [], f"nothing should be missing from this synthetic data dir: {missing}"

    produced = {
        str(p.relative_to(fake_staging).with_suffix("")).replace("\\", "/")
        for p in fake_staging.rglob("*.parquet")
    }
    assert produced == stage_web_data.STAGED, (
        f"staged {produced}, expected exactly {stage_web_data.STAGED}"
    )
    for excluded in extra_paths:
        assert not (fake_staging / f"{excluded}.parquet").exists(), (
            f"{excluded} should never be staged, but stage() copied it"
        )

    sample = sorted(stage_web_data.STAGED)[0]
    assert (
        fake_staging / f"{sample}.parquet"
    ).read_bytes() == f"fake-parquet-bytes:{sample}".encode()


def test_restaging_leaves_unchanged_files_in_place(tmp_path, monkeypatch):
    """A second `npm run dev`/`build` re-stages while another Vite server is
    live. Wiping and recopying deleted the parquet mid-request and hung every
    DuckDB-WASM page on that server, so unchanged files must keep their inode,
    changed ones must get the new bytes, and stale ones must go."""
    import scripts.stage_web_data as stage_web_data

    fake_data = tmp_path / "data"
    fake_staging = tmp_path / "public-data"
    for rel in stage_web_data.STAGED:
        src = fake_data / f"{rel}.parquet"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(f"v1:{rel}".encode())
    monkeypatch.setattr(stage_web_data, "DATA_DIR", fake_data)
    monkeypatch.setattr(stage_web_data, "STAGING_DIR", fake_staging)
    stage_web_data.stage()

    unchanged, changed = sorted(stage_web_data.STAGED)[:2]
    inode_before = (fake_staging / f"{unchanged}.parquet").stat().st_ino
    (fake_data / f"{changed}.parquet").write_bytes(b"v2")
    stale = fake_staging / "marts" / "mart_removed_upstream.parquet"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_bytes(b"old")

    stage_web_data.stage()

    assert (fake_staging / f"{unchanged}.parquet").stat().st_ino == inode_before
    assert (fake_staging / f"{changed}.parquet").read_bytes() == b"v2"
    assert not stale.exists()
    assert not list(fake_staging.rglob(".*.tmp"))
