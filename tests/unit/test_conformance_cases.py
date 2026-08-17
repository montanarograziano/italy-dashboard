"""The conformance matrix is the contract between the two implementations.

Its value depends entirely on covering the paths where the two could plausibly
diverge, so these tests check the matrix itself, not just that it parses.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import generate_conformance_expected as gen

SHARED = Path(__file__).resolve().parents[2] / "shared" / "conformance"


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

    climate_stripes returns nothing when the CLINO coverage guard nulls every
    anomaly, which is correct behaviour, not a bug. Both implementations must
    agree on it.
    """
    expected = json.loads((SHARED / "expected.json").read_text())["results"]
    assert any(v == [] for v in expected.values()), (
        "no case in the matrix produces an empty result; add one"
    )


# mart_options builds its own SQL directly and never calls _mart_where, so it
# does not belong in this set despite living next to the other mart wrappers
# (see italy_dashboard/queries.py's mart_options). These three are the only
# public functions that reach the probe.
_PROBE_FUNCTIONS = {"mart_trend", "mart_breakdown", "offender_foreign_share"}


Mart = tuple[str, list[str]]


def _free_dims(mart: Mart, selections: dict, skip: str | None) -> list[str]:
    """Dimensions _mart_where would leave for the probe to decide between."""
    _, dims = mart
    return [d for d in dims if d != skip and selections.get(d, "All") == "All"]


def _fixed_where_and_params(mart: Mart, selections: dict, skip: str | None) -> tuple[str, list]:
    """Mirrors _mart_where's own fixed-clause construction for pinned
    dimensions and the skip dimension (italy_dashboard/queries.py's
    `_mart_where`), so the probe's combos query can be reconstructed and its
    year-coverage measured directly. `_mart_where`'s return value alone can't
    answer this: it only reports the winning combination, never whether any
    other candidate would have scored differently.
    """
    _, dims = mart
    scope = selections.get("_region_scope") or "region"
    fixed: list[str] = []
    params: list = []
    for dim in dims:
        selected = selections.get(dim, "All")
        if dim == skip:
            fixed.append(f"NOT {dim}_is_total")
            if dim == "region":
                fixed.append("region_level = 'region'")
        elif selected != "All":
            fixed.append(f"NOT {dim}_is_total")
            fixed.append(f"{dim}_name = ?")
            params.append(selected)
            if dim == "region":
                fixed.append("region_level = ?")
                params.append(scope)
    return " AND ".join(fixed) or "TRUE", params


def _mart_where_inputs(case: dict) -> tuple[Mart, dict, str | None] | None:
    """(mart, selections, skip) for a case reaching _mart_where's probe, or
    None for a case whose function isn't one of `_PROBE_FUNCTIONS`.
    """
    fn = case["function"]
    args = [gen._coerce_arg(a) for a in case["args"]]
    if fn == "mart_trend":
        mart, selections, *rest = args
        return mart, selections, (rest[0] if rest else None)
    if fn == "mart_breakdown":
        mart, breakdown_dim, selections = args[0], args[1], args[2]
        return mart, selections, breakdown_dim
    if fn == "offender_foreign_share":
        from italy_dashboard import queries as q

        (selections,) = args
        filtered = {k: v for k, v in selections.items() if k != "citizenship"}
        return q.OFFENDERS_MART, {**filtered, "citizenship": "All"}, "citizenship"
    return None


def test_the_matrix_covers_the_dynamic_mart_engine():
    """_mart_where probes the data to choose an is_total flag combination.

    It is the single most likely thing to diverge in a reimplementation, and a
    function *name* appearing in the matrix proves nothing about it: on
    mart_crime every is_total combination happens to have identical year
    coverage, so a TypeScript port that skips the probe entirely and always
    emits the all-totals combination reproduces every mart_crime case in this
    matrix byte for byte (this bit for real; see the case added on
    mart_offenders and the git history of this test). What actually matters is
    that at least one covered case sits on a mart/selection where the
    combinations genuinely differ in year coverage, so a probe-free port is
    provably distinguishable from the committed reference.
    """
    from italy_dashboard import queries as q

    cases = _cases()
    functions = {c["function"] for c in cases}
    assert functions >= _PROBE_FUNCTIONS, (
        f"no case calls any of {_PROBE_FUNCTIONS}, the only public callers of "
        "_mart_where; mart_options builds its own SQL and never reaches it"
    )

    non_degenerate = []
    for case in cases:
        inputs = _mart_where_inputs(case)
        if inputs is None:
            continue
        mart, selections, skip = inputs
        free = _free_dims(mart, selections, skip)
        if not free:
            continue
        where, params = _fixed_where_and_params(mart, selections, skip)
        flag_cols = ", ".join(f"{d}_is_total" for d in free)
        rows = q._query(
            f"SELECT {flag_cols}, COUNT(DISTINCT year) AS yc "
            f"FROM {mart[0]} WHERE {where} GROUP BY ALL",
            params,
        )
        if len({r["yc"] for r in rows}) > 1:
            non_degenerate.append(case["id"])

    assert non_degenerate, (
        "every mart_trend/mart_breakdown/offender_foreign_share case sits on a "
        "mart where every is_total combination has identical year coverage, so "
        "none of them can pin the probe's decision; add a case on a mart where "
        "the combinations actually differ (see mart_offenders)"
    )


def test_committed_expected_matches_the_generator():
    """Regenerating must be a no-op unless the data or a query changed."""
    assert (SHARED / "expected.json").read_text() == gen.build()


def test_expected_records_the_snapshot_fingerprint():
    """Expected output is only meaningful against the data it was generated from."""
    from italy_dashboard import queries as q

    recorded = json.loads((SHARED / "expected.json").read_text())["fingerprint"]
    assert recorded == gen.fingerprint_digest(q._snapshot_fingerprint())
