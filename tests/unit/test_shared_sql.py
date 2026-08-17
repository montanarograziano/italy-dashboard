"""The shared SQL contract.

These files are read by BOTH the Python app and the TypeScript static app, so
they carry rules neither side can enforce alone: positional parameters only,
and no file may be orphaned by falling out of use on one side.
"""

from __future__ import annotations

import re

import pytest

from italy_dashboard import queries as q

EXPECTED_QUERIES = {
    "climate_distribution",
    "climate_distribution_windows",
    "crime_climate_scatter",
    "crime_climate_stats",
    "income_correlations",
    "income_scatter",
    "income_years",
    "inflation_series",
}

WEB_SRC = q.PROJECT_ROOT / "web" / "src"

# Shared queries with no TypeScript consumer YET. Plan 1 ports four functions by
# design, so this is expected -- but it has to be written down, because the
# alternative (a "both sides reference every file" check that only ever looked
# at Python) is documentation asserting a guarantee that does not exist.
#
# RATCHET: this set may only shrink. `test_no_shared_query_is_orphaned_on_the_
# typescript_side` fails if a name listed here HAS gained a TS consumer, so
# porting a query forces the entry out; and a new file that neither side
# consumes cannot be parked here without a deliberate edit.
NOT_YET_CONSUMED_BY_TS = {
    "climate_distribution",
    "climate_distribution_windows",
    "crime_climate_scatter",
    "crime_climate_stats",
    "income_correlations",
}


def _sql_files() -> dict[str, str]:
    return {p.stem: p.read_text() for p in q.SHARED_SQL_DIR.glob("*.sql")}


def test_every_expected_query_has_a_file():
    assert set(_sql_files()) == EXPECTED_QUERIES


def test_load_sql_returns_the_file_contents():
    assert "FROM economy_inflation" in q.load_sql("inflation_series")


def test_load_sql_rejects_an_unknown_name():
    with pytest.raises(FileNotFoundError):
        q.load_sql("no_such_query")


@pytest.mark.parametrize("name", sorted(EXPECTED_QUERIES))
def test_no_named_parameters(name: str):
    """DuckDB-WASM and the Python client agree on positional `?` only.

    A named parameter would work on one side and fail on the other, which is
    exactly the class of divergence this shared directory exists to prevent.
    """
    sql = _sql_files()[name]
    assert not re.search(r"[:$]\w+", sql), f"{name} looks like it uses a named parameter"


@pytest.mark.parametrize("name", sorted(EXPECTED_QUERIES))
def test_header_comment_documents_the_parameters(name: str):
    """Positional parameters are unreadable without documentation."""
    sql = _sql_files()[name]
    header = "\n".join(line for line in sql.splitlines() if line.strip().startswith("--"))
    assert header.strip(), f"{name} has no header comment"
    placeholders = sql.count("?")
    if placeholders:
        assert "param" in header.lower(), (
            f"{name} takes {placeholders} positional parameters but its header "
            "does not describe them"
        )


@pytest.mark.parametrize("name", sorted(EXPECTED_QUERIES))
def test_python_still_references_every_file(name: str):
    """An orphaned .sql file is dead weight that silently rots."""
    source = (q.PROJECT_ROOT / "italy_dashboard" / "queries.py").read_text()
    assert f'load_sql("{name}")' in source, f"queries.py no longer loads {name}"


def _typescript_imports() -> set[str]:
    """Shared query stems imported anywhere under `web/src` (Vite `?raw`)."""
    imported: set[str] = set()
    for source in WEB_SRC.rglob("*.ts"):
        imported.update(re.findall(r"shared/queries/(\w+)\.sql", source.read_text()))
    return imported


def test_no_shared_query_is_orphaned_on_the_typescript_side():
    """The other half of rule 3 in `shared/queries/README.md`.

    Only the Python side was ever checked, while the README and the design doc
    both stated the rule for BOTH sides -- so a plan-2 developer would have
    trusted a check that did not exist, on the side that has five of the eight
    files unconsumed.

    Three properties, and the exemption list is what makes the claim true rather
    than aspirational: every TS import names a real shared file, every file is
    either consumed by TS or explicitly listed as not yet, and nothing listed as
    not-yet is actually consumed (which is the ratchet -- porting a query fails
    this until its entry is removed).
    """
    imported = _typescript_imports()

    unknown = imported - EXPECTED_QUERIES
    assert not unknown, f"web/src imports shared queries that do not exist: {sorted(unknown)}"

    stale = imported & NOT_YET_CONSUMED_BY_TS
    assert not stale, (
        f"{sorted(stale)} now HAVE a TypeScript consumer; remove them from "
        "NOT_YET_CONSUMED_BY_TS so the set keeps shrinking"
    )

    unaccounted = EXPECTED_QUERIES - imported - NOT_YET_CONSUMED_BY_TS
    assert not unaccounted, (
        f"{sorted(unaccounted)} are referenced by neither side's code nor listed "
        "in NOT_YET_CONSUMED_BY_TS; port them, delete them, or record why they wait"
    )
