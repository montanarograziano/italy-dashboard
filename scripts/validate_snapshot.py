"""Strict, dependency-free production release gate.

Checks checked-in ``data/release-manifest.json`` against bytes on disk. It
never fetches or regenerates data, so Pages and Docker can run same gate.
Sample/unknown/partial/stale snapshots fail; use ``just seal-release`` only
after live fetch, normalization, dbt build, and source attestations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
MANIFEST_PATH = DATA_DIR / "release-manifest.json"
MAX_AGE_DAYS = 35

# Keep release scope explicit. A new source or mart must be added here and to
# the seal generator before it can become publishable.
REQUIRED_NORMALIZED = (
    "economy_inflation",
    "education_university_scholarships",
    "income_regional",
    "labor_naspi_beneficiaries",
    "labor_unemployment",
    "population_foreign",
    "population_resident",
    "crime_reported",
    "crime_offenders",
    "weather_daily",
)
REQUIRED_MARTS = (
    "mart_climate_annual",
    "mart_climate_daily",
    "mart_climate_monthly",
    "mart_climate_region",
    "mart_crime_climate",
    "mart_crime_income",
    "mart_crime",
    "mart_dsu",
    "mart_naspi",
    "mart_offender_rates",
    "mart_offenders",
    "mart_population",
)
REQUIRED_ARTIFACTS = tuple(
    [f"data/{name}.parquet" for name in REQUIRED_NORMALIZED]
    + [f"data/marts/{name}.parquet" for name in REQUIRED_MARTS]
)

# Per-source lineage. Weather has no registry normalized name but is a required
# source, and all climate marts depend on it.
MART_LINEAGE: dict[str, tuple[str, ...]] = {
    "mart_crime": ("crime_reported",),
    "mart_offenders": ("crime_offenders",),
    "mart_offender_rates": ("crime_offenders", "population_resident", "population_foreign"),
    "mart_crime_income": (
        "crime_offenders",
        "population_resident",
        "population_foreign",
        "income_regional",
    ),
    "mart_population": ("population_resident", "population_foreign"),
    "mart_dsu": ("education_university_scholarships",),
    "mart_naspi": ("labor_naspi_beneficiaries",),
    "mart_climate_daily": ("weather",),
    "mart_climate_monthly": ("weather",),
    "mart_climate_annual": ("weather",),
    "mart_climate_region": ("weather",),
    "mart_crime_climate": ("crime_offenders", "weather"),
}
SOURCE_NAMES = (*REQUIRED_NORMALIZED[:-1], "weather")


def _parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be ISO-8601 text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} is not ISO-8601: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include timezone")
    return parsed.astimezone(UTC)


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_hash(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    )


def _records(value: Any) -> dict[str, dict[str, Any]]:
    if isinstance(value, dict):
        result = {}
        for key, record in value.items():
            if isinstance(record, dict):
                result[str(key)] = record
        return result
    if isinstance(value, list):
        return {
            str(record["dataset"]): record
            for record in value
            if isinstance(record, dict) and isinstance(record.get("dataset"), str)
        }
    return {}


def validate_manifest(
    manifest: dict[str, Any],
    data_dir: Path = DATA_DIR,
    *,
    now: datetime | None = None,
    max_age_days: int = MAX_AGE_DAYS,
) -> list[str]:
    """Return all release-gate errors. Empty list means publishable."""
    errors: list[str] = []
    if manifest.get("schema_version") != 1:
        errors.append("manifest schema_version must be 1")
    if manifest.get("status") != "sealed":
        errors.append("manifest status must be sealed")
    if manifest.get("snapshot_mode") != "live":
        errors.append("manifest snapshot_mode must be live (sample/unknown forbidden)")

    current = (now or datetime.now(UTC)).astimezone(UTC)
    for field in ("sealed_at", "expires_at"):
        try:
            parsed = _parse_time(manifest.get(field), field)
            if field == "expires_at" and current >= parsed:
                errors.append("manifest is stale: expires_at has passed")
        except ValueError as exc:
            errors.append(str(exc))
    try:
        sealed_at = _parse_time(manifest.get("sealed_at"), "sealed_at")
        if sealed_at > current + timedelta(minutes=5):
            errors.append("sealed_at is in the future")
        if current - sealed_at > timedelta(days=max_age_days):
            errors.append(f"manifest is stale: sealed_at is older than {max_age_days} days")
    except ValueError:
        sealed_at = None

    records = _records(manifest.get("datasets"))
    missing_sources = sorted(set(SOURCE_NAMES) - set(records))
    if missing_sources:
        errors.append(f"manifest missing source attestations: {', '.join(missing_sources)}")

    expected_by_source: dict[str, list[str]] = {name: [] for name in SOURCE_NAMES}
    for mart, sources in MART_LINEAGE.items():
        path = f"data/marts/{mart}.parquet"
        for source in sources:
            expected_by_source[source].append(path)

    for source_name in SOURCE_NAMES:
        record = records.get(source_name)
        if record is None:
            continue
        evidence = record.get("source", record)
        if not isinstance(evidence, dict):
            errors.append(f"{source_name}: source evidence missing")
            continue
        for field in ("provider", "flow_url", "retrieved_at"):
            if not isinstance(evidence.get(field), str) or not evidence[field].strip():
                errors.append(f"{source_name}: source.{field} required")
        try:
            retrieved = _parse_time(evidence.get("retrieved_at"), f"{source_name}.retrieved_at")
            if current - retrieved > timedelta(days=max_age_days):
                errors.append(f"{source_name}: source receipt is stale")
            if retrieved > current + timedelta(minutes=5):
                errors.append(f"{source_name}: source receipt is in the future")
        except ValueError as exc:
            errors.append(str(exc))
        raw = record.get("raw") or {}
        normalized = record.get("normalized") or {}
        if not _valid_hash(raw.get("sha256")):
            errors.append(f"{source_name}: raw.sha256 required")
        if not _valid_hash(normalized.get("sha256")):
            errors.append(f"{source_name}: normalized.sha256 required")
        expected_normalized = (
            "data/weather_daily.parquet"
            if source_name == "weather"
            else f"data/{source_name}.parquet"
        )
        if normalized.get("path") != expected_normalized:
            errors.append(f"{source_name}: normalized.path must be {expected_normalized}")
        if [
            item.get("path") for item in record.get("marts", []) if isinstance(item, dict)
        ] != expected_by_source[source_name]:
            errors.append(f"{source_name}: mart lineage incomplete or out of order")

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        errors.append("manifest artifacts must be an object of path -> sha256")
        artifacts = {}
    for relative in REQUIRED_ARTIFACTS:
        expected = artifacts.get(relative)
        path = data_dir.parent / relative
        if not _valid_hash(expected):
            errors.append(f"missing or invalid artifact hash: {relative}")
            continue
        if "sample" in relative.lower():
            errors.append(f"sample artifact forbidden: {relative}")
        if not path.is_file():
            errors.append(f"required artifact missing: {relative}")
            continue
        actual = _hash(path)
        if actual != expected:
            errors.append(f"artifact hash mismatch: {relative}")
        if path.stat().st_size == 0:
            errors.append(f"required artifact empty: {relative}")

    for relative, expected in artifacts.items():
        if (
            not isinstance(relative, str)
            or not relative.startswith("data/")
            or Path(relative).is_absolute()
        ):
            errors.append(f"invalid artifact path: {relative!r}")
        elif not _valid_hash(expected):
            errors.append(f"invalid artifact hash: {relative}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    args = parser.parse_args(argv)
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("manifest root must be an object")
        errors = validate_manifest(manifest, args.data_dir)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"release gate: {exc}", file=sys.stderr)
        return 1
    if errors:
        print("release gate: REFUSED", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print(f"release gate: OK ({args.manifest})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
