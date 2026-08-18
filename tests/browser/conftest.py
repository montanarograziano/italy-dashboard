"""Fixtures for browser-rendering tests: boot the real app once, in a real
Chromium, and hand every test a base URL.

This is the one class of defect the rest of the test suite structurally
cannot see. Every chart test elsewhere in this repo asserts on Reflex's
render TREE (the Python-side component graph), never on what a browser
actually paints. A real defect shipped through exactly that gap: every axis
passed its tick colour via `custom_attrs={"fill": ...}`, but recharts builds
each tick label's props as `{...axisProps, fill: stroke}`, so the axis LINE
colour always won over the intended `fill`. Dark mode shipped axis labels at
1.60:1 contrast (see `italy_dashboard/components.py::_tick_style`), and every
render-tree test passed the whole time because the tree looked exactly as
intended — the prop was there, just never applied the way recharts uses it.

Nothing here runs by default: these tests need the `browser` extra
(`uv sync --extra browser`), a Chromium binary (`uv run playwright install
chromium`), and the `browser` pytest marker, which `addopts` deselects by
default so `just check` stays fast.
"""

from __future__ import annotations

import contextlib
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from threading import Thread

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Reflex's dev server (`reflex run`) hot-reloads via Vite and lazily compiles
# routes on first navigation, which makes first-hit timing and console noise
# (HMR websocket reconnects) unpredictable — exactly the kind of flakiness a
# style-assertion test can't afford. `--env prod` instead compiles the whole
# frontend ONCE up front (slower to first byte) and then serves a fixed,
# already-built bundle: slower to start, but deterministic afterwards, and
# closer to what actually ships. It also always serves frontend and backend
# on the SAME port (verified in reflex.reflex._run: for env=PROD it forces
# `frontend_port == backend_port` before this module ever gets a URL), so the
# fixture only has to pick and track one port.
_STARTUP_TIMEOUT_S = 300
_POLL_INTERVAL_S = 1.0
_SHUTDOWN_TIMEOUT_S = 15


def _free_port() -> int:
    """A port nothing is listening on right now.

    Never hardcode 3000: that's the port a developer's own `reflex run` dev
    server is commonly already using, and colliding with it would make this
    fixture flakily attach to (or fight with) someone else's running app
    instead of the one it just started.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _ensure_sample_data() -> None:
    """Make sure the climate marts this suite reads exist, generating them if not.

    The dashboard's query layer (`italy_dashboard/queries.py`) reads a fixed
    `<repo>/data` directory with no override hook, so the subprocess started
    below reads whatever is really on disk in this checkout. In an existing
    dev checkout that's already `just sample` + `just transform`. In a fresh
    clone (or CI) it isn't, so this mirrors those two recipes idempotently
    rather than requiring a manual setup step before `just test-browser` works.
    """
    marker = REPO_ROOT / "data" / "marts" / "mart_climate_annual.parquet"
    if marker.exists():
        return
    subprocess.run(
        ["uv", "run", "python", "-m", "ingestion.fetch", "sample"],
        cwd=REPO_ROOT,
        check=True,
    )
    (REPO_ROOT / "data" / "marts").mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["uv", "run", "dbt", "build", "--project-dir", "dbt", "--profiles-dir", "dbt"],
        cwd=REPO_ROOT,
        check=True,
    )


def _drain_output(proc: subprocess.Popen[str], sink: list[str]) -> None:
    """Continuously read the subprocess's combined stdout/stderr.

    Not just for the failure message: an unread pipe fills its OS buffer and
    then blocks the child process's writes, which would hang `reflex run`
    outright rather than merely making its output unavailable.
    """
    assert proc.stdout is not None
    for line in proc.stdout:
        sink.append(line)


def _wait_until_serving(
    proc: subprocess.Popen[str], base_url: str, output: list[str], label: str = "`reflex run`"
) -> None:
    deadline = time.monotonic() + _STARTUP_TIMEOUT_S
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"{label} exited early (code {proc.returncode}) before serving "
                f"{base_url}.\n--- captured output ---\n{''.join(output)}"
            )
        try:
            with urllib.request.urlopen(base_url, timeout=2) as response:
                if response.status < 500:
                    return
        except urllib.error.HTTPError as exc:
            # HTTPError IS a URLError (caught below too), but urlopen raises it
            # -- rather than returning it as `response` -- for any non-2xx/3xx
            # status, including a plain 404. Left uncaught here, a 404 (e.g.
            # Vite serving its root with no index.html yet) would fall into
            # the generic branch below and retry for the full timeout even
            # though the server answered; a real "not up yet" case (connection
            # refused) still lands there.
            if exc.code < 500:
                return
            last_error = exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last_error = exc
        time.sleep(_POLL_INTERVAL_S)
    raise TimeoutError(
        f"{label} never served {base_url} within {_STARTUP_TIMEOUT_S}s "
        f"(last connection error: {last_error!r}).\n"
        f"--- captured output (tail) ---\n{''.join(output)[-4000:]}"
    )


def _wait_until_reachable(base_url: str) -> None:
    """Poll an already-running server (no subprocess of our own to watch)."""
    deadline = time.monotonic() + _STARTUP_TIMEOUT_S
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(base_url, timeout=2) as response:
                if response.status < 500:
                    return
        except urllib.error.HTTPError as exc:  # see _wait_until_serving
            if exc.code < 500:
                return
            last_error = exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last_error = exc
        time.sleep(_POLL_INTERVAL_S)
    raise TimeoutError(
        f"{base_url} never became reachable within {_STARTUP_TIMEOUT_S}s "
        f"(last connection error: {last_error!r})"
    )


def _terminate(proc: subprocess.Popen[str]) -> None:
    """Kill the whole process group, not just the immediate child.

    `reflex run` in prod mode spawns its own backend/static-file worker as a
    child process; killing only `proc` would leave that worker (and its
    bound port) running after the test session ends.
    """
    if proc.poll() is not None:
        return
    pgid_killer = getattr(os, "killpg", None)
    if pgid_killer is not None:
        with contextlib.suppress(ProcessLookupError):
            pgid_killer(os.getpgid(proc.pid), signal.SIGTERM)
    else:  # pragma: no cover - non-POSIX fallback
        proc.terminate()
    try:
        proc.wait(timeout=_SHUTDOWN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        if pgid_killer is not None:
            with contextlib.suppress(ProcessLookupError):
                pgid_killer(os.getpgid(proc.pid), signal.SIGKILL)
        else:  # pragma: no cover - non-POSIX fallback
            proc.kill()
        proc.wait(timeout=_SHUTDOWN_TIMEOUT_S)


_CHROMIUM_PROBE = (
    "from playwright.sync_api import sync_playwright\n"
    "with sync_playwright() as p:\n"
    "    b = p.chromium.launch()\n"
    "    b.close()\n"
)


@pytest.fixture(scope="session")
def _require_chromium() -> None:
    """Skip the whole session, with a clear reason, if Chromium isn't installed.

    Checked BEFORE `app_server` boots the (slow) app subprocess: no point
    waiting a couple of minutes for a prod build just to fail on the browser
    launch afterwards.

    The probe runs in its own SUBPROCESS rather than calling
    `sync_playwright()` in-process: this test session already resolves
    `pytest-playwright`'s own `page`/`browser` fixtures for the actual tests,
    and a second independent `sync_playwright()` start in the same thread
    trips playwright's "Sync API inside the asyncio loop" guard (verified
    empirically — it fires even though nothing here is async; the guard
    reacts to the first `sync_playwright()` context pytest-playwright itself
    already holds open for the session, not to real asyncio). An isolated
    subprocess has no such conflict, and is exactly what a "can chromium
    even launch at all" check should be anyway.
    """
    try:
        import playwright  # noqa: F401
    except ImportError:
        pytest.skip("playwright is not installed; run `uv sync --extra browser`")
    result = subprocess.run(
        [sys.executable, "-c", _CHROMIUM_PROBE],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        pytest.skip(
            "Chromium is not available for playwright; run `uv run playwright install "
            f"chromium`.\n--- probe output ---\n{result.stdout}{result.stderr}"
        )


@pytest.fixture(scope="session")
def app_server(_require_chromium: None) -> Iterator[str]:
    """Boot the real app ONCE for the whole session; yield its base URL.

    Session-scoped on purpose: a prod build (see module docstring) is real
    wall-clock cost, and none of these tests mutate server-side state in a
    way that would require a fresh instance per test.

    Set `BROWSER_TEST_BASE_URL` to point these tests at an already-running
    server instead (e.g. the Render deployment's single-port Docker
    container), rather than spawning a `reflex run` subprocess: this is how
    the Docker deployment verification proves the websocket path survives
    Caddy's proxy, since a chart only renders a data-driven element like an
    axis tick if the state connection actually came up.
    """
    if base_url := os.environ.get("BROWSER_TEST_BASE_URL"):
        _wait_until_reachable(base_url)
        yield base_url
        return
    _ensure_sample_data()
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    output: list[str] = []
    proc = subprocess.Popen(
        [
            "uv",
            "run",
            "reflex",
            "run",
            "--env",
            "prod",
            "--frontend-port",
            str(port),
            "--loglevel",
            "warning",
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    drain_thread = Thread(target=_drain_output, args=(proc, output), daemon=True)
    drain_thread.start()
    try:
        _wait_until_serving(proc, base_url, output)
        yield base_url
    finally:
        _terminate(proc)


@pytest.fixture(scope="session")
def static_app(_require_chromium: None) -> Iterator[str]:
    """Boot the static frontend's Vite dev server once for the session; yield its base URL.

    A SIBLING of `app_server`, not a replacement for it: `app_server` serves
    the Reflex app (Python backend + its own compiled frontend). The static
    frontend under `web/` is a completely separate site with no backend at
    all -- Vite serving `web/src` per `web/vite.config.ts`'s `root`, same as
    `test_conformance.py`'s `vite_server` fixture drives for the conformance
    harness. Reusing `app_server` here would point every assertion in
    `test_static_app.py` at the Reflex app instead, which would fail (or
    worse, half-pass) in ways that look like application bugs rather than a
    fixture pointed at the wrong site.

    Set `STATIC_APP_BASE_URL` to point at an already-running Vite (or a
    static build served some other way) instead of spawning one here, mirroring
    `app_server`'s `BROWSER_TEST_BASE_URL` escape hatch.
    """
    if base_url := os.environ.get("STATIC_APP_BASE_URL"):
        _wait_until_reachable(base_url)
        yield base_url
        return
    port = _free_port()
    # "localhost", not "127.0.0.1": Vite's dev server (unlike `reflex run`,
    # which app_server points at 127.0.0.1 successfully) does not accept
    # connections on the IPv4 loopback address here unless told `--host`, only
    # on "localhost" -- confirmed by hand, and the same host
    # `test_conformance.py`'s `vite_server` fixture already uses for the
    # identical dev server.
    base_url = f"http://localhost:{port}"
    output: list[str] = []
    proc = subprocess.Popen(
        ["npm", "run", "dev", "--", "--port", str(port), "--strictPort"],
        cwd=REPO_ROOT / "web",
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    drain_thread = Thread(target=_drain_output, args=(proc, output), daemon=True)
    drain_thread.start()
    try:
        _wait_until_serving(proc, base_url, output, label="`npm run dev` (vite)")
        yield base_url
    finally:
        _terminate(proc)


@pytest.fixture(scope="session")
def built_static_app(_require_chromium: None) -> Iterator[str]:
    """Build the static frontend for real (`npm run build`) and serve
    `web/dist` with a plain HTTP server; yield its base URL.

    NOT a second way to reach `static_app` (Vite's dev server) -- the two
    disagree on a property that matters for any test inspecting network
    response codes. `marts/mart_climate_daily.parquet` is deliberately
    excluded from the static build (see `scripts/stage_web_data.py`), and
    `docs/12-deployment.md` warns against verifying that exclusion with
    `vite preview`, whose SPA fallback returns `200` with `index.html` for
    any unmatched path. Vite's DEV server (what `static_app` spawns) turns
    out to have the exact same fallback active by default: read straight out
    of `htmlFallbackMiddleware` in `web/node_modules/vite/dist/node/chunks/`,
    it triggers whenever a request's `Accept` header is absent, empty, or
    `*/*` -- regardless of the URL's file extension -- and a plain `fetch()`
    call with no explicit `Accept` (exactly what DuckDB-WASM's httpfs reader
    sends) matches that condition. Confirmed by hand: `curl` against a
    running `npm run dev` returns `200`/`text/html` for the missing parquet
    with a default `Accept`, and a real `404` only once `Accept:
    application/octet-stream` is forced. So `static_app` cannot tell a
    genuine 404 apart from this fallback either -- only a plain server with
    no SPA fallback at all (what this fixture spawns, matching Netlify's
    default of no rewrite rule) can.

    Set `BUILT_STATIC_APP_BASE_URL` to point at an already-built,
    already-served `web/dist` instead of building/serving one here.
    """
    if base_url := os.environ.get("BUILT_STATIC_APP_BASE_URL"):
        _wait_until_reachable(base_url)
        yield base_url
        return
    subprocess.run(
        ["npm", "run", "build"],
        cwd=REPO_ROOT / "web",
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        check=True,
    )
    dist_dir = REPO_ROOT / "web" / "dist"
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    output: list[str] = []
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", "-d", str(dist_dir), "-b", "127.0.0.1", str(port)],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    drain_thread = Thread(target=_drain_output, args=(proc, output), daemon=True)
    drain_thread.start()
    try:
        _wait_until_serving(proc, base_url, output, label="`python -m http.server` (built dist)")
        yield base_url
    finally:
        _terminate(proc)
