"""The provenance manifest is a release-safety gate, so its own wiring needs
a check as much as any query does: a lineage entry that silently drifts from
the dbt graph, or a mart nobody added to `MART_LINEAGE`, would make the
manifest quietly report less than it claims -- the exact failure mode
`tests/browser/test_conformance.py` polices for the conformance matrix.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import generate_provenance_manifest as gen

REPO_ROOT = Path(__file__).resolve().parents[2]


def _tracked_mart_stems() -> set[str]:
    listing = subprocess.run(
        ["git", "ls-files", "-z", "--", "data/marts"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return {Path(name).stem for name in listing.split("\0") if name.endswith(".parquet")}


def test_mart_lineage_covers_every_committed_mart():
    """A new mart with no MART_LINEAGE entry would KeyError in build_manifest
    rather than silently omitting its provenance -- this just gives that a
    readable failure at the source instead of a traceback deep in a script."""
    missing = _tracked_mart_stems() - set(gen.MART_LINEAGE)
    assert not missing, f"marts with no MART_LINEAGE entry: {sorted(missing)}"


def test_mart_lineage_keys_are_known_registry_datasets_or_weather():
    registry = gen._registry()
    unknown = {
        key
        for keys in gen.MART_LINEAGE.values()
        for key in keys
        if key != "weather" and key not in registry
    }
    assert not unknown, f"MART_LINEAGE references unknown registry datasets: {sorted(unknown)}"


def test_build_manifest_against_the_committed_snapshot():
    """Runs for real against `git ls-files -- data`: no network, no live
    fetch, exactly what a fresh clone has (see the module docstring)."""
    manifest = gen.build_manifest()

    assert manifest["warnings"] == [], manifest["warnings"]
    assert manifest["datasets"], "no tracked parquet found under data/"

    tracked = subprocess.run(
        ["git", "ls-files", "--", "data"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    tracked_parquet = {p for p in tracked if p.endswith(".parquet")}
    assert {e["path"] for e in manifest["datasets"]} == tracked_parquet

    for entry in manifest["datasets"]:
        assert entry["row_count"] > 0, entry["path"]
        assert len(entry["sha256"]) == 64
        assert entry["sources"], entry["path"]
        for source in entry["sources"]:
            assert source["provider"] is not None, entry["path"]


def test_snapshot_provenance_reports_unknown_without_a_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(gen, "PROVENANCE_MARKER", tmp_path / "nope.json")
    status = gen._snapshot_provenance()
    assert status["mode"] == "unknown"
    assert status["recorded_at"] is None
    assert "run `just sample`" in status["note"]


def test_snapshot_provenance_reads_a_real_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    marker = tmp_path / ".provenance.json"
    marker.write_text(json.dumps({"mode": "live", "generated_at": "2026-01-01T00:00:00+00:00"}))
    monkeypatch.setattr(gen, "PROVENANCE_MARKER", marker)
    status = gen._snapshot_provenance()
    assert status == {"mode": "live", "recorded_at": "2026-01-01T00:00:00+00:00", "note": None}


def test_snapshot_provenance_reports_unknown_on_a_malformed_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    marker = tmp_path / ".provenance.json"
    marker.write_text("not json")
    monkeypatch.setattr(gen, "PROVENANCE_MARKER", marker)
    status = gen._snapshot_provenance()
    assert status["mode"] == "unknown"
    assert "malformed" in status["note"]


def test_provider_licenses_cover_every_provider_in_the_registry():
    """A new provider (a fourth ingestion client) must not ship with a silent
    `null` license -- see PROVIDER_LICENSES' own comment on why a real gap is
    reported as a TODO rather than left blank."""
    registry = gen._registry()
    providers = {cfg.get("provider", "istat") for cfg in registry.values()}
    assert providers <= set(gen.PROVIDER_LICENSES), (
        f"registry uses provider(s) with no PROVIDER_LICENSES entry: "
        f"{providers - set(gen.PROVIDER_LICENSES)}"
    )


def test_registry_loads_with_yaml():
    """Sanity check on the loader itself, independent of build_manifest()."""
    registry = gen._registry()
    assert "population_resident" in registry
    raw = yaml.safe_load((REPO_ROOT / "ingestion" / "registry.yaml").read_text())
    assert registry == raw["datasets"]
