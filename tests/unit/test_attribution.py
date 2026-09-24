"""The in-app attribution footer: CC BY 4.0 / IODL 2.0 credit on every page.

Both frontends read the provider list from shared/attribution.json, so these
tests pin the file itself (every link is one the docs already vouch for, no
invented license), the Reflex render tree, and the static app's IT strings
against translations.py.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import reflex as rx

from italy_dashboard import components as c
from italy_dashboard.translations import EN, IT

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASETS_DOC = REPO_ROOT / "docs" / "04-datasets.md"
WEB_I18N = REPO_ROOT / "web" / "src" / "i18n.tsx"
FOOTER_KEYS = ("footer_sources", "footer_license_undocumented", "footer_modified")


def _render(component: rx.Component) -> str:
    return str(component.render())


def _shows(rendered: str, text: str) -> bool:
    """Whether `text` appears as a string literal in a rendered tree.

    Literals are JSON-encoded in the tree (`ciò` -> `ci\\u00f2`) and the tree's
    repr then escapes backslashes and apostrophes, so encode `text` the same way.
    """
    literal = json.dumps(text)[1:-1]
    return literal.replace("\\", "\\\\").replace("'", "\\'") in rendered


def test_every_footer_link_is_a_url_the_licensing_docs_already_cite():
    """No fabricated links: each license URL must appear in docs/04-datasets.md."""
    doc = DATASETS_DOC.read_text(encoding="utf-8")
    for provider in c.load_providers():
        if provider["url"] is not None:
            assert provider["url"] in doc, provider


def test_license_and_url_are_null_together_and_inps_has_no_license_asserted():
    providers = {p["name"]: p for p in c.load_providers()}
    for p in providers.values():
        assert (p["license"] is None) == (p["url"] is None), p
    # docs/04-datasets.md: INPS's license is "Not documented" -- flagged, not guessed.
    assert providers["INPS"]["license"] is None
    assert {"ISTAT", "MUR - Servizio Statistico", "Copernicus C3S ERA5-Land", "Open-Meteo"} <= set(
        providers
    )


def test_footer_renders_every_provider_and_license_link():
    rendered = _render(c.attribution_footer())
    assert '"footer"' in rendered
    for p in c.load_providers():
        assert p["name"] in rendered
        if p["url"] is not None:
            assert p["url"] in rendered
    for key in FOOTER_KEYS:
        assert _shows(rendered, EN[key]) and _shows(rendered, IT[key]), key


def test_every_page_shell_carries_the_footer():
    rendered = _render(c.shell(rx.text("x"), has_loaded=False))
    assert "Copernicus C3S ERA5-Land" in rendered
    assert _shows(rendered, EN["footer_modified"])


def test_static_app_footer_strings_match_the_reflex_translations():
    """The static app keys by the English literal; its IT value must be the
    same wording translations.py uses, so the two frontends never drift."""
    src = WEB_I18N.read_text(encoding="utf-8")
    for key in FOOTER_KEYS:
        entry = re.search(r'\s*"' + re.escape(EN[key]) + r'":\s*"((?:[^"\\]|\\.)*)"', src, re.S)
        assert entry, f"web/src/i18n.tsx has no IT entry for {EN[key]!r}"
        assert entry.group(1) == IT[key], key
