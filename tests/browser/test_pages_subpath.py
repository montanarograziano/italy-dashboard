"""GitHub Pages serves a project site (this repo, with no custom domain --
see docs/12-deployment.md) under a `/italy-dashboard/` path prefix, not at
origin root. Every other browser test in this package (`test_static_app.py`,
`test_conformance.py`) exercises the app at root, via Vite dev or a root
`npm run build` -- none of them could have caught `registerParquetViews`
(`web/src/db.ts`) building parquet URLs off `window.location.origin` and
silently dropping any path prefix `base` had actually been given, which is
exactly the bug the GitHub Pages migration fixed (see that file's comment at
the parquet-URL line).

This module is the standing regression check for that fix, built and served
exactly as `.github/workflows/pages.yml` deploys: a real `vite build --base=
/italy-dashboard/`, served from under that same prefix with no SPA fallback
(`built_static_app_under_subpath`, tests/browser/conftest.py) -- so it is
also revalidating docs/12-deployment.md's "genuine 404" claim under the new
path prefix, not just under root the way `test_static_app.py`'s own version
of this check already does.
"""

from urllib.parse import urlsplit

import pytest

from tests.browser.test_static_app import _ROUTE_READY_SELECTORS

pytestmark = pytest.mark.browser

PATH_PREFIX = "/italy-dashboard/"


def test_every_route_loads_and_renders_under_the_pages_path_prefix(
    page, built_static_app_under_subpath
):
    """Walking all eight routes under `/italy-dashboard/` must reach the same
    real charts `test_static_app.py` already proves at root -- proof that
    hash routing (no server-side path ever changes, see router.tsx) needs no
    adjustment for a subpath host, and that the app's own asset/script tags
    (rewritten by Vite's `base` at build time) resolve correctly once served
    from under that prefix rather than from origin root.
    """
    for slug, ready_selector in _ROUTE_READY_SELECTORS.items():
        page.goto("about:blank")
        page.goto(f"{built_static_app_under_subpath}/#/{slug}")
        page.wait_for_selector(ready_selector, timeout=30_000)


def test_first_party_requests_resolve_under_the_path_prefix_not_site_root(
    page, built_static_app_under_subpath
):
    """The concrete regression this module exists to catch: every request
    this app makes to ITS OWN origin (the JS/CSS bundle, and every parquet
    file `registerParquetViews` registers) must carry the `/italy-dashboard/`
    prefix in its path. The pre-fix `db.ts` built parquet URLs off
    `window.location.origin` directly, which would have requested
    `{origin}/economy_inflation.parquet` here -- a same-origin 404 that
    `registerParquetViews`' own try/except would have silently swallowed as
    "dataset not available" for every single mart, not just the one
    genuinely excluded (see the second test below), which is exactly why
    that failure mode needed a dedicated regression test rather than relying
    on "the page loaded" alone.

    DuckDB-WASM's own worker/wasm/parquet-extension fetches from jsDelivr are
    a different, cross-origin origin entirely and are correctly EXEMPT from
    this check -- they never carried a same-origin path prefix, on Netlify,
    Render, or here.
    """
    first_party_paths: list[str] = []

    def record(response) -> None:
        parts = urlsplit(response.url)
        if parts.netloc == urlsplit(built_static_app_under_subpath).netloc:
            first_party_paths.append(parts.path)

    page.on("response", record)
    try:
        page.goto(f"{built_static_app_under_subpath}/#/climate")
        page.wait_for_selector(
            _ROUTE_READY_SELECTORS["climate"],
            timeout=30_000,
        )
    finally:
        page.remove_listener("response", record)

    assert first_party_paths, "no same-origin requests observed at all"
    parquet_paths = [p for p in first_party_paths if p.endswith(".parquet")]
    assert parquet_paths, "expected at least one parquet request on the climate route"
    offenders = [p for p in first_party_paths if not p.startswith(PATH_PREFIX)]
    assert not offenders, (
        f"same-origin request(s) resolved OUTSIDE the {PATH_PREFIX} path prefix, "
        f"meaning some URL was built off window.location.origin directly rather than "
        f"import.meta.env.BASE_URL: {offenders}\n(all first-party paths seen: {first_party_paths})"
    )


def test_the_excluded_mart_still_genuinely_404s_under_the_path_prefix(
    page, built_static_app_under_subpath
):
    """`marts/mart_climate_daily.parquet` must still 404 -- not fall back to
    a `200 index.html` -- once the request URL itself carries the new path
    prefix. `test_static_app.py`'s equivalent check proves this at root;
    this is the same invariant at the deploy shape that will actually be
    live, since the plain-server-with-no-fallback shape both fixtures share
    is what makes either check meaningful (see `built_static_app`'s
    docstring in conftest.py).
    """
    bad_responses: list[tuple[int, str]] = []

    def record(response) -> None:
        if response.status >= 400:
            bad_responses.append((response.status, response.url))

    page.on("response", record)
    try:
        page.goto(f"{built_static_app_under_subpath}/#/climate")
        page.wait_for_selector(
            _ROUTE_READY_SELECTORS["climate"],
            timeout=30_000,
        )
    finally:
        page.remove_listener("response", record)

    unexpected = [
        (status, url) for status, url in bad_responses if "mart_climate_daily.parquet" not in url
    ]
    assert not unexpected, f"unexpected non-2xx response(s): {unexpected}"
    daily_mart_urls = [url for _, url in bad_responses if "mart_climate_daily.parquet" in url]
    assert daily_mart_urls, "expected marts/mart_climate_daily.parquet to 404; it did not appear"
    assert all(
        f"{PATH_PREFIX}marts/mart_climate_daily.parquet" in url for url in daily_mart_urls
    ), (
        f"the excluded mart's 404 must itself be requested under the {PATH_PREFIX} prefix: "
        f"{daily_mart_urls}"
    )
