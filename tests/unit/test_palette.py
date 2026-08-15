"""The palette is machine-validated, not eyeballed.

Two layers, different jobs:

- The golden tests below (`test_palette_values_are_pinned`) pin every constant
  literally and run everywhere, no Node required. They exist because the
  validator-backed tests skip on any machine that lacks the dataviz validator
  or `node` (a clean clone, another developer's box, CI) — and a test that
  quietly skips green delivers none of the protection a colour edit needs.
- The validator-backed tests run the dataviz validator over the shipped
  values. A colour edit that breaks colourblind separation, the lightness
  band or contrast fails here rather than shipping, on any machine where the
  validator is available.
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

requires_validator = pytest.mark.skipif(
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


# --------------------------------------------------------------- golden pin
#
# Every value below was derived by machine search against the dataviz palette
# validator and verified independently. This test does NOT re-derive them: it
# pins them, so an edit cannot land silently on a machine where the validator
# is unavailable. If you are changing a colour deliberately: re-run the
# validator (see test_categorical_light_passes and friends), confirm every
# check still passes, and update BOTH the palette and this test in the same
# commit.
EXPECTED = {
    "SURFACE_LIGHT": "#fcfcfb",
    "SURFACE_DARK": "#1a1a19",
    "CATEGORICAL_LIGHT": ("#2a78d6", "#eb6834", "#1baf7a"),
    "CATEGORICAL_DARK": ("#2072d0", "#de5c27", "#00995f"),
    "DIVERGING_LIGHT": (
        "#1f5fa8",
        "#2a78d6",
        "#8ab8ea",
        "#b2b2b2",
        "#ff7d44",
        "#eb6834",
        "#cc5e34",
    ),
    "DIVERGING_DARK": (
        "#005acb",
        "#2072d0",
        "#4986d4",
        "#4c4d4c",
        "#ef7344",
        "#de5c27",
        "#c34f1e",
    ),
    "SEQUENTIAL_LIGHT": ("#71b2ff", "#5090e2", "#2e6ebd", "#054e9a", "#002d77"),
    "SEQUENTIAL_DARK": ("#8ed1ff", "#6eafff", "#4e8ee0", "#2e6ebd", "#074f9b"),
}


@pytest.mark.parametrize("name,expected", sorted(EXPECTED.items()))
def test_palette_values_are_pinned(name: str, expected: tuple[str, ...] | str):
    assert getattr(palette, name) == expected


# ------------------------------------------------------------ validator-backed


@requires_validator
def test_categorical_light_passes():
    _assert_no_failures(
        _run("cat", palette.CATEGORICAL_LIGHT, "light", palette.SURFACE_LIGHT), "cat light"
    )


@requires_validator
def test_categorical_dark_passes():
    _assert_no_failures(
        _run("cat", palette.CATEGORICAL_DARK, "dark", palette.SURFACE_DARK), "cat dark"
    )


@requires_validator
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


@requires_validator
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


def test_diverging_bucket_maps_sign_to_the_right_arm():
    mid = palette.DIVERGING_STEPS // 2
    assert palette.diverging_bucket(0.0) == mid
    assert palette.diverging_bucket(-1.5) < mid
    assert palette.diverging_bucket(1.5) > mid


def test_diverging_bucket_clamps_instead_of_wrapping():
    assert palette.diverging_bucket(-99.0) == 0
    assert palette.diverging_bucket(99.0) == palette.DIVERGING_STEPS - 1


def test_diverging_bucket_is_monotonic():
    values = [palette.diverging_bucket(a / 10) for a in range(-40, 41)]
    assert values == sorted(values)


def test_diverging_bucket_rejects_a_non_positive_range():
    with pytest.raises(ValueError):
        palette.diverging_bucket(0.5, half_range=0)
