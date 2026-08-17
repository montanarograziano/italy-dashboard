"""EN/IT key parity.

`i18n.t()` evaluates BOTH `EN[key]` and `IT[key]` eagerly to build its
`rx.cond` (Python must evaluate both call arguments before `rx.cond(...)`
itself runs), so a plain `t(key)` with a missing IT entry raises the moment a
page is built — already caught by
`tests/integration/test_app_pages.py::test_page_component_builds`.

A `_format_translation`/`_coverage_text` lookup inside an `@rx.var`
(state.py), though, is NOT invoked while a page is being built: Reflex only
evaluates a computed var when it actually needs the value, which for these
plain-Python-value backend vars can be well after `climate_page()` returns
successfully. A missing key there slips past every render-tree test and only
raises once a real session actually renders that state. This test closes the
gap at the dictionary level, independent of how a key happens to be consumed.
"""

from __future__ import annotations

from italy_dashboard.translations import EN, IT


def test_every_en_key_has_an_it_counterpart():
    missing_in_it = set(EN) - set(IT)
    assert not missing_in_it, f"EN keys with no IT translation: {sorted(missing_in_it)}"


def test_every_it_key_has_an_en_counterpart():
    missing_in_en = set(IT) - set(EN)
    assert not missing_in_en, f"IT keys with no EN translation: {sorted(missing_in_en)}"


def test_en_and_it_have_the_same_key_count():
    assert len(EN) == len(IT)
