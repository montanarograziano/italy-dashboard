"""The province -> capital city -> region mapping, and the committed seed."""

from __future__ import annotations

import csv

from ingestion import capitals

# Italy's bounding box, generous by ~0.2 degrees on every side.
LAT_MIN, LAT_MAX = 35.4, 47.2
LON_MIN, LON_MAX = 6.5, 18.6

# Known coordinates for the capitals whose names are ambiguous or whose
# province name differs from the city. A geocoder returning a plausible but
# WRONG Italian city passes the bounding-box test; these do not let it.
ANCHORS = {
    "ITC20": (45.735, 7.313),  # Aosta
    "ITC14": (45.921, 8.552),  # Verbania
    "ITE11": (44.035, 10.141),  # Massa
    "ITD58": (44.222, 12.041),  # Forlì
    "IT108": (45.584, 9.274),  # Monza
    "IT110": (41.317, 16.283),  # Barletta
    "ITE31": (43.910, 12.913),  # Pesaro
    "ITD10": (46.498, 11.354),  # Bolzano
    "ITD53": (44.698, 10.631),  # Reggio nell'Emilia
    "ITF65": (38.111, 15.647),  # Reggio di Calabria
}
ANCHOR_TOLERANCE_DEG = 0.15


def test_province_list_has_106_unique_codes():
    codes = [code for code, _ in capitals.PROVINCES]
    assert len(codes) == 106
    assert len(set(codes)) == 106


def test_region_code_uses_nuts_prefix_for_normal_codes():
    assert capitals.region_code_for("ITC11") == "ITC1"
    assert capitals.region_code_for("ITC4A") == "ITC4"
    assert capitals.region_code_for("ITE1A") == "ITE1"
    assert capitals.region_code_for("ITD10") == "ITD1"


def test_region_code_overrides_the_three_non_nuts_provinces():
    # IT108/IT109/IT110 carry no region prefix; a prefix rule would produce "IT10".
    assert capitals.region_code_for("IT108") == "ITC4"  # Monza -> Lombardia
    assert capitals.region_code_for("IT109") == "ITE3"  # Fermo -> Marche
    assert capitals.region_code_for("IT110") == "ITF4"  # BAT -> Puglia


def test_capital_city_defaults_to_the_province_name():
    assert capitals.capital_city_for("ITC45", "Milano") == "Milano"


def test_capital_city_overrides_where_province_name_is_not_the_city():
    assert capitals.capital_city_for("ITC20", "Valle d'Aosta / Vallée d'Aoste") == "Aosta"
    assert capitals.capital_city_for("ITC14", "Verbano-Cusio-Ossola") == "Verbania"
    assert capitals.capital_city_for("ITE11", "Massa-Carrara") == "Massa"
    assert capitals.capital_city_for("ITD58", "Forlì-Cesena") == "Forlì"
    assert capitals.capital_city_for("IT108", "Monza e della Brianza") == "Monza"
    assert capitals.capital_city_for("IT110", "Barletta-Andria-Trani") == "Barletta"
    assert capitals.capital_city_for("ITE31", "Pesaro e Urbino") == "Pesaro"
    assert capitals.capital_city_for("ITD10", "Bolzano / Bozen") == "Bolzano"


def test_every_province_maps_to_a_known_region():
    for code, _ in capitals.PROVINCES:
        assert capitals.region_code_for(code) in capitals.REGION_NAMES


def test_all_21_region_units_are_covered():
    covered = {capitals.region_code_for(code) for code, _ in capitals.PROVINCES}
    assert covered == set(capitals.REGION_NAMES)


def test_committed_seed_is_complete_and_inside_italy():
    with capitals.SEED_PATH.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    assert len(rows) == 106
    assert {r["province_code"] for r in rows} == {c for c, _ in capitals.PROVINCES}

    for r in rows:
        assert r["capital_city"], r
        assert r["region_code"] in capitals.REGION_NAMES, r
        assert r["region_name"] == capitals.REGION_NAMES[r["region_code"]], r
        assert LAT_MIN <= float(r["lat"]) <= LAT_MAX, r
        assert LON_MIN <= float(r["lon"]) <= LON_MAX, r


def test_seed_coordinates_are_distinct():
    with capitals.SEED_PATH.open(newline="", encoding="utf-8") as fh:
        pairs = [(r["lat"], r["lon"]) for r in csv.DictReader(fh)]
    assert len(set(pairs)) == len(pairs)


def test_ambiguous_capitals_match_known_anchor_coordinates():
    """A wrong-but-still-Italian city (e.g. the two Reggios swapped) must fail here.

    The bounding-box and distinctness checks above would both pass a swap;
    only a per-city anchor catches it.
    """
    with capitals.SEED_PATH.open(newline="", encoding="utf-8") as fh:
        rows = {r["province_code"]: r for r in csv.DictReader(fh)}

    for code, (anchor_lat, anchor_lon) in ANCHORS.items():
        row = rows[code]
        lat, lon = float(row["lat"]), float(row["lon"])
        assert abs(lat - anchor_lat) <= ANCHOR_TOLERANCE_DEG, (
            f"{code} ({row['capital_city']}): lat {lat} is more than "
            f"{ANCHOR_TOLERANCE_DEG} degrees from the known {anchor_lat}"
        )
        assert abs(lon - anchor_lon) <= ANCHOR_TOLERANCE_DEG, (
            f"{code} ({row['capital_city']}): lon {lon} is more than "
            f"{ANCHOR_TOLERANCE_DEG} degrees from the known {anchor_lon}"
        )


def test_far_north_and_far_south_regions_are_not_confused():
    """Catches a whole-row region shift or mis-assignment the anchors alone would not."""
    with capitals.SEED_PATH.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    sicilia = [r for r in rows if r["region_code"] == "ITG1"]
    alpine = [r for r in rows if r["region_code"] in {"ITD1", "ITD2"}]
    assert sicilia, "expected at least one Sicilia (ITG1) row"
    assert alpine, "expected at least one Bolzano/Trento (ITD1/ITD2) row"

    for r in sicilia:
        assert float(r["lat"]) < 38.3, r
    for r in alpine:
        assert float(r["lat"]) > 46.0, r
