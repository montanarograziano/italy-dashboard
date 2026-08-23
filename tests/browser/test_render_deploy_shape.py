"""Regression test for the Render/Caddy hydration bug (P1, live QA report).

`Caddyfile`'s `try_files {path} /index.html` used to silently serve HOME's
prerendered HTML for a direct/full-page load of ANY other route (`/crime`,
`/climate`, ...): `{path}` alone never matches Reflex's exported files
(`<route>.html` / `<route>/index.html`, never a bare extension-less name), so
every route but `/` fell straight to the `/index.html` last resort with a
200. React Router then hydrated against the real URL, rendered that route's
actual page client-side, and could not reconcile it with the home markup the
server had actually sent -- a guaranteed, on-every-load React error #418
(hydration mismatch), confirmed live and reproduced locally against this
exact exported build + this exact `Caddyfile` while diagnosing the fix (see
`conftest.py`'s `render_deploy_shape` fixture for the full mechanism this
test guards against).

Deliberately does NOT use `app_server` (every other browser test's usual
Reflex fixture): that fixture runs `reflex run --env prod`, one integrated
process serving both halves together, which never exercises `Caddyfile` at
all and could not have caught this.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.browser

ROUTES = [
    "/",
    "/crime",
    "/population",
    "/education",
    "/climate",
    "/climate-crime",
    "/labor",
    "/economy",
]


def test_every_route_hydrates_without_a_react_error(page, render_deploy_shape):
    """A fresh, full-page load of every route must reach its OWN prerendered
    markup and hydrate clean -- no React error of any kind, #418 included.

    One listener for the whole test, `errors` cleared before each
    navigation: registering a fresh `lambda` per iteration and later trying
    to `remove_listener` the ORIGINAL `errors.append` (a different, never-
    registered callable) would silently fail to detach anything, leaking one
    stale listener per route for the rest of the test.
    """
    errors: list[str] = []

    def _record(exc: object) -> None:
        errors.append(str(exc))

    page.on("pageerror", _record)
    try:
        for route in ROUTES:
            errors.clear()
            # A real navigation each time (not a client-side link click):
            # exactly the "cold load of one route" shape the live report
            # reproduced, and the only way to force Caddy to resolve
            # `{path}` from scratch rather than letting an already-hydrated
            # React Router handle the transition client-side.
            page.goto(f"{render_deploy_shape}{route}", wait_until="networkidle")
            page.wait_for_timeout(500)
            assert not errors, f"{route}: {errors}"
    finally:
        page.remove_listener("pageerror", _record)


def test_a_direct_route_load_serves_its_own_page_not_homes(page, render_deploy_shape):
    """The concrete content-level check behind the hydration fix: a direct
    load of a non-home route must actually render THAT route's heading, not
    silently fall back to home's markup with the URL merely looking right.
    """
    page.goto(f"{render_deploy_shape}/crime", wait_until="networkidle")
    page.wait_for_selector("main h1, h1:has-text('Crime')", timeout=15_000)
    headings = page.eval_on_selector_all("h1", "els => els.map(e => e.textContent)")
    assert "Crime" in headings, headings
    assert "Italy at a glance" not in headings, headings


def test_an_unknown_route_falls_back_to_the_branded_not_found_page(page, render_deploy_shape):
    """A genuinely unmatched path must reach the app shell's 404 page (see
    `italy_dashboard/pages/not_found.py`), not home's content and not a
    bare unstyled string with no header/nav.
    """
    page.goto(f"{render_deploy_shape}/this-route-does-not-exist", wait_until="networkidle")
    page.wait_for_selector("text=Page not found", timeout=15_000)
    # The branded shell (navbar.py's heading), not the bare framework default.
    assert page.locator("text=Italy Dashboard").count() > 0
