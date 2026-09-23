"""The attribution footer must actually paint on real pages of BOTH frontends.

tests/unit/test_attribution.py proves the Reflex render tree carries it; only
a browser can show it lands in the DOM of a routed page, with working license
links, and wraps at phone width instead of widening the page.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROVIDERS = json.loads((REPO_ROOT / "shared" / "attribution.json").read_text())["providers"]
LICENSED = [p for p in PROVIDERS if p["url"]]


def _assert_footer(page) -> None:
    footer = page.locator("footer")
    footer.wait_for(state="visible", timeout=30_000)
    text = footer.inner_text()
    for provider in PROVIDERS:
        assert provider["name"] in text, provider["name"]
    assert "license not documented" in text  # INPS: credited, no license asserted
    hrefs = footer.locator("a").evaluate_all("els => els.map(e => e.getAttribute('href'))")
    assert sorted(hrefs) == sorted(p["url"] for p in LICENSED), hrefs


@pytest.mark.parametrize("route", ["#/", "#/climate"])
def test_static_app_footer_renders(page, static_app, route):
    page.goto(f"{static_app}/{route}")
    page.wait_for_selector("main h1", timeout=30_000)
    _assert_footer(page)


def test_static_app_footer_wraps_at_phone_width(page, static_app):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{static_app}/#/climate")
    page.wait_for_selector("main h1", timeout=30_000)
    _assert_footer(page)
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= 0, f"page scrolls horizontally by {overflow}px at 390px"


@pytest.mark.parametrize("route", ["/", "/climate"])
def test_reflex_footer_renders(page, app_server, route):
    page.goto(f"{app_server}{route}")
    _assert_footer(page)
