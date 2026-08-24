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
import shutil
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
        import playwright  # noqa: F401  # pyrefly: ignore[missing-import]  # optional extra
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
    server instead (e.g. the single-port Docker container from `just
    docker-serve`), rather than spawning a `reflex run` subprocess: this is
    how the Docker verification proves the websocket path survives Caddy's
    proxy, since a chart only renders a data-driven element like an axis
    tick if the state connection actually came up.
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
    no SPA fallback at all (what this fixture spawns, matching GitHub Pages'
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


@pytest.fixture(scope="module")
def built_static_app_under_subpath(
    _require_chromium: None, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[str]:
    """Same real-build-plus-plain-server shape as `built_static_app`, but
    built with Vite's `base` set to `/italy-dashboard/` and served from
    under that same path prefix -- exactly the shape GitHub Pages serves a
    project site in (`.github/workflows/pages.yml`), and NOT the shape any
    other fixture in this file exercises. `built_static_app`/`static_app`
    both serve `web/dist` (or Vite dev) at the origin ROOT, which is also
    where `web/vite.config.ts`'s default (unset) `base` resolves to -- so
    neither could ever have caught the parquet-URL bug this fixture exists
    to guard against: `registerParquetViews` (`web/src/db.ts`) used to build
    every parquet URL off `window.location.origin` directly, silently
    dropping any path prefix Vite's `base` had actually been given.

    A SEPARATE `--outDir` (not `web/dist`) for the same reason CI's `web` job
    uses one (`.github/workflows/ci.yml`): this fixture is `scope="module"`
    and this module can run in the same session as `test_static_app.py`'s
    `built_static_app` (`scope="session"`) -- building over the shared
    `web/dist` a moment after that fixture already handed out a base URL
    pointing at it would silently rewrite what that URL serves for the rest
    of the session.

    The subpath itself is produced by SYMLINKING the built output into a
    fresh temp directory as `<tmp>/italy-dashboard`, then rooting a plain
    `http.server` at `<tmp>` -- so `{base_url}/italy-dashboard/...` resolves
    through the symlink to exactly the files `upload-pages-artifact` would
    have uploaded, with no copy step to keep in sync. Deliberately the same
    plain-server-with-no-fallback shape as `built_static_app` (see that
    fixture's docstring for why: Vite's dev server and `vite preview` both
    apply an `Accept`-header-keyed SPA fallback that would mask the
    deliberately-404ing `marts/mart_climate_daily.parquet` this fixture's
    caller also has to keep verifying under the new path prefix).

    No env-var escape hatch (unlike the fixtures above): this shape only
    exists to be built and served by this fixture, there is no "already
    running" instance of it a caller would ever want to point at instead.
    """
    outdir = tmp_path_factory.mktemp("pages_subpath_dist")
    subprocess.run(
        ["npm", "run", "build", "--", "--base=/italy-dashboard/", "--outDir", str(outdir)],
        cwd=REPO_ROOT / "web",
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        check=True,
    )
    serve_root = tmp_path_factory.mktemp("pages_subpath_root")
    (serve_root / "italy-dashboard").symlink_to(outdir, target_is_directory=True)
    port = _free_port()
    origin = f"http://127.0.0.1:{port}"
    base_url = f"{origin}/italy-dashboard"
    output: list[str] = []
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", "-d", str(serve_root), "-b", "127.0.0.1", str(port)],
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
        _wait_until_serving(
            proc, base_url + "/", output, label="`python -m http.server` (built dist, subpath)"
        )
        yield base_url
    finally:
        _terminate(proc)


@pytest.fixture(scope="session")
def _require_caddy() -> None:
    """Skip, with a clear reason, if the `caddy` binary isn't on PATH.

    Mirrors `_require_chromium` above: checked before `render_deploy_shape`
    spends time on a real `reflex export` + backend boot, and gives a actionable
    install hint (`brew install caddy` / https://caddyserver.com/docs/install)
    rather than a bare `FileNotFoundError` from `subprocess.Popen`.
    """
    if shutil.which("caddy") is None:
        pytest.skip("caddy is not installed; see https://caddyserver.com/docs/install")


@pytest.fixture(scope="module")
def render_deploy_shape(
    _require_chromium: None, _require_caddy: None, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[str]:
    """The real Render single-port shape: a static export, a separate
    backend-only Reflex process, and Caddy in front, reading the repo's OWN
    checked-in `Caddyfile` -- not a hand-copied duplicate of it.

    Every other Reflex fixture here (`app_server`) runs `reflex run --env
    prod`, which serves frontend and backend from ONE integrated process and
    never touches `Caddyfile` at all. That gap is exactly how the real
    `try_files {path} /index.html` bug shipped and stayed invisible: it only
    manifests when a route's request is resolved by Caddy against the
    EXPORTED static files (`reflex export --frontend-only`, what
    `Dockerfile` actually ships), which `{path}` alone cannot
    match -- Reflex writes each route as `<route>.html` and
    `<route>/index.html`, never a bare extension-less file -- so the old rule
    fell through to `/index.html` (home's prerendered markup) for every
    OTHER route's direct load. React Router then hydrated against the real
    URL, rendered that route's real page client-side, and could not
    reconcile it with the home markup the server had actually sent: a
    guaranteed React error #418 on every non-home route, reproduced by hand
    while diagnosing this exact fixture's scenario and now guarded here.

    The Caddyfile's `root * /srv/frontend` is the one line substituted at
    test time (Docker's baked-in path), so the `try_files`/`handle` rules
    under test are byte-for-byte what ships -- a regression there fails this
    fixture's callers, not a copy nobody keeps in sync.

    `scope="module"`, not `"session"` like the other heavy server fixtures in
    this file: this one spins up a SECOND full Reflex backend process (on top
    of whatever `app_server` already has running) plus a Caddy process, and
    it is only used by `test_render_deploy_shape.py`, so there is no reason
    to keep either alive once this module's tests finish.

    `REFLEX_WEB_WORKDIR` is set to an isolated `tmp_path_factory` directory
    for BOTH the export and the backend below -- not the repo's real `.web/`,
    Reflex's default. `app_server` (used by three earlier-collected files:
    `test_axis_contrast.py`, `test_band_opacity.py`, `test_loading_state.py`)
    is a SESSION-scoped `reflex run --env prod` already serving out of that
    real `.web/build` by the time this fixture's module runs. `reflex
    export` recompiles the frontend from scratch and rewrites every
    content-hashed asset filename in that same directory -- confirmed by
    hand to genuinely corrupt `app_server`'s already-served state for the
    REST OF THE SESSION: it hands out HTML/JS referencing the OLD hashes,
    which the export had just deleted, so a later `app_server`-backed test
    (`test_stripe_colors.py`, last in collection order) intermittently
    fails to find content that never actually rendered, its JS chunk having
    404'd. Reproduced 2/2 with a shared `.web/`, even after moving this
    fixture from session to module scope (proving IT WAS THE SHARED WRITE,
    not merely this fixture outliving its own module); 0/3 once the export
    and backend both point at an isolated `REFLEX_WEB_WORKDIR` instead.
    """
    _ensure_sample_data()
    isolated_web_dir = tmp_path_factory.mktemp("render_deploy_shape_web")
    reflex_env = {
        **os.environ,
        "PYTHONUNBUFFERED": "1",
        "REFLEX_WEB_WORKDIR": str(isolated_web_dir),
    }
    subprocess.run(
        ["uv", "run", "reflex", "export", "--frontend-only", "--env", "prod", "--no-zip"],
        cwd=REPO_ROOT,
        env=reflex_env,
        check=True,
    )
    backend_port = _free_port()
    backend_output: list[str] = []
    backend_proc = subprocess.Popen(
        [
            "uv",
            "run",
            "reflex",
            "run",
            "--backend-only",
            "--env",
            "prod",
            "--backend-host",
            "127.0.0.1",
            "--backend-port",
            str(backend_port),
            "--loglevel",
            "warning",
        ],
        cwd=REPO_ROOT,
        env=reflex_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    Thread(target=_drain_output, args=(backend_proc, backend_output), daemon=True).start()
    try:
        _wait_until_serving(
            backend_proc,
            f"http://127.0.0.1:{backend_port}/ping",
            backend_output,
            label="`reflex run --backend-only`",
        )

        caddy_port = _free_port()
        caddyfile_text = (
            (REPO_ROOT / "Caddyfile")
            .read_text()
            .replace("/srv/frontend", str(isolated_web_dir / "build" / "client"))
        )
        caddyfile_text = caddyfile_text.replace("localhost:8000", f"127.0.0.1:{backend_port}")
        # Also isolated (not `.web/`, see the fixture docstring): a stray
        # generated Caddyfile has no serving-conflict risk of its own, but
        # keeping every artifact this fixture writes inside `isolated_web_dir`
        # means one temp-dir cleanup covers all of it, not most of it.
        caddy_config = isolated_web_dir / "Caddyfile.test"
        caddy_config.write_text(caddyfile_text)
        base_url = f"http://127.0.0.1:{caddy_port}"
        caddy_output: list[str] = []
        caddy_proc = subprocess.Popen(
            ["caddy", "run", "--config", str(caddy_config), "--adapter", "caddyfile"],
            cwd=REPO_ROOT,
            env={**os.environ, "PORT": str(caddy_port)},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        Thread(target=_drain_output, args=(caddy_proc, caddy_output), daemon=True).start()
        try:
            _wait_until_serving(caddy_proc, base_url, caddy_output, label="`caddy run`")
            yield base_url
        finally:
            _terminate(caddy_proc)
    finally:
        _terminate(backend_proc)
