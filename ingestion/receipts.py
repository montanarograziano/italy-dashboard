"""Single place that writes `data/source-receipts.json`.

`scripts/generate_provenance_manifest.py::_seal_release` reads this file to
attest which bytes on disk came from which live fetch. A successful refresh
that does NOT update its receipt leaves the seal blocked (missing receipt) or,
worse, attesting a stale one — this module is what fetch.py/cds.py/weather.py
call right after a fetch actually lands to keep the two in sync.

Every write is a read-merge-write of ONE dataset key, never a wholesale
rewrite: another process (a concurrent refresh of a different dataset, or a
human editing a different key by hand) can be touching the same file at the
same time, and its own key must survive untouched. An flock on the file
serialises the read-modify-write across processes so two concurrent upserts
to different keys cannot race and drop one of them.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Registry `provider` value -> the display string already used in
# data/source-receipts.json's existing entries (see crime_reported/
# labor_naspi_beneficiaries/education_university_scholarships).
PROVIDER_DISPLAY = {
    "istat": "ISTAT",
    "inps": "inps",
    "ustat": "ustat",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def upsert_receipt(path: Path, dataset: str, fields: dict[str, Any]) -> None:
    """Merge `fields` into `dataset`'s entry in the receipts file at `path`.

    Every other key already in the file, including one another process is
    editing concurrently, is read fresh and carried through unchanged.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # Lock a stable sidecar, not the data file: `tmp.replace(path)` swaps the
    # data file's inode, so a lock held on it would not exclude a second
    # process that opens the freshly renamed file.
    lock_path = path.with_name(path.name + ".lock")
    with lock_path.open("a") as lock_fh:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)
        try:
            raw_text = path.read_text(encoding="utf-8") if path.exists() else ""
            data: Any = json.loads(raw_text) if raw_text.strip() else {}
            if not isinstance(data, dict):
                raise ValueError(f"{path} root must be a JSON object, found {type(data).__name__}")
            entry = data.get(dataset)
            entry = dict(entry) if isinstance(entry, dict) else {}
            entry.update(fields)
            data[dataset] = entry
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            tmp.replace(path)
        finally:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)


def upsert_fetch_receipt(
    path: Path,
    dataset: str,
    *,
    provider: str,
    source_flow: str | None,
    request_url: str | None,
    raw_path: str | None,
    raw_bytes: bytes,
    count_lines: bool = True,
) -> None:
    """Record a successful fetch: status, provider, flow, URL, hash, size.

    Called only on a SUCCESSFUL fetch + normalize (never from a normalize-only
    re-run of existing raw bytes), so `retrieved_at`/`raw_sha256` always mean
    "this is what was actually downloaded just now". `count_lines=False` for
    binary artifacts (e.g. weather_daily.parquet), where a line count is
    meaningless.
    """
    fields: dict[str, Any] = {
        "status": "fetched",
        "provider": provider,
        "request_url": request_url or "",
        "retrieved_at": now_iso(),
        "raw_sha256": sha256_bytes(raw_bytes),
        "bytes": len(raw_bytes),
    }
    if count_lines:
        fields["lines"] = len(raw_bytes.splitlines())
    if source_flow is not None:
        fields["source_flow"] = source_flow
    if raw_path is not None:
        fields["raw_path"] = raw_path
    upsert_receipt(path, dataset, fields)
