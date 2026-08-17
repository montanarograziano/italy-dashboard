"""Everything the app READS AT RUNTIME has to be inside the deployed image.

This class of defect is invisible to every other test in this repo: the code
imports fine, the suite passes, `ruff`/`pyrefly` are clean, and the container
still breaks — because a path that exists in the checkout was never copied into
the image. It has already happened once: `shared/queries/*.sql` was extracted
out of `queries.py` and nothing updated the Dockerfile, so seven queries raised
`FileNotFoundError` in production while the whole suite was green.

The requirement is DERIVED from the code rather than listed here: every
module-level `pathlib.Path` constant in `italy_dashboard` that points inside
the repo is a path the app resolves at runtime, so every one of them must be
carried into the image. A future extraction (`shared/palette.json`, say) is
covered automatically the moment it becomes a Path constant, which is the
point — a hardcoded list would have to be remembered exactly when it is
forgotten.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path, PurePosixPath

import pytest
import yaml

import italy_dashboard

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "Dockerfile"

# Runtime paths the image deliberately carries only PART of, with the reason.
# Kept explicit (rather than letting any overlapping COPY count as coverage)
# so that partially copying a NEW runtime directory is a recorded decision
# instead of an accident that looks like coverage.
#
#   data/ — the raw ISTAT/Open-Meteo downloads and the dbt scratch database
#   under it are ingestion/dbt inputs, hundreds of MB, and not read at runtime.
#   Only `data/*.parquet` and `data/marts/` are copied; see the long comment
#   above those COPY lines in the Dockerfile and `.dockerignore`.
PARTIALLY_COPIED = {PurePosixPath("data")}


def _runtime_paths() -> dict[PurePosixPath, str]:
    """Repo-relative runtime paths -> the constant that names each one.

    Every module in the `italy_dashboard` package is imported and scanned for
    module-level `Path` values inside the repo. The package directory itself is
    included from its own `__file__`: it is trivially copied today, but leaving
    it out would make this helper's claim ("every runtime-read path") false.
    """
    found: dict[PurePosixPath, str] = {}

    def record(path: Path, origin: str) -> None:
        if not path.is_relative_to(REPO_ROOT):
            return
        relative = PurePosixPath(path.relative_to(REPO_ROOT).as_posix())
        if relative == PurePosixPath("."):
            return  # PROJECT_ROOT itself: the build context, not a copied path
        found.setdefault(relative, origin)

    record(Path(italy_dashboard.__file__).resolve().parent, "italy_dashboard.__file__")
    for module_info in pkgutil.walk_packages(italy_dashboard.__path__, "italy_dashboard."):
        module = importlib.import_module(module_info.name)
        for name, value in vars(module).items():
            if isinstance(value, Path):
                record(value.resolve(), f"{module_info.name}.{name}")
    return found


def _copy_sources() -> list[PurePosixPath]:
    """Build-context paths the Dockerfile COPYs, globs reduced to their directory.

    `COPY --from=<image>` lines are skipped: they pull from another image (uv,
    Caddy), not from this repo, so they say nothing about what the checkout
    needs to provide.
    """
    sources: list[PurePosixPath] = []
    for raw in DOCKERFILE.read_text().splitlines():
        line = raw.strip()
        if not line.upper().startswith("COPY "):
            continue
        tokens = line.split()[1:]
        if any(token.startswith("--from=") for token in tokens):
            continue
        operands = [token for token in tokens if not token.startswith("--")]
        for operand in operands[:-1]:  # the last operand is the destination
            sources.append(_glob_prefix(PurePosixPath(operand)))
    return sources


def _glob_prefix(source: PurePosixPath) -> PurePosixPath:
    """`data/*.parquet` -> `data`. A glob covers no more than its directory."""
    for index, part in enumerate(source.parts):
        if any(char in part for char in "*?["):
            return PurePosixPath(*source.parts[:index]) if index else PurePosixPath(".")
    return source


def _is_ancestor(ancestor: PurePosixPath, descendant: PurePosixPath) -> bool:
    return ancestor != descendant and descendant.is_relative_to(ancestor)


def _dockerignore_patterns() -> list[PurePosixPath]:
    lines = (REPO_ROOT / ".dockerignore").read_text().splitlines()
    return [
        PurePosixPath(line.strip().rstrip("/"))
        for line in lines
        if line.strip() and not line.strip().startswith("#") and not line.strip().startswith("!")
    ]


RUNTIME_PATHS = _runtime_paths()


def test_the_scan_finds_the_runtime_paths_it_claims_to():
    """A guard on the guard: an empty or near-empty scan would pass everything.

    `shared/queries` is named explicitly because it is the path this whole file
    exists for; the count floor catches the scan silently collapsing (an import
    failure swallowed, a rename of the constants) and taking the real checks
    below down with it.
    """
    assert PurePosixPath("shared/queries") in RUNTIME_PATHS, sorted(map(str, RUNTIME_PATHS))
    assert len(RUNTIME_PATHS) >= 5, sorted(map(str, RUNTIME_PATHS))


@pytest.mark.parametrize("relative", sorted(RUNTIME_PATHS), ids=lambda p: str(p))
def test_the_dockerfile_copies_every_runtime_path(relative: PurePosixPath):
    """A COPY must cover each runtime path wholly, or declare it partial."""
    sources = _copy_sources()
    covered = (
        any(source == relative or _is_ancestor(source, relative) for source in sources)
        or relative in PARTIALLY_COPIED
    )
    assert covered, (
        f"{relative} is read at runtime ({RUNTIME_PATHS[relative]}) but no Dockerfile "
        f"COPY carries it into the image; add `COPY {relative} ./{relative}` (or, if "
        f"only part of it belongs in the image, add it to PARTIALLY_COPIED with the "
        f"reason). COPY sources today: {sorted(map(str, sources))}"
    )


@pytest.mark.parametrize("relative", sorted(RUNTIME_PATHS), ids=lambda p: str(p))
def test_dockerignore_does_not_exclude_a_runtime_path(relative: PurePosixPath):
    """A COPY line is not enough on its own: `.dockerignore` wins over it.

    Only the pattern shapes this file actually uses are understood (plain
    paths, with or without a trailing slash). A future wildcard pattern would
    slip past this check, which is why the Dockerfile-side test above is the
    primary guard and this one is the backstop.
    """
    for pattern in _dockerignore_patterns():
        assert not (pattern == relative or _is_ancestor(pattern, relative)), (
            f".dockerignore excludes {pattern}, which contains the runtime path "
            f"{relative} ({RUNTIME_PATHS[relative]})"
        )


def test_render_builds_the_image_from_the_repo_root():
    """The Dockerfile's COPY paths are repo-root-relative, so the build context
    has to BE the repo root. A narrower `dockerContext` would break every COPY
    at once on Render while `docker build .` kept working locally.
    """
    blueprint = yaml.safe_load((REPO_ROOT / "render.yaml").read_text())
    services = blueprint["services"]
    docker_services = [s for s in services if s.get("runtime") == "docker"]
    assert docker_services, "render.yaml declares no docker service"
    for service in docker_services:
        assert service["dockerContext"] == ".", service
        assert (REPO_ROOT / service["dockerfilePath"]).is_file(), service
