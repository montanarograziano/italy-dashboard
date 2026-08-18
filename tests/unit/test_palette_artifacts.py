"""The generated palette artifacts must match palette.py.

palette.py is the source of truth: its values were derived by machine search
against a colour validator and are pinned by golden tests. The static frontend
reads the generated JSON instead, so a palette edit that skips regeneration
would give the two frontends different colours. This test makes that fail.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from italy_dashboard import palette

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import generate_palette

SHARED = Path(__file__).resolve().parents[2] / "shared"


def test_committed_json_matches_the_generator():
    """Regenerating must be a no-op. If this fails, run `just generate-shared`."""
    assert (SHARED / "palette.json").read_text() == generate_palette.build_json()


def test_committed_css_matches_the_generator():
    assert (SHARED / "palette.css").read_text() == generate_palette.build_css()


def test_json_carries_every_role_in_both_modes():
    data = json.loads(generate_palette.build_json())
    for role in (
        "surface",
        "ink_primary",
        "ink_secondary",
        "ink_muted",
        "gridline",
        "categorical",
        "diverging",
        "sequential",
    ):
        assert set(data[role]) == {"light", "dark"}, role


def test_json_values_are_the_palette_values():
    data = json.loads(generate_palette.build_json())
    assert data["categorical"]["light"] == list(palette.CATEGORICAL_LIGHT)
    assert data["categorical"]["dark"] == list(palette.CATEGORICAL_DARK)
    assert data["diverging"]["light"] == list(palette.DIVERGING_LIGHT)
    assert data["diverging"]["dark"] == list(palette.DIVERGING_DARK)
    assert data["sequential"]["light"] == list(palette.SEQUENTIAL_LIGHT)
    assert data["sequential"]["dark"] == list(palette.SEQUENTIAL_DARK)
    assert data["surface"]["light"] == palette.SURFACE_LIGHT
    assert data["surface"]["dark"] == palette.SURFACE_DARK
    assert data["ink_primary"]["light"] == palette.INK_PRIMARY_LIGHT
    assert data["ink_primary"]["dark"] == palette.INK_PRIMARY_DARK
    assert data["ink_secondary"]["light"] == palette.INK_SECONDARY_LIGHT
    assert data["ink_secondary"]["dark"] == palette.INK_SECONDARY_DARK
    assert data["ink_muted"]["light"] == palette.INK_MUTED_LIGHT
    assert data["ink_muted"]["dark"] == palette.INK_MUTED_DARK
    assert data["gridline"]["light"] == palette.GRIDLINE_LIGHT
    assert data["gridline"]["dark"] == palette.GRIDLINE_DARK


def test_css_matches_the_existing_reflex_custom_properties():
    """The Reflex app already injects --div-N through components.shell().

    Both frontends must use the same property names and values, or the warming
    stripes would resolve differently on the two sites.
    """
    css = generate_palette.build_css()
    reflex_css = palette.diverging_css_vars()
    for i, colour in enumerate(palette.DIVERGING_LIGHT):
        assert f"--div-{i}: {colour};" in css
        assert f"--div-{i}: {colour};" in reflex_css


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_diverging_midpoint_stays_neutral_in_the_artifact(mode: str):
    """A tinted midpoint would break the diverging encoding on the static site."""
    data = json.loads(generate_palette.build_json())
    mid = data["diverging"][mode][3]
    r, g, b = (int(mid[i : i + 2], 16) for i in (1, 3, 5))
    assert abs(r - g) <= 2 and abs(g - b) <= 2, f"{mode} midpoint {mid} is not neutral"
