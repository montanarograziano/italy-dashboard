"""Integration tests: every Reflex page builds a component tree without errors.

This catches breakage from Reflex API changes (the framework moves fast) and
from renamed state vars, without needing a browser or a frontend build.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "module_name,page_fn",
    [
        ("italy_dashboard.pages.home", "home_page"),
        ("italy_dashboard.pages.crime", "crime_page"),
        ("italy_dashboard.pages.population", "population_page"),
        ("italy_dashboard.pages.labor", "labor_page"),
        ("italy_dashboard.pages.economy", "economy_page"),
    ],
)
def test_page_component_builds(module_name: str, page_fn: str):
    import importlib

    module = importlib.import_module(module_name)
    component = getattr(module, page_fn)()
    # Rendering to string forces prop validation across the whole tree.
    assert component.render()


def test_app_registers_all_routes():
    from italy_dashboard.italy_dashboard import app

    routes = set(app._unevaluated_pages)
    assert {"index", "crime", "population", "labor", "economy"} <= routes
