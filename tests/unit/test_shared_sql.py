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
