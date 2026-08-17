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
def harness_page(vite_server: str, browser):
    """The loaded harness page (see the module docstring for why the browser is
    pytest-playwright's and not a private one).

    Waiting on `runConformance` is what makes this ready: the harness assigns it
    last, so every other `window.*` entry point is in place by then.
    """
    page = browser.new_page()
    try:
        page.goto(f"{vite_server}/conformance/harness.html")
        page.wait_for_function("() => typeof window.runConformance === 'function'")
        yield page
    finally:
        page.close()


@pytest.fixture(scope="module")
def results(harness_page) -> dict:
    return harness_page.evaluate("() => window.runConformance()")


@pytest.fixture(scope="module")
def implemented_functions(harness_page) -> list[str]:
    """The functions the harness CLAIMS to have ported (harness.ts IMPLEMENTED)."""
    return harness_page.evaluate("() => window.implementedFunctions()")


@pytest.fixture(scope="module")
def missing_parquet_probe(harness_page) -> dict:
    """A connection booted with one parquet path that does not exist."""
    return harness_page.evaluate("() => window.probeMissingParquet()")


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


def test_every_ported_function_actually_produced_a_result(
    results: dict, implemented_functions: list[str]
):
    """Guards against the harness silently covering less than it claims.

    Derived from the harness's own IMPLEMENTED map rather than from a number.
    The floor used to be a hardcoded `>= 4` with exactly four functions ported,
    so it was tight on the day it was written and stopped ratcheting the moment
    a fifth landed -- a later regression from twenty ports back down to four
    would have passed it. This version tightens automatically with every port,
    and closes the same hole the old floor did (relabelling a broken port's
    errors as `__unported__` now contradicts IMPLEMENTED).

    IMPLEMENTED itself cannot shrink silently either: it is pinned against the
    functions actually exported by `web/src/queries/static.ts` in
    `tests/unit/test_conformance_cases.py`.

    Compares distinct FUNCTIONS, not cases: several cases can exercise one
    function (climate_annual_series has two in this matrix).
    """
    claimed = set(implemented_functions)
    assert claimed, "the harness claims no ported functions at all"

    matrix_functions = set(CASE_FUNCTIONS.values())
    unmeasured = claimed - matrix_functions
    assert not unmeasured, (
        f"ported but no case in the matrix, so nothing measures them: {sorted(unmeasured)}"
    )

    produced = {CASE_FUNCTIONS[case_id] for case_id, v in results.items() if not _is_unported(v)}
    assert produced == claimed, (
        f"claimed ported {sorted(claimed)} but produced real results for {sorted(produced)}"
    )


def test_a_missing_parquet_does_not_break_unrelated_queries(missing_parquet_probe: dict):
    """One absent dataset must cost exactly that dataset, not the whole app.

    Registration is eager (DuckDB reads each parquet's footer to build the
    view), so a single missing file used to abort the connection and therefore
    every query: reproduced at 53 of 53 cases erroring. The static deploy
    excludes `mart_climate_daily` by design, so the deployed app would have
    failed to initialise at all.

    Both halves matter. Tolerating the absence is only correct if a query that
    NEEDS the missing table still fails -- otherwise this trades a loud failure
    for a silently empty chart, which is worse.
    """
    probe = missing_parquet_probe
    assert probe["failed"] == ["mart_absent_from_this_build"], probe
    assert probe["presentTableRows"] > 0, (
        f"a query on a present table returned nothing after a sibling parquet was missing: {probe}"
    )
    assert "mart_absent_from_this_build" in probe["missingTableError"], (
        f"a query on the ABSENT table did not fail loudly: {probe}"
    )


def test_the_typescript_typechecks():
    """`tsc` runs nowhere else, so a strict tsconfig is decorative without this.

    Vite/esbuild strips types without checking them, so a blatant type error in
    `web/` passed the entire suite. That matters most for
    `noUncheckedIndexedAccess`, which is exactly the guard against the latent
    `undefined` that conforms on today's snapshot and diverges on tomorrow's.
    """
    result = subprocess.run(
        ["npm", "run", "--silent", "typecheck"],
        cwd=ROOT / "web",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"tsc failed:\n{result.stdout}\n{result.stderr}"


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


def test_no_case_is_unported(results: dict):
    """Every matrix case now has a TypeScript port, and must keep having one.

    Until the port completed, `__unported__` was the honest state of partial
    work and this suite counted it rather than hiding it. Now that every case
    is ported, the same marker means the opposite thing: a case was added to
    the matrix with no TypeScript counterpart, which is exactly the divergence
    this suite exists to prevent. Failing here costs a build; discovering it in
    the UI costs a wrong number on a public dashboard.
    """
    unported = sorted(k for k, v in results.items() if _is_unported(v))
    assert not unported, (
        f"{len(unported)} of {len(results)} cases have no TypeScript port: "
        f"{unported}. Port them, or remove them from shared/conformance/cases.json."
    )
