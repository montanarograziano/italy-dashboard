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
