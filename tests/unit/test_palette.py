"""The palette is machine-validated, not eyeballed.

These tests run the dataviz validator over the shipped values. A colour edit
that breaks colourblind separation, the lightness band or contrast fails here
rather than shipping.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from italy_dashboard import palette

VALIDATOR = Path(
    "/private/tmp/claude-501/bundled-skills/2.1.220/"
    "a98a95678ed18250c62d48f3cfa1dc2a/dataviz/scripts/validate_palette.js"
)

pytestmark = pytest.mark.skipif(
    not VALIDATOR.exists() or shutil.which("node") is None,
    reason="dataviz validator or node unavailable",
)


def _run(kind: str, colors: tuple[str, ...], mode: str, surface: str) -> dict:
    """Call the validator's validate()/validateOrdinal() and return its report."""
    script = f"""
    import {{ validate, validateOrdinal }} from "{VALIDATOR}";
    const fn = {"validateOrdinal" if kind == "ordinal" else "validate"};
    const res = fn({json.dumps(list(colors))}, {{mode: "{mode}", surface: "{surface}"}});
    console.log(JSON.stringify(res));
    """
    out = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return json.loads(out.stdout)


def _assert_no_failures(res: dict, label: str) -> None:
    failures = [r for r in res["report"] if r[1] is False or r[1] == "fail"]
    assert not failures, f"{label}: {failures}"


def test_categorical_light_passes():
    _assert_no_failures(
        _run("cat", palette.CATEGORICAL_LIGHT, "light", palette.SURFACE_LIGHT), "cat light"
    )


def test_categorical_dark_passes():
    _assert_no_failures(
        _run("cat", palette.CATEGORICAL_DARK, "dark", palette.SURFACE_DARK), "cat dark"
    )


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_diverging_arms_pass(mode: str):
    """Each arm is validated as a single-hue ramp, EXCLUDING the neutral midpoint.

    Including the midpoint would blow the single-hue check by design: a neutral
    gray is not the arms' hue. That is expected, not a failure.
    """
    steps = palette.DIVERGING_LIGHT if mode == "light" else palette.DIVERGING_DARK
    surface = palette.SURFACE_LIGHT if mode == "light" else palette.SURFACE_DARK
    cool = tuple(reversed(steps[:3]))  # pale -> deep
    warm = steps[4:]
    _assert_no_failures(_run("ordinal", cool, mode, surface), f"div {mode} cool")
    _assert_no_failures(_run("ordinal", warm, mode, surface), f"div {mode} warm")


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_sequential_passes(mode: str):
    steps = palette.SEQUENTIAL_LIGHT if mode == "light" else palette.SEQUENTIAL_DARK
    surface = palette.SURFACE_LIGHT if mode == "light" else palette.SURFACE_DARK
    _assert_no_failures(_run("ordinal", steps, mode, surface), f"seq {mode}")


def test_diverging_has_seven_steps_with_a_neutral_middle():
    for steps in (palette.DIVERGING_LIGHT, palette.DIVERGING_DARK):
        assert len(steps) == 7
        r, g, b = (int(steps[3][i : i + 2], 16) for i in (1, 3, 5))
        assert abs(r - g) <= 2 and abs(g - b) <= 2, f"midpoint {steps[3]} is not neutral"


def test_css_vars_cover_every_diverging_step():
    css = palette.diverging_css_vars()
    for i in range(7):
        assert f"--div-{i}:" in css
    assert ".dark" in css or "[data-theme" in css
