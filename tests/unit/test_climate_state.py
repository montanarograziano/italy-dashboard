"""ClimateState's three-scope cascade (Italia -> region -> city) and the
cross-city highlight it drives.

Instantiates ClimateState directly (`_reflex_internal_init=True`, Reflex's
own supported way to build a state outside a live session — see test_state.py
for the same pattern and why it works here but not for an AppState-inherited
field) and calls its event handlers as plain methods.
"""

from __future__ import annotations

from italy_dashboard import queries as q
from italy_dashboard.state import ClimateState, _format_translation


def _fresh() -> ClimateState:
    return ClimateState(_reflex_internal_init=True)  # pyrefly: ignore[unexpected-keyword]


def test_default_scope_is_italia_the_broadest_level(climate_db):
    state = _fresh()
    state.load()
    assert state.region == q.ITALIA
    assert state.city == q.ALL


def test_mart_ready_is_false_without_the_region_mart(annual_only_climate_mart):
    """The scenario ClimateState.mart_ready's comment describes: an older
    snapshot with mart_climate_annual but no mart_climate_region. Before this
    gate existed, `mart_ready` would have been True here (climate_ready()
    alone only checks the annual mart), region_options would collapse to
    just ["Italia"], and every "Selected scope" card would query a table
    that does not exist and render empty with no callout to explain why.
    """
    assert q.climate_ready() is True
    assert q.climate_region_ready() is False

    state = _fresh()
    state.load()
    assert state.mart_ready is False


def test_region_options_and_city_options_are_populated_on_load(climate_db):
    state = _fresh()
    state.load()
    assert state.region_options[0] == q.ITALIA
    assert "Piemonte" in state.region_options
    # Default region is Italia, so city_options must list every city.
    assert state.city_options[0] == q.ALL
    assert len(state.city_options) == 1 + len(q.climate_cities())


def test_set_region_cascades_city_options_and_resets_city(climate_db):
    state = _fresh()
    state.load()
    state.set_city("Torino")
    assert state.city == "Torino"

    state.set_region("Piemonte")
    assert state.region == "Piemonte"
    assert state.city == q.ALL, "changing region must broaden back out, not keep a stale city"
    assert state.city_options == [q.ALL, "Cuneo", "Torino"]


def test_set_city_narrows_to_city_scope(climate_db):
    state = _fresh()
    state.load()
    state.set_city("Torino")
    assert state.city == "Torino"
    assert state.annual == q.climate_annual_series("Torino")
    assert state.stripes == q.climate_stripes("Torino")
    assert state.thresholds == q.climate_threshold_days("Torino")


def test_region_scope_uses_the_region_query_functions(climate_db):
    state = _fresh()
    state.load()
    state.set_region("Piemonte")
    assert state.city == q.ALL
    assert state.annual == q.climate_region_annual_series("Piemonte")
    assert state.stripes == q.climate_region_stripes("Piemonte")
    assert state.thresholds == q.climate_region_threshold_days("Piemonte")


def test_italia_scope_uses_the_region_query_functions_with_italia(climate_db):
    state = _fresh()
    state.load()
    assert state.region == q.ITALIA
    assert state.city == q.ALL
    assert state.annual == q.climate_region_annual_series(q.ITALIA)
    assert state.stripes == q.climate_region_stripes(q.ITALIA)
    assert state.thresholds == q.climate_region_threshold_days(q.ITALIA)


def test_distribution_is_the_existing_empty_state_at_region_and_italia_scope(climate_db):
    """mart_climate_region has no daily rows (see queries.climate_distribution's
    docstring): region/Italia scope must show the SAME empty state a city with
    too short a record already gets, not a crash or invented data.
    """
    state = _fresh()
    state.load()
    assert state.distribution == []
    assert state.dist_early_lo == "—"
    assert state.dist_early_hi == "—"
    assert state.dist_late_lo == "—"
    assert state.dist_late_hi == "—"

    state.set_region("Piemonte")
    assert state.distribution == []
    assert state.dist_early_lo == "—"


def test_distribution_is_populated_at_city_scope(climate_db):
    state = _fresh()
    state.load()
    state.set_city("Torino")
    assert state.distribution == q.climate_distribution("Torino")


def test_is_city_scope_tracks_whether_a_city_is_selected(climate_db):
    state = _fresh()
    state.load()
    assert state.is_city_scope is False  # default: Italia

    state.set_region("Piemonte")
    assert state.is_city_scope is False  # a region, still not a city

    state.set_city("Torino")
    assert state.is_city_scope is True

    state.set_region("Piemonte")  # region change resets city to q.ALL
    assert state.is_city_scope is False


def test_is_national_scope_is_true_only_for_the_italia_aggregate(climate_db):
    """The Italia average is an unweighted mean of whichever capitals the
    backfill has reached, which it reaches in province-code order (from the
    north), so it carries a composition caveat no other scope does — and it is
    the DEFAULT scope, so that caveat is on the landing view. See
    `climate_coverage_note` in translations.py and its `rx.cond` in the page.
    """
    state = _fresh()
    state.load()
    assert state.is_national_scope is True  # default

    state.set_region("Piemonte")
    assert state.is_national_scope is False

    state.set_region(q.ITALIA)
    state.set_city("Torino")  # a single city, even under Italia, is not the mean
    assert state.is_national_scope is False

    state.set_region(q.ITALIA)  # resets city to q.ALL
    assert state.is_national_scope is True


def test_partial_national_scope_is_false_once_coverage_is_complete(climate_db):
    """The composition caveat must disappear once the backfill completes.

    `is_national_scope` stays true for Italia, but `is_partial_national_scope`
    must become false when every capital is covered — otherwise the default
    view keeps claiming "much of the South is still missing" about a fully
    covered country. This is the behavioural half of the gate the page's
    `rx.cond` uses (test_the_climate_page_carries_the_national_coverage_note
    asserts the wiring; this asserts the state logic).
    """
    state = _fresh()
    state.load()
    assert state.capitals_included == "20"  # the synthetic climate_db covers 20 of 106
    assert state.is_partial_national_scope is True

    # Simulate a complete backfill: every capital present.
    state.capitals_included = state.capitals_total
    assert state.is_partial_national_scope is False

    # A partial region or city scope is never the national note's concern.
    state.capitals_included = "20"
    state.set_region("Piemonte")
    assert state.is_partial_national_scope is False


def test_the_climate_page_carries_the_national_coverage_note():
    """The state var is only half of it: the note has to reach the page, in
    both languages, gated on that var. Asserted on the rendered tree rather
    than by reading the source, so a `t()` that silently resolved to nothing
    or a caveat wired to the wrong condition would show up here.
    """
    from italy_dashboard.pages.climate import climate_page
    from italy_dashboard.translations import EN, IT

    # Distinctive fragments rather than the whole sentence: `render()` returns
    # a repr in which apostrophes come back escaped. Each fragment is asserted
    # to still BE part of its translation, so rewording the note cannot quietly
    # turn this into a check of nothing.
    en_marker = "unweighted mean of the capitals covered so far"
    it_marker = "media non ponderata dei capoluoghi finora coperti"
    assert en_marker in EN["climate_coverage_note"]
    assert it_marker in IT["climate_coverage_note"]

    rendered = str(climate_page().render())
    assert en_marker in rendered
    assert it_marker in rendered
    # Gated on the PARTIAL-coverage flag, not the bare national-scope flag:
    # once the backfill completes, the note's "much of the South is still
    # missing" is false and must not be rendered about a fully-covered Italy.
    assert "is_partial_national_scope" in rendered


# --------------------------------------------------------- highlighted_city
#
# The cross-city ranking/grid must acknowledge the selection ONLY when a
# single city is what's selected — region and Italia scope select many
# cities at once, so nothing should be singled out there.


# ----------------------------------------------- city_outside_ranking_note
#
# `climate_stripes_grid`'s top 12 is a strict subset of `ranking`'s top 20
# (both order by the same warming rate), so a city outside the ranking
# entirely gets NO visual acknowledgement anywhere on the page — neither the
# ranking's outline nor the grid's ring. These tests set `ranking` directly
# (a plain state field) rather than going through a real query, since the
# 20-capital synthetic snapshot puts every one of its cities inside a top-20
# ranking by construction and could never exercise the "absent" branch.


def test_city_outside_ranking_note_is_empty_when_the_city_is_in_the_ranking():
    state = _fresh()
    state.ranking = [{"name": "Torino", "value": 0.5}, {"name": "Milano", "value": 0.4}]
    state.city = "Torino"
    assert state.city_outside_ranking_note == ""


def test_city_outside_ranking_note_names_the_city_when_absent():
    state = _fresh()
    state.ranking = [{"name": "Torino", "value": 0.5}, {"name": "Milano", "value": 0.4}]
    state.city = "Palermo"
    assert state.city_outside_ranking_note == (
        "Palermo is not among the top 20 fastest-warming cities, so it isn't highlighted below."
    )


def test_city_outside_ranking_note_is_empty_at_region_and_italia_scope():
    """Not a city selection at all: this note must stay silent, distinct
    from the "in the ranking" case above, even though both return "".
    """
    state = _fresh()
    state.ranking = [{"name": "Torino", "value": 0.5}]
    state.city = q.ALL
    assert state.city_outside_ranking_note == ""


def test_highlighted_city_is_the_city_at_city_scope(climate_db):
    state = _fresh()
    state.load()
    state.set_city("Torino")
    assert state.highlighted_city == "Torino"


def test_highlighted_city_is_empty_at_region_scope(climate_db):
    state = _fresh()
    state.load()
    state.set_region("Piemonte")
    assert state.city == q.ALL
    assert state.highlighted_city == ""


def test_highlighted_city_is_empty_at_italia_scope(climate_db):
    state = _fresh()
    state.load()
    assert state.region == q.ITALIA
    assert state.city == q.ALL
    assert state.highlighted_city == ""


def test_selected_scope_title_names_the_active_entity(climate_db):
    """`lang` is inherited from AppState (see AppState's own docstring), so a
    standalone instance built with `_reflex_internal_init=True` has no
    `parent_state` to write it through — the same limitation test_state.py's
    module docstring documents for `has_loaded`. The IT template is exercised
    directly through `_format_translation` instead, which is exactly the
    function `selected_scope_title` itself calls.
    """
    state = _fresh()
    state.load()
    assert state.selected_scope_title == "Selected scope: Italia"

    state.set_region("Piemonte")
    assert state.selected_scope_title == "Selected scope: Piemonte"

    state.set_city("Torino")
    assert state.selected_scope_title == "Selected scope: Torino"

    assert (
        _format_translation("it", "selected_scope_title", name="Torino")
        == "Ambito selezionato: Torino"
    )
