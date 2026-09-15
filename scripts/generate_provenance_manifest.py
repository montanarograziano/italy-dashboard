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

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
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
        "Data licence: CC BY 4.0 (verified at open-meteo.com/en/licence and, for the "
        "underlying reanalysis, cds.climate.copernicus.eu). That is DIFFERENT from the "
        "free API tier this pipeline uses by default, which is a separate, narrower "
        "promise: non-commercial use only, rate-capped (600/min, 5,000/hour, 10,000/day) "
        "-- see docs/04-datasets.md#weather_daily-temperature-non-istat and "
        "docs/04-datasets.md#licensing. If this snapshot was instead populated via the "
        "Copernicus/CDS bulk backfill (ingestion/cds.py), the same CC BY 4.0 data licence "
        "applies with no non-commercial restriction, once a CDS account has accepted it."
    ),
}

# Per-provider license notes, verified against each provider's own published
# terms (see docs/04-datasets.md#licensing for sources) rather than assumed --
# a firm claim here would otherwise be fabricated, per the org's own "state
# uncertainty, never fabricate" rule. Where verification wasn't possible
# (INPS), that gap is flagged explicitly as a TODO instead of guessed.
PROVIDER_LICENSES = {
    "istat": (
        "ISTAT SDMX REST API (esploradati.istat.it): free, keyless (docs/04-datasets.md). "
        'Data licence: CC BY 4.0 -- verified at istat.it/it/note-legali ("Licenza CC-by '
        "Creative Commons 4.0\"), ISTAT's own legal notice, as of this writing."
    ),
    "inps": (
        "INPS data via the StatKit hub middleware (ingestion/inps_client.py), not "
        "SDMX-REST. License terms: TODO -- not documented in this repo; verify with "
        "INPS/StatKit before external use."
    ),
    "ustat": (
        "USTAT/MUR open-data portal (CKAN), see ingestion/ustat_client.py. "
        "Data licence: Italian Open Data License (IODL) 2.0 -- verified via the CKAN "
        "package's own license_id field (dati-ustat.mur.gov.it), attributed to "
        '"MUR - Servizio Statistico", as of this writing.'
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
        row[0]
        for row in con.execute("describe select * from read_parquet(?)", [str(path)]).fetchall()
    }
    for column in ("obs_date", "period", "year", "academic_year"):
        if column in cols:
            row = con.execute(
                f"select min({column}), max({column}) from read_parquet(?)",
                [str(path)],
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
            source_keys = (
                MART_LINEAGE[stem]
                if is_mart
                else ["weather"]
                if stem == "weather_daily"
                else [stem]
            )
            count_row = con.execute("select count(*) from read_parquet(?)", [str(path)]).fetchone()
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


RELEASE_MANIFEST = DATA_DIR / "release-manifest.json"
SOURCE_RECEIPTS = DATA_DIR / "source-receipts.json"
RELEASE_MAX_AGE_DAYS = 35


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _receipt_records(payload: Any) -> dict[str, dict[str, Any]]:
    # source-receipts.json currently uses dataset names at its root. Accept
    # sealed-manifest-style {"datasets": {...}} too for tooling reuse.
    records = payload.get("datasets", payload) if isinstance(payload, dict) else payload
    if isinstance(records, dict):
        return {str(name): value for name, value in records.items() if isinstance(value, dict)}
    if isinstance(records, list):
        return {
            str(item["dataset"]): item
            for item in records
            if isinstance(item, dict) and isinstance(item.get("dataset"), str)
        }
    return {}


def _seal_release(receipts_path: Path, output_path: Path) -> dict[str, Any]:
    """Seal current bytes only when live source attestations bind every input."""
    from validate_snapshot import MART_LINEAGE as RELEASE_LINEAGE  # type: ignore[import-not-found]
    from validate_snapshot import REQUIRED_ARTIFACTS, SOURCE_NAMES  # type: ignore[import-not-found]

    try:
        payload = json.loads(receipts_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to read source receipts: {receipts_path}") from exc
    receipts = _receipt_records(payload)
    now = datetime.now(UTC).replace(microsecond=0)
    datasets: dict[str, Any] = {}
    for name in SOURCE_NAMES:
        receipt = receipts.get(name)
        if receipt is None:
            raise ValueError(f"missing source receipt for {name}")
        # data/source-receipts.json schema: provider/source_flow/request_url/
        # retrieved_at/raw_sha256 flat per dataset (see crime_reported/
        # crime_offenders entries already in the repo).
        required = ("provider", "request_url", "retrieved_at", "raw_sha256")
        missing = [
            field
            for field in required
            if not isinstance(receipt.get(field), str) or not receipt[field].strip()
        ]
        if missing:
            raise ValueError(f"{name}: receipt missing {', '.join(missing)}")
        if receipt.get("status", "fetched") != "fetched" or receipt["provider"].lower() in {
            "sample",
            "unknown",
        }:
            raise ValueError(f"{name}: source receipt is not live")
        raw_sha = receipt["raw_sha256"]
        if len(raw_sha) != 64:
            raise ValueError(f"{name}: receipt raw_sha256 required")
        raw_path = receipt.get("raw_path")
        normalized_path = DATA_DIR / (
            "weather_daily.parquet" if name == "weather" else f"{name}.parquet"
        )
        if not normalized_path.is_file():
            raise FileNotFoundError(f"required normalized artifact missing: {normalized_path}")
        actual_normalized = _sha256(normalized_path)
        marts = []
        for mart, sources in RELEASE_LINEAGE.items():
            if name in sources:
                mart_path = DATA_DIR / "marts" / f"{mart}.parquet"
                if not mart_path.is_file():
                    raise FileNotFoundError(f"required mart missing: {mart_path}")
                marts.append({"path": f"data/marts/{mart}.parquet", "sha256": _sha256(mart_path)})
        datasets[name] = {
            "source": {
                "provider": receipt["provider"],
                "flow_url": receipt["request_url"],
                "retrieved_at": receipt["retrieved_at"],
            },
            "raw": {
                "path": raw_path,
                "sha256": raw_sha,
            },
            "normalized": {"path": f"data/{normalized_path.name}", "sha256": actual_normalized},
            "marts": marts,
        }

    artifacts: dict[str, str] = {}
    for relative in REQUIRED_ARTIFACTS:
        path = REPO_ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(f"required release artifact missing: {path}")
        artifacts[relative] = _sha256(path)
    manifest = {
        "schema_version": 1,
        "status": "sealed",
        "snapshot_mode": "live",
        "sealed_at": now.isoformat(),
        "expires_at": (now + timedelta(days=RELEASE_MAX_AGE_DAYS)).isoformat(),
        "datasets": datasets,
        "artifacts": artifacts,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(output_path.name + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output_path)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seal", action="store_true", help="write checked-in live release manifest"
    )
    parser.add_argument("--receipts", type=Path, default=SOURCE_RECEIPTS)
    parser.add_argument("--output", type=Path, default=RELEASE_MANIFEST)
    args = parser.parse_args()
    if args.seal:
        try:
            manifest = _seal_release(args.receipts, args.output)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"release seal refused: {exc}", file=sys.stderr)
            return 1
        print(f"sealed {args.output} ({len(manifest['artifacts'])} artifacts)")
        return 0

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
