"""Unit tests for the `has_loaded` three-state guard (see components.data_gate).

`load()` sets `has_loaded = True` at its very END, regardless of whether the
page's own data turned out to be ready — that is the guarantee that lets a
page show a neutral placeholder while `has_loaded` is still False, and only
ever show the "no data" callout once loading has genuinely finished. These
tests instantiate a state directly (Reflex's `_reflex_internal_init=True`,
its own supported way to build a state object outside of a live app/session)
and call `load()` as a plain method, then check the flag by hand.

`has_loaded` is deliberately declared on each CONCRETE page state, not
inherited from `AppState` (see AppState's docstring in state.py): Reflex
resolves an inherited field by writing through to `self.parent_state`, which
is `None` for a standalone instance built this way, so testing an inherited
flag this way would raise/silently misbehave. A field declared directly on
the instantiated class has no such indirection, which is exactly why these
tests can observe it reliably.
"""

from __future__ import annotations

from italy_dashboard.state import (
    ClimateCrimeState,
    ClimateState,
    CrimeState,
    EconomyState,
    HomeState,
    LaborState,
    OffendersState,
    PopulationState,
)

# Every state that has a `load()`, paired with whether it also has its own
# `mart_ready`-style flag (checked below whenever the fixture makes that mart
# absent, to prove `has_loaded` doesn't merely track "succeeded").
ALL_LOAD_STATES = [
    HomeState,
    CrimeState,
    OffendersState,
    PopulationState,
    LaborState,
    EconomyState,
    ClimateState,
    ClimateCrimeState,
]


def test_has_loaded_starts_false_before_load_runs():
    for cls in ALL_LOAD_STATES:
        instance = cls(_reflex_internal_init=True)  # pyrefly: ignore[unexpected-keyword]
        assert instance.has_loaded is False, f"{cls.__name__} should default to not-loaded"


def test_has_loaded_is_true_after_load_when_data_is_ready(sample_db):
    for cls in ALL_LOAD_STATES:
        instance = cls(_reflex_internal_init=True)  # pyrefly: ignore[unexpected-keyword]
        instance.load()
        assert instance.has_loaded is True, f"{cls.__name__}.load() must set has_loaded"


def test_has_loaded_is_true_after_load_even_when_the_mart_is_missing(sample_db):
    """The regression this guard exists for: on a state with its own
    `mart_ready` flag, `sample_db` alone (no crime/offenders/climate marts
    built) makes `mart_ready` end up False. `has_loaded` must STILL flip to
    True — "loaded, but empty" is a real, distinct state from "not loaded
    yet", and only `has_loaded` can tell them apart (see the module docstring
    and `components.data_gate`).
    """
    mart_backed = [CrimeState, OffendersState, ClimateState, ClimateCrimeState]
    for cls in mart_backed:
        instance = cls(_reflex_internal_init=True)  # pyrefly: ignore[unexpected-keyword]
        instance.load()
        assert instance.mart_ready is False, f"{cls.__name__}: fixture has no mart to be ready"
        assert instance.has_loaded is True, (
            f"{cls.__name__}: has_loaded must be True even when mart_ready is False"
        )


def test_has_loaded_is_true_after_load_with_no_snapshot_at_all(missing_db):
    for cls in ALL_LOAD_STATES:
        instance = cls(_reflex_internal_init=True)  # pyrefly: ignore[unexpected-keyword]
        instance.load()
        assert instance.has_loaded is True, f"{cls.__name__}.load() must set has_loaded"
