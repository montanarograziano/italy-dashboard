"""The conformance matrix is the contract between the two implementations.

Its value depends entirely on covering the paths where the two could plausibly
diverge, so these tests check the matrix itself, not just that it parses.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import generate_conformance_expected as gen

REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED = REPO_ROOT / "shared" / "conformance"


def _cases() -> list[dict]:
    return json.loads((SHARED / "cases.json").read_text())


def test_case_ids_are_unique():
    ids = [c["id"] for c in _cases()]
    assert len(ids) == len(set(ids))


def test_every_case_names_a_real_query_function():
    from italy_dashboard import queries as q

    for case in _cases():
        assert callable(getattr(q, case["function"], None)), case["function"]


def test_the_matrix_covers_an_empty_result():
    """A query returning [] is a real state, and the easiest one to get wrong.

    Both empty cases the matrix currently carries are the same shape: an
    unknown name matching no row (`climate_annual_unknown_city`,
    `climate_region_annual_unknown_region`). Neither is a mistyped argument --
    each was verified against the real snapshot to be a genuinely nonexistent
    city/region, not one written as a region code where a display name was
    expected (region-scope functions take `region_name`, not `region_code` --
    see the comment above `ITALIA = "Italia"` in `italy_dashboard/queries.py`
    -- and a code silently returns [] too, which would make an unverified
    case here look like coverage while asserting nothing).

    The spec's own named example -- `climate_stripes` returning [] when the
    CLINO coverage guard nulls every anomaly -- is NOT covered by anything in
    this matrix, and is not reachable on the current snapshot at all: no city
    has annual rows with every `anomaly_1981_2010` null. That path stays
    uncovered until a future snapshot (a wider Open-Meteo backfill, or a
    region with no CLINO baseline) actually produces it; a fixture just for
    this test file would need synthetic data no other test here uses.
    """
    expected = json.loads((SHARED / "expected.json").read_text())["results"]
    assert any(v == [] for v in expected.values()), (
        "no case in the matrix produces an empty result; add one"
    )


Mart = tuple[str, list[str]]

# _mart_where's three DIRECT public callers. Asserted present below as a
# baseline: without at least one case for each, there is nothing for the scan
# further down to work with at all.
#
# Several other public functions reach the probe INDIRECTLY, by delegating to
# one of these three, and `_probe_case_inputs` below recognises the ones that
# actually have a case in the matrix: `mart_trend_pivot` (straight to
# `mart_trend`), `kpis` (via `crime_trend`), and `offenders_kpis` (via both
# `mart_trend` and `offender_foreign_share`). `crime_trend`,
# `crime_trend_pivot` and `crime_offence_breakdown` also reach the probe
# indirectly, but no case in cases.json calls any of them -- they are thin
# CRIME_MART-baked-in wrappers, each argument-identical to a case already in
# the matrix (see the fix-round-1 report) -- so there is nothing for the scan
# to visit there even though it would recognise them if there were.
_DIRECT_PROBE_FUNCTIONS = {"mart_trend", "mart_breakdown", "offender_foreign_share"}


def _probe_case_inputs(case: dict) -> list[tuple[Mart, dict, str | None]]:
    """Every (mart, selections, skip) triple this case's function feeds to
    _mart_where, directly or by delegation. [] for a case whose function
    never reaches the probe at all (mart_options builds its own SQL, for
    instance, despite living next to the other mart wrappers).
    """
    from italy_dashboard import queries as q

    fn = case["function"]
    args = [gen._coerce_arg(a) for a in case["args"]]

    if fn in ("mart_trend", "mart_trend_pivot"):
        mart, selections, *rest = args
        return [(mart, selections, rest[0] if rest else None)]
    if fn == "mart_breakdown":
        mart, breakdown_dim, selections = args[0], args[1], args[2]
        return [(mart, selections, breakdown_dim)]
    if fn == "offender_foreign_share":
        (selections,) = args
        filtered = {k: v for k, v in selections.items() if k != "citizenship"}
        return [(q.OFFENDERS_MART, {**filtered, "citizenship": "All"}, "citizenship")]
    if fn == "kpis":
        # kpis() -> crime_trend(all-"All") -> mart_trend(CRIME_MART, ..., None).
        return [(q.CRIME_MART, dict.fromkeys(q.CRIME_MART[1], "All"), None)]
    if fn == "offenders_kpis":
        # offenders_kpis(selections) calls mart_trend(OFFENDERS_MART,
        # selections) and offender_foreign_share(selections); its third call,
        # offender_rates, builds its own WHERE and never reaches _mart_where.
        (selections,) = args
        filtered = {k: v for k, v in selections.items() if k != "citizenship"}
        return [
            (q.OFFENDERS_MART, selections, None),
            (q.OFFENDERS_MART, {**filtered, "citizenship": "All"}, "citizenship"),
        ]
    return []


def _naive_all_totals_where(
    mart: Mart, selections: dict, skip: str | None, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, list] | None:
    """What _mart_where would return if a TypeScript port skipped the probe
    entirely and always emitted `{dim}_is_total = true` for every free
    dimension -- the exact port F1 constructed. `None` when there is no free
    dimension for a probe-free port to get wrong.

    Obtained by rigging _mart_where's OWN probe query to report a single,
    all-true candidate, then calling the real function: this compares
    `_mart_where`'s actual output against itself under a fake data condition,
    rather than reimplementing its fixed/free-dimension WHERE construction a
    second time to measure a proxy for the same thing (year-coverage
    distinctness), which is what this replaced -- see the fix-round-2 report.
    """
    from italy_dashboard import queries as q

    _, dims = mart
    free = [d for d in dims if d != skip and selections.get(d, "All") == "All"]
    if not free:
        return None

    real_query = q._query
    stub_combo = dict.fromkeys((f"{d}_is_total" for d in free), True) | {"yc": 1}

    def rigged(sql: str, params: list | None = None):
        if "GROUP BY ALL" in sql:  # this is _mart_where's own combos probe
            return [stub_combo]
        return real_query(sql, params)

    monkeypatch.setattr(q, "_query", rigged)
    try:
        return q._mart_where(mart, selections, skip=skip)
    finally:
        monkeypatch.setattr(q, "_query", real_query)


def test_the_matrix_covers_the_dynamic_mart_engine(monkeypatch: pytest.MonkeyPatch):
    """_mart_where probes the data to choose an is_total flag combination.

    It is the single most likely thing to diverge in a reimplementation, and a
    function *name* appearing in the matrix proves nothing about it: on
    mart_crime every is_total combination happens to have identical year
    coverage, so a TypeScript port that skips the probe entirely and always
    emits the all-totals combination reproduces every mart_crime case in this
    matrix byte for byte (this bit for real; see the case added on
    mart_offenders and the git history of this test). What actually matters is
    that at least one covered case's real _mart_where output is provably
    distinguishable from what that exact probe-free port would produce.
    """
    from italy_dashboard import queries as q

    cases = _cases()
    functions = {c["function"] for c in cases}
    assert functions >= _DIRECT_PROBE_FUNCTIONS, (
        f"no case calls any of {_DIRECT_PROBE_FUNCTIONS}, the direct public "
        "callers of _mart_where; mart_options builds its own SQL and never "
        "reaches it"
    )

    distinguishable = []
    for case in cases:
        for mart, selections, skip in _probe_case_inputs(case):
            real = q._mart_where(mart, selections, skip=skip)
            naive = _naive_all_totals_where(mart, selections, skip, monkeypatch)
            if naive is not None and naive != real:
                distinguishable.append(case["id"])

    assert distinguishable, (
        "every probe-reaching case in the matrix sits on a mart/selection "
        "where the all-totals combination is indistinguishable from the real "
        "probe's choice, so a probe-free port would conform everywhere; add a "
        "case on a mart where it does not (see mart_offenders)"
    )


def test_committed_expected_matches_the_generator():
    """Regenerating must be a no-op unless the data or a query changed."""
    assert (SHARED / "expected.json").read_text() == gen.build()


def test_expected_records_the_snapshot_fingerprint():
    """Expected output is only meaningful against the data it was generated from."""
    recorded = json.loads((SHARED / "expected.json").read_text())["fingerprint"]
    assert recorded == gen.fingerprint_digest(gen.tracked_snapshot_fingerprint())


def test_the_recorded_fingerprint_reproduces_in_a_second_checkout(monkeypatch: pytest.MonkeyPatch):
    """The digest must identify the COMMITTED data, not this machine or moment.

    It used to be built from absolute paths, `st_mtime_ns` and a glob that also
    caught the untracked dbt inputs, so a fresh clone or a git worktree computed
    a different digest (measured: 18 files / 1142563040ca2e00 here against 14 /
    21218be79b0aad0a in a clone) and started red on an opaque mismatch. Since
    plan 2 is meant to be developed in a worktree, and since a new contributor's
    first `pytest` run hit the same thing, the property is worth pinning rather
    than trusting the code to keep it.

    A real second checkout is what makes this discriminate. Any in-process
    reformulation over the same directory would pass whether or not the entries
    carried absolute paths and mtimes; a `git worktree` of the same commit has
    different absolute paths, freshly written files (so different mtimes) and no
    untracked parquet at all -- the three differences that used to move the
    digest. `gen.REPO_ROOT` is redirected at it rather than the code being run
    from it, so the CURRENT implementation is what gets measured (the worktree
    holds HEAD's copy of the script, which is one commit behind by definition).
    """
    here = gen.fingerprint_digest(gen.tracked_snapshot_fingerprint())
    subprocess.run(["git", "worktree", "prune"], cwd=REPO_ROOT, check=True, capture_output=True)
    with tempfile.TemporaryDirectory() as tmp:
        checkout = Path(tmp) / "same-commit"
        subprocess.run(
            ["git", "worktree", "add", "--detach", "--quiet", str(checkout), "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
        )
        try:
            with monkeypatch.context() as patched:
                patched.setattr(gen, "REPO_ROOT", checkout)
                elsewhere = gen.fingerprint_digest(gen.tracked_snapshot_fingerprint())
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(checkout)],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
            )
    assert elsewhere == here, (
        f"the fingerprint differs between two checkouts of the same commit: "
        f"worktree {elsewhere!r} vs working tree {here!r}"
    )
