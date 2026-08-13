"""The province -> capital city -> region mapping, and the committed seed."""

from __future__ import annotations

import csv

from ingestion import capitals

# Italy's bounding box, generous by ~0.2 degrees on every side.
LAT_MIN, LAT_MAX = 35.4, 47.2
LON_MIN, LON_MAX = 6.5, 18.6


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
