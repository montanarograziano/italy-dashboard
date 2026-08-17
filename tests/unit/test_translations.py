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

import string

from italy_dashboard.translations import EN, IT


def test_every_en_key_has_an_it_counterpart():
    missing_in_it = set(EN) - set(IT)
    assert not missing_in_it, f"EN keys with no IT translation: {sorted(missing_in_it)}"


def test_every_it_key_has_an_en_counterpart():
    missing_in_en = set(IT) - set(EN)
    assert not missing_in_en, f"IT keys with no EN translation: {sorted(missing_in_en)}"


def test_en_and_it_have_the_same_key_count():
    assert len(EN) == len(IT)


def _placeholder_fields(template: str) -> set[str]:
    """Field names a `str.format` template references, e.g. `{city}` -> `"city"`.

    `string.Formatter().parse` is used rather than a regex: a regex would
    trip over doubled braces (an escaped literal `{{`/`}}`, which parse() folds
    into plain text with no field name) and over format specs (the `.2f` in
    `{value:.2f}`, which parse() already separates out).
    """
    return {
        field_name
        for _, field_name, _, _ in string.Formatter().parse(template)
        if field_name  # None (no substitution) and "" (positional {}) excluded
    }


def test_placeholder_fields_match_between_en_and_it():
    """Key parity (above) does not catch a renamed placeholder: EN and IT are
    separate strings, so `{city}` on one side and `{citta}` on the other is
    two dicts with identical keys and completely silent to every test above.
    It only surfaces as `_format_translation`'s `str.format(**values)` raising
    KeyError for whichever language doesn't have the field the caller passed
    (see state.py), at runtime, for Italian users only if EN happens to get
    exercised in tests and IT does not.
    """
    for key in sorted(set(EN) & set(IT)):
        en_fields = _placeholder_fields(EN[key])
        it_fields = _placeholder_fields(IT[key])
        assert en_fields == it_fields, (
            f"{key!r}: EN placeholders {sorted(en_fields)} != IT placeholders {sorted(it_fields)}"
        )
