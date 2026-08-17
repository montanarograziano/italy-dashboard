"""The "no data" callouts must be gone from the DOM once a page has loaded.

This is the browser-side companion to the render-tree tests in
tests/unit/test_components.py (`data_gate`'s three states): those prove the
STRUCTURE is right (a `has_loaded` cond wraps the `mart_ready`/`data_ready`
one), which is as far as a Python-side render-tree assertion can reach —
`rx.cond`'s `render()` always embeds BOTH branches (see that test module's
own comment), so it cannot see which one a real browser actually mounts.
This test drives a real, locally running app with real synthetic data (see
`app_server` / `_ensure_sample_data` in conftest.py) and checks what
actually ends up in the DOM after loading: neither the generic "no data
snapshot" banner (`components.no_data_callout`, driven by `data_ready`) nor
the climate-specific one (`pages/climate.py`, driven by `mart_ready`) should
still be there, because both are genuinely True by then.
"""

from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

# Default (`en`) callout texts (italy_dashboard/translations.py's `no_data`
# and `no_climate` keys) — short, distinctive prefixes rather than the full
# strings, so the assertion doesn't depend on exact whitespace.
_NO_DATA_TEXT = "No data snapshot found"
_NO_CLIMATE_TEXT = "No temperature data yet"

# Default `t()` heading for a chart card that only renders once ClimateState's
# `load()` has actually finished with `mart_ready=True` (see `data_gate` /
# `pages/climate.py`); waiting for it is how this test knows loading is done
# without a fixed sleep.
_WARMING_HEADING = "Annual temperature"


def test_no_data_callout_is_absent_once_the_page_has_loaded(page, app_server):
    page.goto(f"{app_server}/climate")

    # Real chart content appears only once has_loaded AND mart_ready are both
    # True: waiting for it is the signal that `ClimateState.load()` is done.
    page.get_by_text(_WARMING_HEADING).wait_for(state="visible")

    assert page.get_by_text(_NO_DATA_TEXT).count() == 0, (
        "the generic 'no data snapshot' callout is still in the DOM after the page loaded"
    )
    assert page.get_by_text(_NO_CLIMATE_TEXT).count() == 0, (
        "the climate-specific 'no data' callout is still in the DOM after the page loaded"
    )
