"""Integration: `just refresh` must fail loudly, not silently.

The `refresh` recipe runs `ingestion.fetch refresh` then `just transform`.
The recipe must stop before dbt when fetch fails: a partial snapshot must
never become a release candidate. It also propagates transform failures. This
locks both behaviors in by faking each half of the pipeline in turn.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("just") is None, reason="`just` is not installed"),
]

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _fake_uv(tmp_path: Path, fail_marker: str) -> Path:
    """A stand-in `uv` on PATH: exits 1 only for the call containing
    `fail_marker`, exits 0 for everything else (including `dbt build`), so the
    test exercises the recipe's exit-code plumbing without hitting the
    network or actually building marts."""
    fake = tmp_path / "uv"
    fake.write_text(
        f'#!/usr/bin/env bash\nif [[ "$*" == *"{fail_marker}"* ]]; then exit 1; fi\nexit 0\n'
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    return fake


def _run_refresh(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["just", "refresh"],
        cwd=PROJECT_ROOT,
        env={**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_refresh_exits_nonzero_when_ingestion_fails(tmp_path):
    _fake_uv(tmp_path, "ingestion.fetch refresh")
    result = _run_refresh(tmp_path)
    assert result.returncode != 0, result.stdout + result.stderr


def test_refresh_exits_nonzero_when_transform_fails(tmp_path):
    _fake_uv(tmp_path, "dbt build")
    result = _run_refresh(tmp_path)
    assert result.returncode != 0, result.stdout + result.stderr


def test_refresh_stops_before_transform_after_ingestion_failure(tmp_path):
    _fake_uv(tmp_path, "ingestion.fetch refresh")
    result = _run_refresh(tmp_path)
    assert "dbt build" not in result.stdout + result.stderr
