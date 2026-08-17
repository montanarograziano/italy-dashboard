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


def test_the_matrix_covers_the_dynamic_mart_engine():
    """_mart_where probes the data to choose an is_total flag combination.

    It is the single most likely thing to diverge in a reimplementation, so the
    matrix must exercise it through its public callers.
    """
    functions = {c["function"] for c in _cases()}
    assert {"mart_trend", "mart_breakdown", "mart_options"} <= functions


def test_committed_expected_matches_the_generator():
    """Regenerating must be a no-op unless the data or a query changed."""
    assert (SHARED / "expected.json").read_text() == gen.build()


def test_expected_records_the_snapshot_fingerprint():
    """Expected output is only meaningful against the data it was generated from."""
    from italy_dashboard import queries as q

    recorded = json.loads((SHARED / "expected.json").read_text())["fingerprint"]
    assert recorded == gen.fingerprint_digest(q._snapshot_fingerprint())
