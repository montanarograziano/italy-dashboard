from __future__ import annotations

import hashlib
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import validate_snapshot as gate  # type: ignore[import-not-found]


def _write_release(tmp_path: Path) -> dict:
    data = tmp_path / "data"
    (data / "marts").mkdir(parents=True)
    artifacts: dict[str, str] = {}
    for relative in gate.REQUIRED_ARTIFACTS:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(relative.encode())
        artifacts[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    now = datetime.now(UTC).replace(microsecond=0)
    datasets = {}
    for name in gate.SOURCE_NAMES:
        normalized = "data/weather_daily.parquet" if name == "weather" else f"data/{name}.parquet"
        datasets[name] = {
            "source": {
                "provider": "test",
                "flow_url": "https://example.test/flow",
                "retrieved_at": now.isoformat(),
            },
            "raw": {"sha256": "a" * 64},
            "normalized": {"path": normalized, "sha256": artifacts[normalized]},
            "marts": [
                {
                    "path": f"data/marts/{mart}.parquet",
                    "sha256": artifacts[f"data/marts/{mart}.parquet"],
                }
                for mart, sources in gate.MART_LINEAGE.items()
                if name in sources
            ],
        }
    return {
        "schema_version": 1,
        "status": "sealed",
        "snapshot_mode": "live",
        "sealed_at": now.isoformat(),
        "expires_at": (now + timedelta(days=35)).isoformat(),
        "datasets": datasets,
        "artifacts": artifacts,
    }


def test_valid_manifest_binds_every_required_artifact(tmp_path: Path):
    assert gate.validate_manifest(_write_release(tmp_path), tmp_path / "data") == []


def test_gate_rejects_sample_and_tampered_artifact(tmp_path: Path):
    manifest = _write_release(tmp_path)
    manifest["snapshot_mode"] = "sample"
    path = tmp_path / "data" / "population_resident.parquet"
    path.write_bytes(b"tampered")
    errors = gate.validate_manifest(manifest, tmp_path / "data")
    assert any("sample/unknown" in error for error in errors)
    assert any("hash mismatch" in error for error in errors)


def test_gate_rejects_stale_receipt(tmp_path: Path):
    manifest = _write_release(tmp_path)
    old = (datetime.now(UTC) - timedelta(days=36)).isoformat()
    manifest["sealed_at"] = old
    manifest["expires_at"] = old
    manifest["datasets"]["weather"]["source"]["retrieved_at"] = old
    errors = gate.validate_manifest(manifest, tmp_path / "data")
    assert any("stale" in error for error in errors)
