"""Verify and describe the published data/ snapshot: a release-safety check.

This is NOT a data-quality tool: `dbt build` (`just transform`) already runs
per-mart `not_null`/`unique`-grain tests, and this script does not repeat
those. What it checks instead is the thing dbt never sees, because dbt only
ever looks at whatever happens to be on disk right now: is the snapshot a
public repo would actually SHIP (i.e. `git`-tracked under `data/`) present,
non-empty, and does anyone downstream know where each file came from and
under what license?

Deterministic from a fresh clone: every file this reads is `git ls-files`d,
so it needs no network call and no live fetch (`just refresh`/
`just refresh-weather` can each take from minutes to several days, see
docs/04-datasets.md, and are deliberately never invoked here).

Run with `just provenance` (prints and exits nonzero on a real problem) or
import `build_manifest()` for the JSON payload.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import duckdb  # type: ignore[import-not-found]
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
REGISTRY_PATH = REPO_ROOT / "ingestion" / "registry.yaml"
PROVENANCE_MARKER = DATA_DIR / ".provenance.json"

# Which registry dataset(s) (ingestion/registry.yaml keys) feed each mart,
# read off the dbt `ref()`/`source()` graph (dbt/models/staging/sources.yml,
# dbt/models/marts/*.sql) rather than guessed from names -- e.g. mart_crime
# sources the RAW csv directly (stg_crime), not the normalized snapshot.
# "weather" is a sentinel: ingestion/weather.py's Open-Meteo fetch has no
# registry entry (it is not an SDMX/hub dataset), see WEATHER_SOURCE below.
MART_LINEAGE: dict[str, list[str]] = {
    "mart_crime": ["crime_reported"],
    "mart_offenders": ["crime_offenders"],
    "mart_offender_rates": ["crime_offenders", "population_resident", "population_foreign"],
    "mart_crime_income": [
        "crime_offenders",
        "population_resident",
        "population_foreign",
        "income_regional",
    ],
    "mart_population": ["population_resident", "population_foreign"],
    "mart_dsu": ["education_university_scholarships"],
    "mart_naspi": ["labor_naspi_beneficiaries"],
    "mart_climate_daily": ["weather"],
    "mart_climate_monthly": ["weather"],
    "mart_climate_annual": ["weather"],
    "mart_climate_region": ["weather"],
    "mart_crime_climate": ["crime_offenders", "weather"],
}

# Grounded in docs/04-datasets.md's "weather_daily" section: Open-Meteo is the
# day-to-day source, the Copernicus/CDS bulk backfill (ingestion/cds.py) is an
# alternative fetcher for the SAME snapshot. Neither license is ISTAT's.
WEATHER_SOURCE = {
    "provider": "open-meteo",
    "dataflow_id": None,
    "title": "Daily 2m temperature, ERA5-Land reanalysis (Open-Meteo Historical Weather API)",
    "license": (
        "Open-Meteo Historical Weather API (ERA5-Land derived): free, no API key, "
        "NON-COMMERCIAL USE ONLY -- see docs/04-datasets.md#weather_daily-temperature-non-istat. "
        "If this snapshot was instead populated via the Copernicus/CDS bulk backfill "
        "(ingestion/cds.py), the Copernicus/CDS ERA5-Land licence applies (accepted "
        "per-user via a CDS account, see docs/04-datasets.md)."
    ),
}

# Per-provider license notes. None of these are asserted as a specific SPDX
# license: the registry and docs record WHERE each provider's data comes from
# but never its redistribution terms, so a firm claim here would be fabricated.
# Flagged explicitly rather than left blank -- see the org's own "state
# uncertainty, never fabricate" rule -- so a public-release review has an
# actionable TODO instead of a silent gap.
PROVIDER_LICENSES = {
    "istat": (
        "ISTAT SDMX REST API (esploradati.istat.it): free, keyless (docs/04-datasets.md). "
        "License terms: TODO -- verify ISTAT's official open-data license "
        "(commonly CC BY 3.0 IT for Italian public-sector statistics) before external use."
    ),
    "inps": (
        "INPS data via the StatKit hub middleware (ingestion/inps_client.py), not "
        "SDMX-REST. License terms: TODO -- not documented in this repo; verify with "
        "INPS/StatKit before external use."
    ),
    "ustat": (
        "USTAT/MUR open-data portal (CKAN), see ingestion/ustat_client.py. "
        "License terms: TODO -- not documented in this repo; verify with USTAT/MUR "
        "before external use."
    ),
}


def _tracked_parquet() -> list[Path]:
    """The committed data/ snapshot, from `git ls-files` -- not a glob.

    Mirrors scripts/generate_conformance_expected.py's `_tracked_parquet`: a
    glob would also pick up a developer's untracked scratch files (raw CSVs,
    `dbt.duckdb`, an uncommitted weather backfill), which a fresh clone never
    has, making the manifest depend on whatever happens to sit on one machine.
    """
    try:
        listing = subprocess.run(
            ["git", "ls-files", "-z", "--", "data"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:  # pragma: no cover
        raise RuntimeError(
            "cannot list the committed data/ snapshot: this needs `git` and a checkout "
            "of the repository, because the manifest describes what a CLONE ships"
        ) from exc
    paths = sorted(REPO_ROOT / name for name in listing.split("\0") if name.endswith(".parquet"))
    missing = [p for p in paths if not p.is_file()]
    if missing:
        raise FileNotFoundError(f"committed parquet missing from the working tree: {missing}")
    return paths


def _registry() -> dict[str, dict[str, Any]]:
    return yaml.safe_load(REGISTRY_PATH.read_text())["datasets"]


def _covered_period(con: duckdb.DuckDBPyConnection, path: Path) -> dict[str, Any] | None:
    """Best-effort min/max over whichever time column this file actually has.

    Schemas vary by mart (see dbt/models/marts/*.sql), so this tries the
    columns that occur in practice, in order, rather than assuming one.
    """
    cols = {
        row[0] for row in con.execute(f"describe select * from read_parquet('{path}')").fetchall()
    }
    for column in ("obs_date", "period", "year", "academic_year"):
        if column in cols:
            row = con.execute(
                f"select min({column}), max({column}) from read_parquet('{path}')"
            ).fetchone()
            if row is None:  # pragma: no cover - an aggregate always returns one row
                raise RuntimeError(f"min/max({column}) over {path} returned no row")
            lo, hi = row
            return {"column": column, "min": str(lo), "max": str(hi)}
    return None


def _source_for(registry: dict[str, dict[str, Any]], key: str) -> dict[str, Any]:
    if key == "weather":
        return dict(WEATHER_SOURCE)
    cfg = registry.get(key)
    if cfg is None:  # pragma: no cover - guards MART_LINEAGE/registry drift
        return {"provider": None, "dataflow_id": None, "title": None, "license": None}
    provider = cfg.get("provider", "istat")
    return {
        "provider": provider,
        "dataflow_id": cfg["dataflow_id"],
        "title": cfg["title"],
        "license": PROVIDER_LICENSES.get(provider),
    }


def _snapshot_provenance() -> dict[str, Any]:
    """How the snapshot on disk was produced, per `ingestion.fetch`'s marker.

    Absent on any snapshot generated before the marker existed (including,
    as of this writing, the one committed to this repo) -- reported as
    "unknown" rather than guessed, since guessing from file contents alone
    (e.g. "these numbers look plausible") is exactly the kind of unverified
    claim this manifest exists to replace with a real signal.
    """
    if not PROVENANCE_MARKER.is_file():
        return {
            "mode": "unknown",
            "recorded_at": None,
            "note": (
                "no data/.provenance.json marker on this snapshot -- run `just sample` "
                "or `just refresh` to (re)generate one and get an authoritative status"
            ),
        }
    try:
        marker = json.loads(PROVENANCE_MARKER.read_text())
        return {"mode": marker["mode"], "recorded_at": marker["generated_at"], "note": None}
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        return {
            "mode": "unknown",
            "recorded_at": None,
            "note": f"data/.provenance.json is unreadable/malformed ({exc}) -- regenerate it",
        }


def build_manifest() -> dict[str, Any]:
    registry = _registry()
    con = duckdb.connect()
    entries: list[dict[str, Any]] = []
    warnings: list[str] = []
    try:
        for path in _tracked_parquet():
            rel = path.relative_to(REPO_ROOT).as_posix()
            stem = path.stem
            is_mart = path.parent.name == "marts"
            source_keys = MART_LINEAGE[stem] if is_mart else [stem]
            count_row = con.execute(f"select count(*) from read_parquet('{path}')").fetchone()
            if count_row is None:  # pragma: no cover - an aggregate always returns one row
                raise RuntimeError(f"count(*) over {path} returned no row")
            row_count = count_row[0]
            if row_count == 0:
                warnings.append(f"{rel}: 0 rows -- a shipped mart/snapshot must not be empty")
            entries.append(
                {
                    "path": rel,
                    "kind": "mart" if is_mart else "source",
                    "sources": [_source_for(registry, key) for key in source_keys],
                    "row_count": row_count,
                    "size_bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "covered_period": _covered_period(con, path),
                }
            )
    finally:
        con.close()
    return {
        "_comment": (
            "Generated by scripts/generate_provenance_manifest.py (`just provenance`). "
            "Describes the git-tracked data/ snapshot a fresh clone ships, not whatever "
            "else happens to be on this machine's disk."
        ),
        "snapshot_provenance": _snapshot_provenance(),
        "datasets": entries,
        "warnings": warnings,
    }


def main() -> int:
    manifest = build_manifest()
    print(json.dumps(manifest, indent=2, sort_keys=True))
    if manifest["warnings"]:
        print(f"\n{len(manifest['warnings'])} problem(s):", file=sys.stderr)
        for warning in manifest["warnings"]:
            print(f"  - {warning}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
