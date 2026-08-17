"""Run the conformance matrix through real DuckDB-WASM in a real browser.

The static frontend will ship WASM DuckDB reading parquet over HTTP, so the
harness runs in that environment rather than under Node: a Node-only check
could pass while the shipped configuration fails.

Cases whose function is not yet ported report __unported__ and are counted, not
silently ignored. A harness that quietly covers less than it claims is worse
than no harness.

Unlike the other files in this directory, this module does NOT guard its
Playwright dependency with `pytest.importorskip`. This is the harness whose
entire purpose is to prove a real divergence gets caught -- an `importorskip`
would turn "Playwright is not installed" into a silent, green SKIP for exactly
this test, which is the one test in the repo that must never report success
without having actually run. The `browser` marker (see `pytestmark` below)
still keeps it out of the default run via `addopts` in pyproject.toml; explicit
selection (`-m browser`, `just test-conformance`) is what asks for the real
thing, and a missing dependency should fail loudly there, not skip quietly.
It does that: with pytest-playwright absent, the `browser` fixture below is
unresolvable and every test here ERRORS.

The browser comes from pytest-playwright's own session-scoped `browser`
fixture, like every sibling file in this directory, rather than from a private
`sync_playwright()` context. That is not a style preference: the Reflex browser
tests run first under `pytest -m browser` and leave pytest-playwright's own
sync context open, and a second independent `sync_playwright()` start in the
same thread trips playwright's "Sync API inside the asyncio loop" guard (see
`conftest.py::_require_chromium`, which hit the same thing). Every test in this
module used to ERROR in that run -- so the divergence gate was silent unless
invoked as exactly `just test-conformance`, which is the "the gate only works
if you type it one specific way" fragility this project has been bitten by
before.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads((ROOT / "shared" / "conformance" / "cases.json").read_text())
CASE_FUNCTIONS = {c["id"]: c["function"] for c in CASES}
EXPECTED = json.loads((ROOT / "shared" / "conformance" / "expected.json").read_text())


def _is_unported(value: object) -> bool:
    return isinstance(value, dict) and "__unported__" in value


@pytest.fixture(scope="module")
def vite_server():
    """Serve web/src plus the repo's data/ directory, as the deployed site will."""
    proc = subprocess.Popen(
        ["npm", "run", "dev", "--", "--port", "5178", "--strictPort"],
        cwd=ROOT / "web",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        import urllib.error
        import urllib.request

        for _ in range(60):
            time.sleep(1)
            try:
                urllib.request.urlopen("http://localhost:5178/conformance/harness.html")
                break
            except (urllib.error.URLError, ConnectionError):
                continue
        else:
            proc.terminate()
            pytest.fail(f"vite did not start:\n{proc.stdout.read() if proc.stdout else ''}")
        yield "http://localhost:5178"
    finally:
        proc.terminate()
        proc.wait(timeout=30)


@pytest.fixture(scope="module")
def results(vite_server: str, browser) -> dict:
    """Every case's output, run once in the browser (see the module docstring
    for why the browser is pytest-playwright's and not a private one).
    """
    page = browser.new_page()
    try:
        page.goto(f"{vite_server}/conformance/harness.html")
        page.wait_for_function("() => typeof window.runConformance === 'function'")
        return page.evaluate("() => window.runConformance()")
    finally:
        page.close()


def test_no_case_errored(results: dict):
    errors = {k: v for k, v in results.items() if isinstance(v, dict) and "__error__" in v}
    assert not errors, f"cases raised in the browser: {errors}"


def test_every_case_is_accounted_for(results: dict):
    """No case goes missing: it is ported, ported-but-errored, or explicitly
    reported as `__unported__`. A harness that silently dropped a case (as
    opposed to marking it unported) would look identical to one covering
    everything, which is the exact failure mode this suite exists to catch.
    """
    assert set(results) == set(CASE_FUNCTIONS), (
        f"harness reported {len(results)} cases, matrix has {len(CASE_FUNCTIONS)}: "
        f"missing {set(CASE_FUNCTIONS) - set(results)}, extra {set(results) - set(CASE_FUNCTIONS)}"
    )


def test_at_least_four_functions_are_ported(results: dict):
    """Guards against the harness silently covering nothing.

    Counts distinct PORTED FUNCTIONS, not cases: several cases can exercise one
    function (climate_annual_series alone has two in this matrix), so counting
    cases would keep passing long after the function count dropped below four --
    exactly the silent-shrink this test exists to catch.
    """
    ported_functions = {
        CASE_FUNCTIONS[case_id] for case_id, v in results.items() if not _is_unported(v)
    }
    assert len(ported_functions) >= 4, f"only {len(ported_functions)} ported: {ported_functions}"


def test_ported_cases_match_the_python_reference(results: dict):
    """The whole point: same inputs, same data, same output.

    A mismatch means the TypeScript port diverged from its Python original, or
    that expected.json is stale and needs regenerating with `just
    generate-shared` and its diff reviewed.
    """
    mismatches = {}
    for case_id, actual in results.items():
        if _is_unported(actual):
            continue
        want = EXPECTED["results"][case_id]
        if actual != want:
            mismatches[case_id] = {"python": want, "typescript": actual}
    assert not mismatches, json.dumps(mismatches, indent=2)[:4000]
