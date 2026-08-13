# Temperature Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add daily min/mean/max temperature for Italy from 1950 to today, per province capital city, rolled up to province and region, with a climate dashboard page and one region × year crime-versus-temperature panel.

**Architecture:** A second ingestion path (`ingestion/openmeteo.py` + `ingestion/weather.py`) fetches ERA5-Land daily temperatures from the Open-Meteo archive API and writes `data/weather_daily.parquet`, matching the existing "snapshot is a parquet file" contract. A committed dbt seed maps the 106 ISTAT province codes to their capital city and coordinates. dbt builds climate marts (daily, monthly, annual, region) plus `mart_crime_climate`, which joins summer temperature anomalies to violent offender counts with a two-way within transformation. Two new Reflex pages read the marts through `queries.py`.

**Tech Stack:** Python 3.11+, httpx2 (async), polars, DuckDB, dbt-duckdb, Reflex 0.9.8, pytest, just.

## Global Constraints

- Source: Open-Meteo Historical Weather API, `https://archive-api.open-meteo.com/v1/archive`, `models=era5_land` pinned explicitly. Free tier, **non-commercial use only**.
- Coverage: 1950-01-01 to (today − 7 days). ERA5 has a ~5-day publication lag.
- `ingestion/` must never import Reflex or dbt. `italy_dashboard/` must never make network calls.
- All marts materialize as external parquet under `{{ env_var('ITALY_DATA_DIR', 'data') }}/marts/`.
- `year` is **VARCHAR** in every mart, matching the existing ISTAT-derived marts, so joins need no casting.
- Line length 100 (ruff). Run `just check` (lint + typecheck + tests) before every commit.
- All tests run offline. No test may reach the network.
- Every commit message ends with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

---

## File Structure

**Created:**
- `ingestion/openmeteo.py` — async HTTP client for the Open-Meteo geocoding and archive endpoints. Knows HTTP and Open-Meteo's JSON shape, nothing else.
- `ingestion/weather.py` — CLI and orchestration: decade chunking, raw JSON caching, the null-rate gate, parquet writing.
- `ingestion/capitals.py` — one-off builder for the province-capitals seed. Run once, output committed.
- `dbt/seeds/province_capitals.csv` — 106 rows: province code, capital city, region, coordinates.
- `dbt/seeds/violent_crime_codes.csv` — the violent-crime subset of ISTAT's 59 offence codes.
- `dbt/models/staging/stg_weather.sql`
- `dbt/models/marts/mart_climate_daily.sql`, `mart_climate_monthly.sql`, `mart_climate_annual.sql`, `mart_climate_region.sql`, `mart_crime_climate.sql`
- `dbt/tests/assert_mart_climate_annual_unique_grain.sql`, `assert_mart_crime_climate_unique_grain.sql`
- `italy_dashboard/pages/climate.py`, `italy_dashboard/pages/climate_crime.py`
- `tests/unit/test_openmeteo.py`, `tests/unit/test_weather.py`, `tests/unit/test_capitals_seed.py`

**Modified:**
- `dbt/dbt_project.yml` — add `seed-paths` and seed column types.
- `dbt/models/staging/sources.yml` — add the weather parquet source.
- `ingestion/sample_data.py` — synthetic weather; two violent crime codes added to the offenders sample.
- `italy_dashboard/queries.py` — climate and crime-climate read functions.
- `italy_dashboard/state.py` — `ClimateState`, `ClimateCrimeState`.
- `italy_dashboard/components.py` — `NAV_LINKS` gains the climate route.
- `italy_dashboard/translations.py` — EN/IT strings for both pages.
- `italy_dashboard/italy_dashboard.py` — two routes.
- `justfile` — `build-capitals`, `refresh-weather`.
- `tests/integration/test_app_pages.py` — the two new pages.
- `docs/02-architecture.md`, `docs/04-datasets.md`, `docs/07-methodology.md`, `docs/11-roadmap.md`

---

### Task 1: Province capitals seed

**Files:**
- Create: `ingestion/capitals.py`
- Create: `dbt/seeds/province_capitals.csv` (generated, then committed)
- Create: `tests/unit/test_capitals_seed.py`
- Modify: `dbt/dbt_project.yml`
- Modify: `justfile`

**Interfaces:**
- Consumes: nothing.
- Produces: `dbt/seeds/province_capitals.csv` with header
  `province_code,province_name,capital_city,region_code,region_name,lat,lon`;
  `ingestion.capitals.PROVINCES: list[tuple[str, str]]`,
  `ingestion.capitals.REGION_NAMES: dict[str, str]`,
  `ingestion.capitals.CAPITAL_OVERRIDES: dict[str, str]`,
  `ingestion.capitals.REGION_OVERRIDES: dict[str, str]`,
  `ingestion.capitals.region_code_for(province_code: str) -> str`,
  `ingestion.capitals.capital_city_for(province_code: str, province_name: str) -> str`,
  `ingestion.capitals.SEED_PATH: Path`.

- [ ] **Step 1: Write the failing test for the pure mapping helpers**

Create `tests/unit/test_capitals_seed.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_capitals_seed.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingestion.capitals'`

- [ ] **Step 3: Write `ingestion/capitals.py`**

The 106 `(code, name)` pairs are the exact `region_level = 'province'` values in `data/marts/mart_offenders.parquet`. They are hardcoded rather than read from the mart so the seed builder does not depend on a built mart.

```python
"""One-off builder for the province-capitals seed.

Run once with `just build-capitals`, then REVIEW and COMMIT the generated
`dbt/seeds/province_capitals.csv`. Nothing geocodes at run time: a silent
upstream coordinate change would silently change every downstream number.

The province codes are ISTAT's, taken verbatim from mart_offenders
(region_level = 'province'), so the seed joins to the crime marts directly.
"""

from __future__ import annotations

import asyncio
import csv
import logging
import re
import sys
from pathlib import Path

from ingestion.openmeteo import OpenMeteoClient, OpenMeteoError

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ingestion.capitals")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SEED_PATH = PROJECT_ROOT / "dbt" / "seeds" / "province_capitals.csv"

SEED_COLUMNS = [
    "province_code",
    "province_name",
    "capital_city",
    "region_code",
    "region_name",
    "lat",
    "lon",
]

# The 21 region-level NUTS units in ISTAT's coding (19 regions + the two
# autonomous provinces). This dataflow family uses NUTS 2006 codes (ITD*/ITE*),
# not the later ITH*/ITI* revision.
REGION_NAMES: dict[str, str] = {
    "ITC1": "Piemonte",
    "ITC2": "Valle d'Aosta / Vallée d'Aoste",
    "ITC3": "Liguria",
    "ITC4": "Lombardia",
    "ITD1": "Provincia Autonoma Bolzano / Bozen",
    "ITD2": "Provincia Autonoma Trento",
    "ITD3": "Veneto",
    "ITD4": "Friuli-Venezia Giulia",
    "ITD5": "Emilia-Romagna",
    "ITE1": "Toscana",
    "ITE2": "Umbria",
    "ITE3": "Marche",
    "ITE4": "Lazio",
    "ITF1": "Abruzzo",
    "ITF2": "Molise",
    "ITF3": "Campania",
    "ITF4": "Puglia",
    "ITF5": "Basilicata",
    "ITF6": "Calabria",
    "ITG1": "Sicilia",
    "ITG2": "Sardegna",
}

# Provinces born after the NUTS coding was fixed carry a flat IT1xx code with
# no region prefix, so the prefix rule cannot find their region.
REGION_OVERRIDES: dict[str, str] = {
    "IT108": "ITC4",  # Monza e della Brianza -> Lombardia
    "IT109": "ITE3",  # Fermo -> Marche
    "IT110": "ITF4",  # Barletta-Andria-Trani -> Puglia
}

# Provinces whose name is not their capital city's name.
# IT110 has three official capitals (Barletta, Andria, Trani); Barletta is
# chosen as the single sampling point and the choice is recorded here.
CAPITAL_OVERRIDES: dict[str, str] = {
    "ITC20": "Aosta",
    "ITC14": "Verbania",
    "ITE11": "Massa",
    "ITD58": "Forlì",
    "IT108": "Monza",
    "IT110": "Barletta",
    "ITE31": "Pesaro",
    "ITD10": "Bolzano",
}

PROVINCES: list[tuple[str, str]] = [
    ("IT108", "Monza e della Brianza"),
    ("IT109", "Fermo"),
    ("IT110", "Barletta-Andria-Trani"),
    ("ITC11", "Torino"),
    ("ITC12", "Vercelli"),
    ("ITC13", "Biella"),
    ("ITC14", "Verbano-Cusio-Ossola"),
    ("ITC15", "Novara"),
    ("ITC16", "Cuneo"),
    ("ITC17", "Asti"),
    ("ITC18", "Alessandria"),
    ("ITC20", "Valle d'Aosta / Vallée d'Aoste"),
    ("ITC31", "Imperia"),
    ("ITC32", "Savona"),
    ("ITC33", "Genova"),
    ("ITC34", "La Spezia"),
    ("ITC41", "Varese"),
    ("ITC42", "Como"),
    ("ITC43", "Lecco"),
    ("ITC44", "Sondrio"),
    ("ITC45", "Milano"),
    ("ITC46", "Bergamo"),
    ("ITC47", "Brescia"),
    ("ITC48", "Pavia"),
    ("ITC49", "Lodi"),
    ("ITC4A", "Cremona"),
    ("ITC4B", "Mantova"),
    ("ITD10", "Bolzano / Bozen"),
    ("ITD20", "Trento"),
    ("ITD31", "Verona"),
    ("ITD32", "Vicenza"),
    ("ITD33", "Belluno"),
    ("ITD34", "Treviso"),
    ("ITD35", "Venezia"),
    ("ITD36", "Padova"),
    ("ITD37", "Rovigo"),
    ("ITD41", "Pordenone"),
    ("ITD42", "Udine"),
    ("ITD43", "Gorizia"),
    ("ITD44", "Trieste"),
    ("ITD51", "Piacenza"),
    ("ITD52", "Parma"),
    ("ITD53", "Reggio nell'Emilia"),
    ("ITD54", "Modena"),
    ("ITD55", "Bologna"),
    ("ITD56", "Ferrara"),
    ("ITD57", "Ravenna"),
    ("ITD58", "Forlì-Cesena"),
    ("ITD59", "Rimini"),
    ("ITE11", "Massa-Carrara"),
    ("ITE12", "Lucca"),
    ("ITE13", "Pistoia"),
    ("ITE14", "Firenze"),
    ("ITE15", "Prato"),
    ("ITE16", "Livorno"),
    ("ITE17", "Pisa"),
    ("ITE18", "Arezzo"),
    ("ITE19", "Siena"),
    ("ITE1A", "Grosseto"),
    ("ITE21", "Perugia"),
    ("ITE22", "Terni"),
    ("ITE31", "Pesaro e Urbino"),
    ("ITE32", "Ancona"),
    ("ITE33", "Macerata"),
    ("ITE34", "Ascoli Piceno"),
    ("ITE41", "Viterbo"),
    ("ITE42", "Rieti"),
    ("ITE43", "Roma"),
    ("ITE44", "Latina"),
    ("ITE45", "Frosinone"),
    ("ITF11", "L'Aquila"),
    ("ITF12", "Teramo"),
    ("ITF13", "Pescara"),
    ("ITF14", "Chieti"),
    ("ITF21", "Isernia"),
    ("ITF22", "Campobasso"),
    ("ITF31", "Caserta"),
    ("ITF32", "Benevento"),
    ("ITF33", "Napoli"),
    ("ITF34", "Avellino"),
    ("ITF35", "Salerno"),
    ("ITF41", "Foggia"),
    ("ITF42", "Bari"),
    ("ITF43", "Taranto"),
    ("ITF44", "Brindisi"),
    ("ITF45", "Lecce"),
    ("ITF51", "Potenza"),
    ("ITF52", "Matera"),
    ("ITF61", "Cosenza"),
    ("ITF62", "Crotone"),
    ("ITF63", "Catanzaro"),
    ("ITF64", "Vibo Valentia"),
    ("ITF65", "Reggio di Calabria"),
    ("ITG11", "Trapani"),
    ("ITG12", "Palermo"),
    ("ITG13", "Messina"),
    ("ITG14", "Agrigento"),
    ("ITG15", "Caltanissetta"),
    ("ITG16", "Enna"),
    ("ITG17", "Catania"),
    ("ITG18", "Ragusa"),
    ("ITG19", "Siracusa"),
    ("ITG25", "Sassari"),
    ("ITG26", "Nuoro"),
    ("ITG27", "Cagliari"),
    ("ITG28", "Oristano"),
]

_NUTS_PROVINCE = re.compile(r"^IT[A-Z][0-9]")


def region_code_for(province_code: str) -> str:
    """The NUTS2 region a province belongs to."""
    override = REGION_OVERRIDES.get(province_code)
    if override is not None:
        return override
    if _NUTS_PROVINCE.match(province_code):
        return province_code[:4]
    raise ValueError(f"No region mapping for province code {province_code!r}")


def capital_city_for(province_code: str, province_name: str) -> str:
    """The capital city sampled for a province."""
    return CAPITAL_OVERRIDES.get(province_code, province_name)


async def build_seed(path: Path = SEED_PATH) -> Path:
    """Geocode every capital once and write the seed CSV."""
    rows: list[dict[str, object]] = []
    async with OpenMeteoClient() as client:
        for code, province_name in PROVINCES:
            city = capital_city_for(code, province_name)
            region = region_code_for(code)
            try:
                lat, lon = await client.geocode_italian_city(city)
            except OpenMeteoError as exc:
                logger.error("[%s] geocoding %r failed: %s", code, city, exc)
                raise
            rows.append(
                {
                    "province_code": code,
                    "province_name": province_name,
                    "capital_city": city,
                    "region_code": region,
                    "region_name": REGION_NAMES[region],
                    "lat": round(lat, 4),
                    "lon": round(lon, 4),
                }
            )
            logger.info("[%s] %s -> %.4f, %.4f", code, city, lat, lon)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=SEED_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    logger.info("Wrote %d rows to %s — REVIEW before committing.", len(rows), path)
    return path


def main(argv: list[str]) -> int:
    if argv:
        print(__doc__)
        return 2
    asyncio.run(build_seed())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 4: Run the mapping tests (the seed test still fails)**

Run: `uv run pytest tests/unit/test_capitals_seed.py -v`
Expected: the seven mapping tests PASS; `test_committed_seed_is_complete_and_inside_italy` and `test_seed_coordinates_are_distinct` FAIL with `FileNotFoundError` — the seed does not exist yet. It is generated in Step 7, after the client exists.

Note: `ingestion/capitals.py` imports `ingestion.openmeteo`. **Task 2 is executed before Task 1**, so that module already exists when you start — verify with `ls ingestion/openmeteo.py` before Step 3. If it is missing, stop and report BLOCKED rather than stubbing it: the geocoding client is Task 2's deliverable and duplicating it here would leave two implementations to reconcile.

- [ ] **Step 5: Add seed wiring to `dbt/dbt_project.yml`**

Append after the `models:` block:

```yaml
seed-paths: ["seeds"]

seeds:
  italy_dashboard:
    +quote_columns: false
    province_capitals:
      +column_types:
        province_code: varchar
        province_name: varchar
        capital_city: varchar
        region_code: varchar
        region_name: varchar
        lat: double
        lon: double
```

- [ ] **Step 6: Add the justfile recipe**

Insert after the `dims` recipe:

```
# Rebuild the province-capitals seed (geocodes once; REVIEW the CSV before committing)
build-capitals:
    uv run python -m ingestion.capitals
```

- [ ] **Step 7: Generate the seed and review it by hand**

Run: `just build-capitals`

Then check the output before trusting it:

```bash
head -3 dbt/seeds/province_capitals.csv
wc -l dbt/seeds/province_capitals.csv   # expect 107 (106 rows + header)
```

Sanity-check a north, a centre and a south point against known values — Torino ≈ 45.07/7.69, Roma ≈ 41.89/12.48, Palermo ≈ 38.12/13.36. If any row is obviously wrong (wrong country, duplicate coordinates, a city in the sea), correct it in the CSV by hand and note why in the commit message. Hand corrections are expected and fine: the seed is committed data, not generated output.

- [ ] **Step 8: Run the tests to verify they all pass**

Run: `uv run pytest tests/unit/test_capitals_seed.py -v`
Expected: all nine PASS.

- [ ] **Step 9: Verify dbt loads the seed**

Run: `uv run dbt seed --project-dir dbt --profiles-dir dbt`
Expected: `1 of 1 OK loaded seed file main.province_capitals ... [INSERT 106]`

- [ ] **Step 10: Commit**

```bash
git add ingestion/capitals.py dbt/seeds/province_capitals.csv dbt/dbt_project.yml \
        justfile tests/unit/test_capitals_seed.py
git commit -m "feat: province capitals seed with coordinates

106 ISTAT province codes mapped to capital city, region and coordinates.
Codes come from mart_offenders so the seed joins to crime data directly.
Coordinates geocoded once and frozen: nothing geocodes at run time.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Open-Meteo client

**Files:**
- Create: `ingestion/openmeteo.py`
- Create: `tests/unit/test_openmeteo.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  `ingestion.openmeteo.OpenMeteoError` (subclass of `RuntimeError`),
  `ingestion.openmeteo.OpenMeteoClient` (async context manager, `__init__(self, transport: httpx2.AsyncBaseTransport | None = None)`),
  `OpenMeteoClient.geocode_italian_city(city: str) -> tuple[float, float]`,
  `OpenMeteoClient.daily_temperatures(lat: float, lon: float, start: date, end: date) -> dict[str, list]`
  returning `{"time": [...], "t_max": [...], "t_min": [...], "t_mean": [...]}` with `None` for gaps,
  `ingestion.openmeteo.ARCHIVE_URL`, `GEOCODING_URL`, `MODEL`, `DAILY_VARS`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_openmeteo.py`:

```python
"""Unit tests for the Open-Meteo client, fully offline via httpx2.MockTransport."""

from __future__ import annotations

import json
from datetime import date

import httpx2
import pytest

from ingestion import openmeteo
from ingestion.openmeteo import OpenMeteoClient, OpenMeteoError


def make_client(handler) -> OpenMeteoClient:
    return OpenMeteoClient(transport=httpx2.MockTransport(handler))


GEO_MULTI = {
    "results": [
        {
            "name": "Roma",
            "country_code": "US",
            "latitude": 43.2,
            "longitude": -75.4,
            "population": 32000,
        },
        {
            "name": "Roma",
            "country_code": "IT",
            "latitude": 41.8933,
            "longitude": 12.4829,
            "population": 2748109,
        },
        {
            "name": "Roma",
            "country_code": "IT",
            "latitude": 44.0,
            "longitude": 11.0,
            "population": 900,
        },
    ]
}

ARCHIVE_OK = {
    "latitude": 41.9,
    "longitude": 12.5,
    "daily": {
        "time": ["1950-01-01", "1950-01-02"],
        "temperature_2m_max": [11.4, 12.0],
        "temperature_2m_min": [2.1, 3.0],
        "temperature_2m_mean": [6.5, 7.2],
    },
}


async def test_geocode_picks_the_most_populous_italian_match():
    async def handler(request: httpx2.Request) -> httpx2.Response:
        assert "geocoding-api" in str(request.url)
        assert request.url.params["name"] == "Roma"
        return httpx2.Response(200, json=GEO_MULTI)

    async with make_client(handler) as client:
        lat, lon = await client.geocode_italian_city("Roma")

    assert (round(lat, 4), round(lon, 4)) == (41.8933, 12.4829)


async def test_geocode_raises_when_no_italian_match():
    async def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "results": [
                    {
                        "name": "Nowhere",
                        "country_code": "FR",
                        "latitude": 1.0,
                        "longitude": 2.0,
                        "population": 10,
                    }
                ]
            },
        )

    async with make_client(handler) as client:
        with pytest.raises(OpenMeteoError, match="No Italian match"):
            await client.geocode_italian_city("Nowhere")


async def test_geocode_raises_on_empty_results():
    async def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={})

    async with make_client(handler) as client:
        with pytest.raises(OpenMeteoError, match="No Italian match"):
            await client.geocode_italian_city("Atlantis")


async def test_daily_temperatures_pins_the_era5_land_model_and_parses_arrays():
    seen: dict[str, str] = {}

    async def handler(request: httpx2.Request) -> httpx2.Response:
        seen.update(dict(request.url.params))
        return httpx2.Response(200, json=ARCHIVE_OK)

    async with make_client(handler) as client:
        out = await client.daily_temperatures(41.9, 12.5, date(1950, 1, 1), date(1950, 1, 2))

    assert seen["models"] == "era5_land"
    assert seen["start_date"] == "1950-01-01"
    assert seen["end_date"] == "1950-01-02"
    assert out["time"] == ["1950-01-01", "1950-01-02"]
    assert out["t_max"] == [11.4, 12.0]
    assert out["t_min"] == [2.1, 3.0]
    assert out["t_mean"] == [6.5, 7.2]


async def test_daily_temperatures_accepts_model_suffixed_variable_names():
    """Open-Meteo suffixes variables with the model name in some responses."""
    payload = {
        "daily": {
            "time": ["1950-01-01"],
            "temperature_2m_max_era5_land": [11.4],
            "temperature_2m_min_era5_land": [2.1],
            "temperature_2m_mean_era5_land": [6.5],
        }
    }

    async def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=payload)

    async with make_client(handler) as client:
        out = await client.daily_temperatures(41.9, 12.5, date(1950, 1, 1), date(1950, 1, 1))

    assert out["t_max"] == [11.4]
    assert out["t_min"] == [2.1]
    assert out["t_mean"] == [6.5]


async def test_daily_temperatures_preserves_nulls_as_none():
    payload = {
        "daily": {
            "time": ["1950-01-01", "1950-01-02"],
            "temperature_2m_max": [11.4, None],
            "temperature_2m_min": [2.1, None],
            "temperature_2m_mean": [6.5, None],
        }
    }

    async def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=payload)

    async with make_client(handler) as client:
        out = await client.daily_temperatures(41.9, 12.5, date(1950, 1, 1), date(1950, 1, 2))

    assert out["t_mean"] == [6.5, None]


async def test_api_error_body_is_raised_with_its_reason():
    async def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(400, json={"error": True, "reason": "Invalid date range"})

    async with make_client(handler) as client:
        with pytest.raises(OpenMeteoError, match="Invalid date range"):
            await client.daily_temperatures(41.9, 12.5, date(1950, 1, 1), date(1950, 1, 2))


async def test_rate_limit_is_retried_then_succeeds(monkeypatch):
    monkeypatch.setattr(openmeteo, "RETRY_BACKOFF_S", 0.0)
    calls = {"n": 0}

    async def handler(request: httpx2.Request) -> httpx2.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx2.Response(429, text="slow down")
        return httpx2.Response(200, json=ARCHIVE_OK)

    async with make_client(handler) as client:
        out = await client.daily_temperatures(41.9, 12.5, date(1950, 1, 1), date(1950, 1, 2))

    assert calls["n"] == 2
    assert out["t_mean"] == [6.5, 7.2]


async def test_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr(openmeteo, "RETRY_BACKOFF_S", 0.0)

    async def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(500, text="boom")

    async with make_client(handler) as client:
        with pytest.raises(OpenMeteoError, match="after 3 attempts"):
            await client.daily_temperatures(41.9, 12.5, date(1950, 1, 1), date(1950, 1, 2))


async def test_client_requires_context_manager():
    client = OpenMeteoClient()
    with pytest.raises(RuntimeError, match="async context manager"):
        _ = client.client


def test_response_shape_constants_are_stable():
    assert openmeteo.MODEL == "era5_land"
    assert openmeteo.DAILY_VARS == (
        "temperature_2m_max",
        "temperature_2m_min",
        "temperature_2m_mean",
    )
    assert json.loads(json.dumps(ARCHIVE_OK))  # payload fixture stays JSON-serialisable
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_openmeteo.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingestion.openmeteo'`

- [ ] **Step 3: Write `ingestion/openmeteo.py`**

```python
"""Thin async client for the Open-Meteo archive and geocoding APIs.

Endpoint reference: https://open-meteo.com/en/docs/historical-weather-api

Design notes:
- Free tier, no API key, NON-COMMERCIAL use only. If this dashboard ever
  becomes commercial, switch to Copernicus CDS ERA5-Land or Open-Meteo's
  paid tier — the free endpoint is no longer permitted.
- `models=era5_land` is pinned explicitly. Open-Meteo's default "best match"
  switches underlying models across a long series, which would inject
  discontinuities indistinguishable from real climate signal.
- Mirrors ingestion/sdmx_client.py: async, injectable transport for tests,
  retries with backoff, no wrapper library.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date

import httpx2

logger = logging.getLogger(__name__)

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"

MODEL = "era5_land"
DAILY_VARS = ("temperature_2m_max", "temperature_2m_min", "temperature_2m_mean")

# Maps the API's variable names onto our column names.
VAR_TO_COLUMN = {
    "temperature_2m_max": "t_max",
    "temperature_2m_min": "t_min",
    "temperature_2m_mean": "t_mean",
}

DEFAULT_TIMEOUT = httpx2.Timeout(180.0, connect=30.0, read=120.0)
MAX_RETRIES = 3
RETRY_BACKOFF_S = 3.0
# Polite spacing between requests; the free tier is generous but not unlimited.
REQUEST_DELAY_S = 0.4


class OpenMeteoError(RuntimeError):
    """Raised when Open-Meteo returns an unusable response."""


class OpenMeteoClient:
    """Async context-manager client for the Open-Meteo public APIs."""

    def __init__(
        self,
        timeout: httpx2.Timeout = DEFAULT_TIMEOUT,
        transport: httpx2.AsyncBaseTransport | None = None,
    ):
        self._timeout = timeout
        self._transport = transport  # injectable for tests (httpx2.MockTransport)
        self._client: httpx2.AsyncClient | None = None

    async def __aenter__(self) -> OpenMeteoClient:
        self._client = httpx2.AsyncClient(
            timeout=self._timeout, follow_redirects=True, transport=self._transport
        )
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx2.AsyncClient:
        if self._client is None:
            raise RuntimeError("OpenMeteoClient must be used as an async context manager")
        return self._client

    async def _get_json(self, url: str, params: dict[str, str]) -> dict:
        """GET returning parsed JSON, retrying on rate limits and transport errors.

        Open-Meteo signals problems two ways: an HTTP error status, and a 200
        carrying {"error": true, "reason": ...}. Both are surfaced as
        OpenMeteoError with the reason text, because a silently-empty result
        would look like "this city has no data" rather than "the query is wrong".
        """
        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = await self.client.get(url, params=params)
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_error = OpenMeteoError(f"HTTP {resp.status_code} from {url}")
                elif resp.status_code >= 400:
                    raise OpenMeteoError(f"HTTP {resp.status_code} from {url}: {_reason(resp)}")
                else:
                    payload = resp.json()
                    if isinstance(payload, dict) and payload.get("error"):
                        raise OpenMeteoError(
                            f"{url} returned an error: {payload.get('reason', 'unknown')}"
                        )
                    return payload
            except (httpx2.TransportError, httpx2.TimeoutException) as exc:
                last_error = exc
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF_S * attempt
                logger.warning(
                    "Attempt %d/%d failed for %s (%s); retrying in %.1fs",
                    attempt,
                    MAX_RETRIES,
                    url,
                    last_error,
                    wait,
                )
                await asyncio.sleep(wait)
        raise OpenMeteoError(f"Failed after {MAX_RETRIES} attempts: {url}") from last_error

    async def geocode_italian_city(self, city: str) -> tuple[float, float]:
        """Coordinates of an Italian city, preferring the most populous match.

        Ambiguity is real (Reggio, Roma, ...), so the rule is deterministic:
        Italian matches only, highest population wins.
        """
        payload = await self._get_json(
            GEOCODING_URL,
            {"name": city, "count": "10", "language": "it", "format": "json"},
        )
        italian = [
            r
            for r in payload.get("results") or []
            if r.get("country_code") == "IT" and r.get("latitude") is not None
        ]
        if not italian:
            raise OpenMeteoError(f"No Italian match for city {city!r}")
        best = max(italian, key=lambda r: r.get("population") or 0)
        return float(best["latitude"]), float(best["longitude"])

    async def daily_temperatures(
        self, lat: float, lon: float, start: date, end: date
    ) -> dict[str, list]:
        """Daily max/min/mean for one point over a date range.

        Returns {"time": [...], "t_max": [...], "t_min": [...], "t_mean": [...]}.
        Missing days keep their None: the caller's null-rate gate decides
        whether a city's coordinate landed on an ERA5-Land ocean cell.
        """
        payload = await self._get_json(
            ARCHIVE_URL,
            {
                "latitude": f"{lat:.4f}",
                "longitude": f"{lon:.4f}",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "daily": ",".join(DAILY_VARS),
                "models": MODEL,
                "timezone": "UTC",
            },
        )
        daily = payload.get("daily") or {}
        out: dict[str, list] = {"time": list(daily.get("time") or [])}
        for var, column in VAR_TO_COLUMN.items():
            # Open-Meteo appends the model name to variable keys in some
            # responses; accept both spellings rather than guessing.
            values = daily.get(var)
            if values is None:
                values = daily.get(f"{var}_{MODEL}")
            if values is None:
                raise OpenMeteoError(f"Response is missing {var!r}; keys present: {sorted(daily)}")
            out[column] = list(values)
        return out


def _reason(resp: httpx2.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:200]
    if isinstance(body, dict):
        return str(body.get("reason", body))[:200]
    return str(body)[:200]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_openmeteo.py -v`
Expected: all 11 PASS.

- [ ] **Step 5: Commit**

```bash
git add ingestion/openmeteo.py tests/unit/test_openmeteo.py
git commit -m "feat: Open-Meteo archive and geocoding client

Async client mirroring the SDMX one: injectable transport, retries with
backoff, no wrapper library. models=era5_land is pinned explicitly because
Open-Meteo's default best-match switches models mid-series.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Weather fetch orchestration, null gate, parquet snapshot

**Files:**
- Create: `ingestion/weather.py`
- Create: `tests/unit/test_weather.py`
- Modify: `justfile`

**Interfaces:**
- Consumes: `ingestion.openmeteo.OpenMeteoClient`, `ingestion.capitals.SEED_PATH`.
- Produces:
  `ingestion.weather.START_DATE: date`, `PUBLICATION_LAG_DAYS: int`, `MAX_NULL_RATE: float`,
  `ingestion.weather.Capital` (frozen dataclass: `province_code, capital_city, lat, lon`),
  `ingestion.weather.load_capitals(path: Path) -> list[Capital]`,
  `ingestion.weather.decade_chunks(start: date, end: date) -> list[tuple[date, date]]`,
  `ingestion.weather.payload_to_rows(province_code: str, payload: dict) -> list[dict]`,
  `ingestion.weather.null_rate(rows: list[dict]) -> float`,
  `ingestion.weather.write_snapshot(rows: list[dict], data_dir: Path) -> Path`,
  `ingestion.weather.WEATHER_COLUMNS: list[str]`,
  `ingestion.weather.ensure_weather_placeholder(data_dir: Path) -> Path`,
  `ingestion.weather.WeatherError` (subclass of `RuntimeError`).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_weather.py`:

```python
"""Unit tests for weather chunking, parsing, the null gate and the snapshot."""

from __future__ import annotations

import csv
from datetime import date
from itertools import pairwise
from pathlib import Path

import polars as pl
import pytest

from ingestion import weather
from ingestion.weather import Capital, WeatherError


def write_seed(tmp_path: Path) -> Path:
    path = tmp_path / "province_capitals.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "province_code",
                "province_name",
                "capital_city",
                "region_code",
                "region_name",
                "lat",
                "lon",
            ]
        )
        w.writerow(["ITC45", "Milano", "Milano", "ITC4", "Lombardia", "45.4642", "9.19"])
        w.writerow(["ITE43", "Roma", "Roma", "ITE4", "Lazio", "41.8933", "12.4829"])
    return path


def test_load_capitals_reads_codes_and_coordinates(tmp_path):
    caps = weather.load_capitals(write_seed(tmp_path))
    assert [c.province_code for c in caps] == ["ITC45", "ITE43"]
    assert caps[0] == Capital("ITC45", "Milano", 45.4642, 9.19)


def test_decade_chunks_cover_the_range_without_gaps_or_overlap():
    chunks = weather.decade_chunks(date(1950, 1, 1), date(1971, 6, 15))
    assert chunks[0] == (date(1950, 1, 1), date(1959, 12, 31))
    assert chunks[1] == (date(1960, 1, 1), date(1969, 12, 31))
    assert chunks[-1] == (date(1970, 1, 1), date(1971, 6, 15))
    for (_, prev_end), (next_start, _) in pairwise(chunks):
        assert (next_start - prev_end).days == 1


def test_decade_chunks_handles_a_range_inside_one_decade():
    assert weather.decade_chunks(date(2021, 3, 1), date(2024, 5, 2)) == [
        (date(2021, 3, 1), date(2024, 5, 2))
    ]


def test_payload_to_rows_pairs_dates_with_values():
    payload = {
        "time": ["1950-01-01", "1950-01-02"],
        "t_max": [11.4, 12.0],
        "t_min": [2.1, 3.0],
        "t_mean": [6.5, 7.2],
    }
    rows = weather.payload_to_rows("ITE43", payload)
    assert rows[0] == {
        "province_code": "ITE43",
        "date": date(1950, 1, 1),
        "t_min": 2.1,
        "t_mean": 6.5,
        "t_max": 11.4,
    }
    assert len(rows) == 2


def test_payload_to_rows_rejects_ragged_arrays():
    payload = {
        "time": ["1950-01-01", "1950-01-02"],
        "t_max": [1.0],
        "t_min": [0.0],
        "t_mean": [0.5],
    }
    with pytest.raises(WeatherError, match="length mismatch"):
        weather.payload_to_rows("ITE43", payload)


def test_null_rate_counts_days_with_a_missing_mean():
    rows = [
        {"province_code": "X", "date": date(1950, 1, 1), "t_min": 1.0, "t_mean": 2.0, "t_max": 3.0},
        {
            "province_code": "X",
            "date": date(1950, 1, 2),
            "t_min": None,
            "t_mean": None,
            "t_max": None,
        },
    ]
    assert weather.null_rate(rows) == 0.5
    assert weather.null_rate([]) == 1.0


def test_write_snapshot_produces_the_expected_schema(tmp_path):
    rows = [
        {
            "province_code": "ITE43",
            "date": date(1950, 1, 1),
            "t_min": 2.1,
            "t_mean": 6.5,
            "t_max": 11.4,
        }
    ]
    out = weather.write_snapshot(rows, tmp_path)
    assert out == tmp_path / "weather_daily.parquet"
    df = pl.read_parquet(out)
    assert df.columns == weather.WEATHER_COLUMNS
    assert df.height == 1
    assert df["t_mean"].dtype == pl.Float64
    assert df["date"].dtype == pl.Date


def test_write_snapshot_is_atomic_and_leaves_no_tmp_file(tmp_path):
    rows = [
        {
            "province_code": "ITE43",
            "date": date(1950, 1, 1),
            "t_min": 2.1,
            "t_mean": 6.5,
            "t_max": 11.4,
        }
    ]
    weather.write_snapshot(rows, tmp_path)
    assert not list(tmp_path.glob("*.tmp"))


def test_placeholder_snapshot_has_the_same_schema_and_no_rows(tmp_path):
    out = weather.ensure_weather_placeholder(tmp_path)
    df = pl.read_parquet(out)
    assert df.columns == weather.WEATHER_COLUMNS
    assert df.height == 0


def test_placeholder_never_overwrites_a_real_snapshot(tmp_path):
    rows = [
        {
            "province_code": "ITE43",
            "date": date(1950, 1, 1),
            "t_min": 2.1,
            "t_mean": 6.5,
            "t_max": 11.4,
        }
    ]
    weather.write_snapshot(rows, tmp_path)
    weather.ensure_weather_placeholder(tmp_path)
    assert pl.read_parquet(tmp_path / "weather_daily.parquet").height == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_weather.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingestion.weather'`

- [ ] **Step 3: Write `ingestion/weather.py`**

```python
"""Fetch ERA5-Land daily temperatures per province capital -> parquet snapshot.

Usage:
    python -m ingestion.weather refresh          # every province capital
    python -m ingestion.weather refresh ITC45    # one province (after a coord fix)

Raw JSON is cached under data/raw/weather/, so an interrupted run resumes
instead of re-downloading 76 years for every city.
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import polars as pl

from ingestion.capitals import SEED_PATH
from ingestion.openmeteo import REQUEST_DELAY_S, OpenMeteoClient, OpenMeteoError

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ingestion.weather")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

START_DATE = date(1950, 1, 1)  # ERA5-Land's first year
PUBLICATION_LAG_DAYS = 7  # ERA5 lags reality by ~5 days; 7 is a safe margin

# A city whose 0.1 degree cell is ocean returns nulls. Fail loudly rather than
# publish a plausible-looking warming rate computed from a handful of days.
MAX_NULL_RATE = 0.01

WEATHER_COLUMNS = ["province_code", "date", "t_min", "t_mean", "t_max"]

SNAPSHOT_NAME = "weather_daily.parquet"


class WeatherError(RuntimeError):
    """Raised when fetched weather data is unusable."""


@dataclass(frozen=True)
class Capital:
    province_code: str
    capital_city: str
    lat: float
    lon: float


def load_capitals(path: Path = SEED_PATH) -> list[Capital]:
    with path.open(newline="", encoding="utf-8") as fh:
        return [
            Capital(
                province_code=r["province_code"],
                capital_city=r["capital_city"],
                lat=float(r["lat"]),
                lon=float(r["lon"]),
            )
            for r in csv.DictReader(fh)
        ]


def decade_chunks(start: date, end: date) -> list[tuple[date, date]]:
    """Split a range into calendar decades, clipped to the range's edges.

    Chunking keeps single responses small enough to retry cheaply and makes
    the raw cache resumable at decade granularity.
    """
    chunks: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        decade_end = date((cursor.year // 10) * 10 + 9, 12, 31)
        chunk_end = min(decade_end, end)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def payload_to_rows(province_code: str, payload: dict) -> list[dict]:
    times = payload.get("time") or []
    series = {col: payload.get(col) or [] for col in ("t_min", "t_mean", "t_max")}
    for col, values in series.items():
        if len(values) != len(times):
            raise WeatherError(
                f"[{province_code}] {col} length mismatch: "
                f"{len(values)} values for {len(times)} dates"
            )
    return [
        {
            "province_code": province_code,
            "date": datetime.strptime(times[i], "%Y-%m-%d").date(),
            "t_min": series["t_min"][i],
            "t_mean": series["t_mean"][i],
            "t_max": series["t_max"][i],
        }
        for i in range(len(times))
    ]


def null_rate(rows: list[dict]) -> float:
    """Share of days with no mean temperature. Empty input counts as fully null."""
    if not rows:
        return 1.0
    missing = sum(1 for r in rows if r["t_mean"] is None)
    return missing / len(rows)


def _empty_frame() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "province_code": pl.Utf8,
            "date": pl.Date,
            "t_min": pl.Float64,
            "t_mean": pl.Float64,
            "t_max": pl.Float64,
        }
    )


def write_snapshot(rows: list[dict], data_dir: Path = DATA_DIR) -> Path:
    """Write the normalized parquet snapshot, swapping it in atomically."""
    data_dir.mkdir(parents=True, exist_ok=True)
    out = data_dir / SNAPSHOT_NAME
    tmp = out.with_name(out.name + ".tmp")
    frame = _empty_frame() if not rows else pl.DataFrame(rows, schema=_empty_frame().schema)
    frame = frame.select(WEATHER_COLUMNS).sort(["province_code", "date"])
    frame.write_parquet(tmp)
    tmp.replace(out)  # atomic: a crash mid-write keeps the previous snapshot
    logger.info("wrote %s (%d rows)", out, frame.height)
    return out


def ensure_weather_placeholder(data_dir: Path = DATA_DIR) -> Path:
    """Empty snapshot so dbt sources resolve before the first real fetch."""
    out = data_dir / SNAPSHOT_NAME
    if out.exists():
        return out
    data_dir.mkdir(parents=True, exist_ok=True)
    _empty_frame().write_parquet(out)
    logger.info("no weather snapshot yet — wrote empty placeholder %s", out.name)
    return out


def _cache_path(raw_dir: Path, province_code: str, start: date) -> Path:
    return raw_dir / f"{province_code}_{start.year}.json"


async def _fetch_capital(
    client: OpenMeteoClient, cap: Capital, end: date, raw_dir: Path
) -> list[dict]:
    """All decades for one city, using the raw cache where it already exists."""
    rows: list[dict] = []
    for start, chunk_end in decade_chunks(START_DATE, end):
        cache = _cache_path(raw_dir, cap.province_code, start)
        # The current decade is still growing, so its cache is always stale.
        is_current_decade = chunk_end == end
        if cache.exists() and not is_current_decade:
            payload = json.loads(cache.read_text())
        else:
            payload = await client.daily_temperatures(cap.lat, cap.lon, start, chunk_end)
            tmp = cache.with_name(cache.name + ".tmp")
            tmp.write_text(json.dumps(payload))
            tmp.replace(cache)
            await asyncio.sleep(REQUEST_DELAY_S)
        rows.extend(payload_to_rows(cap.province_code, payload))
    return rows


async def cmd_refresh(only: str | None = None, data_dir: Path = DATA_DIR) -> int:
    capitals = load_capitals()
    if only is not None:
        capitals = [c for c in capitals if c.province_code == only]
        if not capitals:
            logger.error("Unknown province code %r — see dbt/seeds/province_capitals.csv", only)
            return 2

    raw_dir = data_dir / "raw" / "weather"
    raw_dir.mkdir(parents=True, exist_ok=True)
    end = date.today() - timedelta(days=PUBLICATION_LAG_DAYS)

    all_rows: list[dict] = []
    bad: list[tuple[str, float]] = []
    async with OpenMeteoClient() as client:
        for i, cap in enumerate(capitals, start=1):
            logger.info(
                "=== [%d/%d] %s (%s) ===", i, len(capitals), cap.capital_city, cap.province_code
            )
            try:
                rows = await _fetch_capital(client, cap, end, raw_dir)
            except OpenMeteoError as exc:
                logger.error("[%s] fetch failed: %s", cap.province_code, exc)
                return 1
            rate = null_rate(rows)
            if rate > MAX_NULL_RATE:
                bad.append((cap.province_code, rate))
                logger.error(
                    "[%s] %s: %.1f%% of days are null (limit %.1f%%). Its ERA5-Land "
                    "cell is probably ocean — nudge lat/lon inland in "
                    "dbt/seeds/province_capitals.csv and rerun "
                    "`just refresh-weather %s`.",
                    cap.province_code,
                    cap.capital_city,
                    100 * rate,
                    100 * MAX_NULL_RATE,
                    cap.province_code,
                )
            all_rows.extend(r for r in rows if r["t_mean"] is not None)

    if bad:
        logger.error(
            "Refusing to write the snapshot: %d cities exceed the null limit (%s). "
            "A partially-null city produces a plausible but wrong warming rate.",
            len(bad),
            ", ".join(code for code, _ in bad),
        )
        return 1

    if only is not None:
        # Single-city refresh merges into the existing snapshot instead of
        # replacing it with one city's rows.
        existing = data_dir / SNAPSHOT_NAME
        if existing.exists():
            kept = pl.read_parquet(existing).filter(pl.col("province_code") != only)
            all_rows = kept.to_dicts() + all_rows

    write_snapshot(all_rows, data_dir)
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] != "refresh":
        print(__doc__)
        return 2
    return asyncio.run(cmd_refresh(argv[1] if len(argv) > 1 else None))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_weather.py -v`
Expected: all 10 PASS.

- [ ] **Step 5: Add the justfile recipe**

Insert after the `build-capitals` recipe:

```
# Fetch ERA5-Land daily temperatures for every province capital, then rebuild marts
# `just refresh-weather ITC45` refetches one city (after a coordinate fix)
refresh-weather *province:
    uv run python -m ingestion.weather refresh {{province}}
    just transform
```

- [ ] **Step 6: Commit**

```bash
git add ingestion/weather.py tests/unit/test_weather.py justfile
git commit -m "feat: weather fetch orchestration with null-rate gate

Decade chunking with a resumable raw JSON cache, and a hard 1% null-day gate
per city: ERA5-Land has no ocean cells, so a coastal capital can silently
return nulls and produce a plausible but wrong warming rate.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Synthetic weather sample data

**Files:**
- Modify: `ingestion/sample_data.py`
- Modify: `ingestion/fetch.py:397-404` (the `cmd_sample` function)

**Interfaces:**
- Consumes: `ingestion.weather.WEATHER_COLUMNS`, `ingestion.weather.SNAPSHOT_NAME`.
- Produces: `ingestion.sample_data.SAMPLE_CAPITALS: list[tuple[str, float]]`,
  `ingestion.sample_data.generate_weather_parquet(data_dir: Path, seed: int = 42) -> Path`,
  called from `generate_all`.

**Why 20 cities, not 106:** `generate_all` runs in the `sample_db` fixture on many tests. 106 cities × 19 years × 365 days is ~735k rows per test. Twenty cities is ~139k rows, exercises every code path, and keeps the suite fast.

**Known limitation to preserve:** `sample_data.REGIONS` uses NUTS-2013 codes (`ITH3` Veneto, `ITI1` Toscana, `ITI4` Lazio, `ITH5` Emilia-Romagna) while the real offenders dataflow — and therefore the capitals seed — uses NUTS-2006 (`ITD3`, `ITE1`, `ITE4`, `ITD5`). Eight of the twelve synthetic regions overlap, so `mart_crime_climate` gets 8 regions offline. Do **not** "fix" this by editing `REGIONS`: it would silently change every existing sample-data assertion for no analytical gain.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_sample_data.py`:

```python
def test_sample_weather_covers_20_capitals_with_a_north_south_gradient(tmp_path):
    from ingestion import sample_data, weather

    out = sample_data.generate_weather_parquet(tmp_path, seed=99)
    df = pl.read_parquet(out)

    assert out.name == weather.SNAPSHOT_NAME
    assert df.columns == weather.WEATHER_COLUMNS
    assert df["province_code"].n_unique() == 20
    assert df["t_mean"].null_count() == 0
    # min <= mean <= max must hold on every day, or the marts are meaningless
    assert (df["t_min"] <= df["t_mean"]).all()
    assert (df["t_mean"] <= df["t_max"]).all()

    # Palermo must be warmer on average than Torino.
    means = df.group_by("province_code").agg(pl.col("t_mean").mean().alias("m"))
    by_code = dict(zip(means["province_code"], means["m"], strict=True))
    assert by_code["ITG12"] > by_code["ITC11"]


def test_generate_all_writes_the_weather_snapshot(tmp_path):
    from ingestion import sample_data, weather

    sample_data.generate_all(tmp_path, seed=99)
    assert (tmp_path / weather.SNAPSHOT_NAME).exists()


def test_sample_offenders_include_violent_crime_codes(tmp_path):
    from ingestion import sample_data

    out = sample_data.generate_raw_offenders_csv(tmp_path, seed=99)
    text = out.read_text()
    assert "INTENHOM: intentional homicides" in text
    assert "BLOWS: blows" in text
```

Add `import polars as pl` at the top of the file if it is not already imported.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_sample_data.py -v`
Expected: FAIL — `AttributeError: module 'ingestion.sample_data' has no attribute 'generate_weather_parquet'`

- [ ] **Step 3: Add the generator to `ingestion/sample_data.py`**

Append at the end of the file:

```python
# ------------------------------------------------------------------
# Synthetic daily temperatures, mirroring the real weather_daily.parquet
# schema so the climate marts build offline.
#
# Twenty capitals rather than all 106: generate_all runs in the sample_db
# fixture on many tests, and 106 cities would add ~735k rows per test.
# Latitudes are approximate on purpose — the values are FAKE.

SAMPLE_CAPITALS: list[tuple[str, float]] = [
    ("ITC11", 45.07),  # Torino
    ("ITC16", 44.39),  # Cuneo
    ("ITC33", 44.41),  # Genova
    ("ITC34", 44.11),  # La Spezia
    ("ITC45", 45.46),  # Milano
    ("ITC47", 45.54),  # Brescia
    ("ITD35", 45.44),  # Venezia
    ("ITD55", 44.49),  # Bologna
    ("ITE14", 43.77),  # Firenze
    ("ITE43", 41.89),  # Roma
    ("ITF11", 42.35),  # L'Aquila
    ("ITF13", 42.46),  # Pescara
    ("ITF33", 40.85),  # Napoli
    ("ITF35", 40.68),  # Salerno
    ("ITF42", 41.12),  # Bari
    ("ITF45", 40.35),  # Lecce
    ("ITG12", 38.12),  # Palermo
    ("ITG17", 37.51),  # Catania
    ("ITG25", 40.73),  # Sassari
    ("ITG27", 39.22),  # Cagliari
]

WEATHER_YEARS = list(range(2006, 2025))


def generate_weather_parquet(data_dir: Path, seed: int = 42) -> Path:
    """Daily min/mean/max for 20 capitals: latitude gradient + seasonal cycle
    + a warming trend, so the climate marts have something to aggregate."""
    import math
    from datetime import date, timedelta

    from ingestion.weather import SNAPSHOT_NAME, WEATHER_COLUMNS

    rng = random.Random(seed)
    rows: list[dict] = []
    for code, lat in SAMPLE_CAPITALS:
        # Warmer towards the south; roughly 0.7 C per degree of latitude.
        annual_mean = 26.0 - 0.7 * (lat - 36.0)
        for year in WEATHER_YEARS:
            warming = 0.035 * (year - WEATHER_YEARS[0])
            day = date(year, 1, 1)
            while day.year == year:
                doy = day.timetuple().tm_yday
                seasonal = 9.0 * math.sin(2 * math.pi * (doy - 105) / 365.25)
                mean = annual_mean + warming + seasonal + rng.uniform(-2.5, 2.5)
                spread = rng.uniform(4.0, 9.0)
                rows.append(
                    {
                        "province_code": code,
                        "date": day,
                        "t_min": round(mean - spread / 2, 1),
                        "t_mean": round(mean, 1),
                        "t_max": round(mean + spread / 2, 1),
                    }
                )
                day += timedelta(days=1)

    df = pl.DataFrame(
        rows,
        schema={
            "province_code": pl.Utf8,
            "date": pl.Date,
            "t_min": pl.Float64,
            "t_mean": pl.Float64,
            "t_max": pl.Float64,
        },
    ).select(WEATHER_COLUMNS)
    out = data_dir / SNAPSHOT_NAME
    df.write_parquet(out)
    logger.info("[sample] weather: %d rows -> %s", df.height, out.name)
    return out
```

- [ ] **Step 4: Call it from `generate_all`**

In `ingestion/sample_data.py`, inside `generate_all`, immediately after
`generate_raw_offenders_csv(data_dir / "raw", seed=seed)`, add:

```python
    generate_weather_parquet(data_dir, seed=seed)
```

- [ ] **Step 5: Add violent crime codes to the synthetic offenders CSV**

In `ingestion/sample_data.py`, extend `OFFENDER_CRIMES` (currently at line 272) with the two
violent codes the crime-climate mart needs, using the real ISTAT code and label spellings:

```python
OFFENDER_CRIMES = [
    ("TOT", "total"),  # regression guard: hidden grand-total row (real ISTAT quirk)
    ("THEFT", "theft"),
    ("ROBBERY", "robbery"),
    ("FRAUD", "fraud and cyber fraud"),
    ("INJURIES", "voluntary injuries"),
    ("DRUGS", "drug-related crimes"),
    ("INTENHOM", "intentional homicides"),
    ("BLOWS", "blows"),
]
```

And extend the `base` dict inside `generate_raw_offenders_csv`:

```python
    base = {
        "TOT": 10500,  # grand total = sum of the five original crime types
        "THEFT": 5000,
        "ROBBERY": 900,
        "FRAUD": 1600,
        "INJURIES": 1300,
        "DRUGS": 1700,
        "INTENHOM": 45,
        "BLOWS": 800,
    }
```

- [ ] **Step 6: Write the weather placeholder in `cmd_sample`**

In `ingestion/fetch.py`, `cmd_sample` (line 397), after `ensure_placeholder_snapshots(load_registry())`, add:

```python
    from ingestion.weather import ensure_weather_placeholder

    ensure_weather_placeholder(DATA_DIR)
```

And in `cmd_refresh` (line 297), after `ensure_placeholder_snapshots(registry)`, add the same two lines. The weather snapshot has its own schema, so `ensure_placeholder_snapshots` (which writes the six-column normalized schema) cannot cover it.

- [ ] **Step 7: Run the new tests plus the whole existing suite**

Run: `uv run pytest tests/unit -v`
Expected: the three new tests PASS and **every pre-existing test still passes**. The offenders CSV grew two crime types; if any existing assertion counted crime types, fix that assertion to the new count rather than reverting Step 5.

- [ ] **Step 8: Commit**

```bash
git add ingestion/sample_data.py ingestion/fetch.py tests/unit/test_sample_data.py
git commit -m "feat: synthetic daily temperatures for offline development

20 capitals with a latitude gradient, seasonal cycle and warming trend, so
the climate marts build with no network. Two violent crime codes added to
the synthetic offenders CSV so mart_crime_climate has rows offline.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Climate staging and daily/monthly/annual marts

**Files:**
- Create: `dbt/models/staging/stg_weather.sql`
- Create: `dbt/models/marts/mart_climate_daily.sql`, `mart_climate_monthly.sql`, `mart_climate_annual.sql`
- Create: `dbt/tests/assert_mart_climate_annual_unique_grain.sql`
- Modify: `dbt/models/staging/sources.yml`
- Modify: `dbt/models/marts/schema.yml`

**Interfaces:**
- Consumes: `weather_daily.parquet`, seed `province_capitals`.
- Produces:
  `stg_weather(province_code, province_name, capital_city, region_code, region_name, obs_date, year, month, t_min, t_mean, t_max)` — `year` and `month` are VARCHAR/INTEGER respectively, `year` zero-padded 4-digit.
  `mart_climate_daily` — `stg_weather` columns plus `is_hot_day`, `is_tropical_night`, `is_frost_day` (BOOLEAN).
  `mart_climate_monthly(province_code, province_name, capital_city, region_code, region_name, year, month, t_mean, t_min_mean, t_max_mean, anomaly_1971_2000, anomaly_1981_2010)`.
  `mart_climate_annual(province_code, province_name, capital_city, region_code, region_name, year, t_mean, t_min_mean, t_max_mean, t_min_abs, t_max_abs, hot_days, tropical_nights, frost_days, anomaly_1971_2000, anomaly_1981_2010, days_observed)`.

- [ ] **Step 1: Add the weather source**

In `dbt/models/staging/sources.yml`, append to the `snapshots` source's `tables` list:

```yaml
      - name: weather_daily_pq
        description: >
          Daily min/mean/max 2 m temperature per province capital city from
          Open-Meteo's ERA5-Land archive (1950+). Reanalysis, not station
          observations: right for trends and anomalies, wrong for record extremes.
        meta:
          external_location: >-
            read_parquet('{{ env_var('ITALY_DATA_DIR', 'data') }}/weather_daily.parquet')
```

- [ ] **Step 2: Write `dbt/models/staging/stg_weather.sql`**

```sql
-- Staging: daily temperatures joined to the province-capitals seed, one row
-- per (province, date). The join is an INNER join on purpose: a snapshot row
-- whose province code is not in the seed is a bug, not data to carry forward.
--
-- `year` is VARCHAR to match every ISTAT-derived mart, so joins need no cast.

with raw as (
    select * from {{ source('snapshots', 'weather_daily_pq') }}
),

capitals as (
    select * from {{ ref('province_capitals') }}
)

select
    r.province_code,
    c.province_name,
    c.capital_city,
    c.region_code,
    c.region_name,
    cast(r.date as date)                       as obs_date,
    cast(year(cast(r.date as date)) as varchar) as year,
    month(cast(r.date as date))                as month,
    cast(r.t_min as double)                    as t_min,
    cast(r.t_mean as double)                   as t_mean,
    cast(r.t_max as double)                    as t_max
from raw r
join capitals c on r.province_code = c.province_code
where r.t_mean is not null
```

- [ ] **Step 3: Write `dbt/models/marts/mart_climate_daily.sql`**

```sql
-- Daily climate mart: staging plus the three conventional Italian threshold
-- flags. These read far more plainly to non-specialists than anomalies do.
--
-- Definitions: hot day = daily max >= 30 C; tropical night = daily min >= 20 C;
-- frost day = daily min <= 0 C.

{{ config(
    materialized='external',
    location=env_var('ITALY_DATA_DIR', 'data') ~ '/marts/mart_climate_daily.parquet',
    format='parquet',
) }}

select
    province_code,
    province_name,
    capital_city,
    region_code,
    region_name,
    obs_date,
    year,
    month,
    t_min,
    t_mean,
    t_max,
    (t_max >= 30.0) as is_hot_day,
    (t_min >= 20.0) as is_tropical_night,
    (t_min <= 0.0)  as is_frost_day
from {{ ref('stg_weather') }}
```

- [ ] **Step 4: Write `dbt/models/marts/mart_climate_monthly.sql`**

```sql
-- Monthly climate mart with anomalies against BOTH climate normals ISTAT
-- publishes (1971-2000 and 1981-2010), so the dashboard's numbers can be
-- checked against the official release.
--
-- A baseline is NULL when a province has no data in that window; the anomaly
-- is then NULL too, rather than silently comparing against a partial normal.

{{ config(
    materialized='external',
    location=env_var('ITALY_DATA_DIR', 'data') ~ '/marts/mart_climate_monthly.parquet',
    format='parquet',
) }}

with monthly as (
    select
        province_code,
        any_value(province_name)  as province_name,
        any_value(capital_city)   as capital_city,
        any_value(region_code)    as region_code,
        any_value(region_name)    as region_name,
        year,
        month,
        avg(t_mean) as t_mean,
        avg(t_min)  as t_min_mean,
        avg(t_max)  as t_max_mean
    from {{ ref('mart_climate_daily') }}
    group by province_code, year, month
),

clino as (
    select
        province_code,
        month,
        avg(case when cast(year as integer) between 1971 and 2000 then t_mean end)
            as base_1971_2000,
        avg(case when cast(year as integer) between 1981 and 2010 then t_mean end)
            as base_1981_2010
    from monthly
    group by province_code, month
)

select
    m.province_code,
    m.province_name,
    m.capital_city,
    m.region_code,
    m.region_name,
    m.year,
    m.month,
    round(m.t_mean, 2)     as t_mean,
    round(m.t_min_mean, 2) as t_min_mean,
    round(m.t_max_mean, 2) as t_max_mean,
    round(m.t_mean - c.base_1971_2000, 2) as anomaly_1971_2000,
    round(m.t_mean - c.base_1981_2010, 2) as anomaly_1981_2010
from monthly m
left join clino c
    on m.province_code = c.province_code and m.month = c.month
```

- [ ] **Step 5: Write `dbt/models/marts/mart_climate_annual.sql`**

```sql
-- Annual climate mart.
--
-- Two senses of "minimum" and "maximum" are both published, because they
-- answer different questions and conflating them is the usual error:
--   t_min_mean / t_max_mean = mean of DAILY minima / maxima (ISTAT's definition)
--   t_min_abs  / t_max_abs  = the year's absolute coldest / hottest reading
--
-- `days_observed` is exposed so a partial first or last year is visible rather
-- than plotting as a spurious dip.

{{ config(
    materialized='external',
    location=env_var('ITALY_DATA_DIR', 'data') ~ '/marts/mart_climate_annual.parquet',
    format='parquet',
) }}

with annual as (
    select
        province_code,
        any_value(province_name) as province_name,
        any_value(capital_city)  as capital_city,
        any_value(region_code)   as region_code,
        any_value(region_name)   as region_name,
        year,
        avg(t_mean)  as t_mean,
        avg(t_min)   as t_min_mean,
        avg(t_max)   as t_max_mean,
        min(t_min)   as t_min_abs,
        max(t_max)   as t_max_abs,
        count(*)                                as days_observed,
        sum(case when is_hot_day then 1 else 0 end)         as hot_days,
        sum(case when is_tropical_night then 1 else 0 end)  as tropical_nights,
        sum(case when is_frost_day then 1 else 0 end)       as frost_days
    from {{ ref('mart_climate_daily') }}
    group by province_code, year
),

clino as (
    select
        province_code,
        avg(case when cast(year as integer) between 1971 and 2000 then t_mean end)
            as base_1971_2000,
        avg(case when cast(year as integer) between 1981 and 2010 then t_mean end)
            as base_1981_2010
    from annual
    group by province_code
)

select
    a.province_code,
    a.province_name,
    a.capital_city,
    a.region_code,
    a.region_name,
    a.year,
    round(a.t_mean, 2)     as t_mean,
    round(a.t_min_mean, 2) as t_min_mean,
    round(a.t_max_mean, 2) as t_max_mean,
    round(a.t_min_abs, 1)  as t_min_abs,
    round(a.t_max_abs, 1)  as t_max_abs,
    a.hot_days,
    a.tropical_nights,
    a.frost_days,
    a.days_observed,
    round(a.t_mean - c.base_1971_2000, 2) as anomaly_1971_2000,
    round(a.t_mean - c.base_1981_2010, 2) as anomaly_1981_2010
from annual a
left join clino c on a.province_code = c.province_code
```

- [ ] **Step 6: Write the grain test**

Create `dbt/tests/assert_mart_climate_annual_unique_grain.sql`:

```sql
-- One row per province per year, or every chart double counts.
select province_code, year, count(*) as n
from {{ ref('mart_climate_annual') }}
group by province_code, year
having count(*) > 1
```

- [ ] **Step 7: Add not-null tests to `dbt/models/marts/schema.yml`**

Append to the `models:` list, matching the existing style in that file:

```yaml
  - name: mart_climate_annual
    description: Annual temperature per province capital, with CLINO anomalies.
    columns:
      - name: province_code
        tests: [not_null]
      - name: year
        tests: [not_null]
      - name: t_mean
        tests: [not_null]

  - name: mart_climate_monthly
    description: Monthly temperature per province capital, with CLINO anomalies.
    columns:
      - name: province_code
        tests: [not_null]
      - name: year
        tests: [not_null]
      - name: month
        tests: [not_null]
```

- [ ] **Step 8: Build and verify against sample data**

```bash
uv run python -m ingestion.fetch sample
just transform
```

Expected: the build succeeds and every test passes. Then verify the numbers:

```bash
uv run python -c "
import duckdb
c = duckdb.connect()
a = \"data/marts/mart_climate_annual.parquet\"
print(c.execute(f\"select count(*), count(distinct province_code), min(year), max(year) from '{a}'\").fetchall())
print(c.execute(f\"select capital_city, round(avg(t_mean),1) from '{a}' group by 1 order by 2 desc limit 3\").fetchall())
print(c.execute(f\"select count(*) from '{a}' where t_min_mean > t_max_mean\").fetchall())
"
```

Expected: 20 provinces × 19 years = 380 rows; the three warmest are southern cities (Catania, Palermo, Cagliari or similar); **zero** rows where `t_min_mean > t_max_mean`. Anomalies are all NULL against sample data, because the synthetic series starts in 2006 and never overlaps either CLINO window — that is correct behaviour, not a bug.

- [ ] **Step 9: Commit**

```bash
git add dbt/models/staging/stg_weather.sql dbt/models/staging/sources.yml \
        dbt/models/marts/mart_climate_daily.sql dbt/models/marts/mart_climate_monthly.sql \
        dbt/models/marts/mart_climate_annual.sql dbt/models/marts/schema.yml \
        dbt/tests/assert_mart_climate_annual_unique_grain.sql
git commit -m "feat: climate staging plus daily, monthly and annual marts

Threshold-day flags, mean-of-daily-extremes and absolute extremes as separate
columns, and anomalies against both CLINO baselines ISTAT publishes.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Region rollup and the crime-climate panel

**Files:**
- Create: `dbt/seeds/violent_crime_codes.csv`
- Create: `dbt/models/marts/mart_climate_region.sql`, `mart_crime_climate.sql`
- Create: `dbt/tests/assert_mart_crime_climate_unique_grain.sql`
- Modify: `dbt/dbt_project.yml` (seed column types)
- Modify: `dbt/models/marts/schema.yml`

**Interfaces:**
- Consumes: `mart_climate_daily`, `mart_offenders`, seed `violent_crime_codes`.
- Produces:
  `mart_climate_region(region_code, region_name, year, t_mean, t_min_mean, t_max_mean, hot_days, tropical_nights, frost_days, provinces_covered)`.
  `mart_crime_climate(region_code, region_name, year, summer_tmax, summer_anomaly, offenders, ln_offenders, summer_anomaly_dm, ln_offenders_dm)` where `_dm` are the two-way demeaned values.

- [ ] **Step 1: Create the violent-crime seed**

The real dataflow publishes 59 offence codes. The chosen set is deliberately narrow: heat-aggression theory predicts interpersonal violence, and ISTAT's homicide sub-types (`MAFIAHOM`, `ROBBHOM`, `TERRORHOM`, `INFANTHOM`, `MASSMURD`) nest inside `INTENHOM`, so summing them would double count. `STALK` and `CP612BIS` are both labelled "stalking" and are excluded as suspected duplicates of each other.

Create `dbt/seeds/violent_crime_codes.csv`:

```csv
crime_code,crime_name
INTENHOM,intentional homicides
ATTEMPHOM,attempted homicides
BLOWS,blows
RAPE,sexual violence
MENACE,menaces
KIDNAPP,kidnappings
```

Six codes, not seven. `CP572` (maltreatment in the family) is published only from 2022; including it would put a step change in the outcome series at 2022 that region and year fixed effects cannot absorb, because it is a change in *what is counted*, not in the world.

- [ ] **Step 2: Confirm the two diagnostics (already run, results recorded)**

Both diagnostics behind the seed above were run during pre-flight against the real `mart_offenders.parquet` in the main checkout, because the worktree's `data/` is gitignored and empty. Their results are recorded here; **do not re-run them and do not change the seed based on sample data**, where the crime codes are synthetic.

1. **Homicide sub-types nest inside `INTENHOM`.** At `region_code='IT'`, the five sub-types summed to 225 / 240 / 180 against `INTENHOM` of 758 / 828 / 771 for 2022 / 2023 / 2024. Excluding them is correct.
2. **All six chosen codes are published in all 18 years** (2007-2024), 6 distinct codes present every year, giving 21 regions × 18 years = **378 region-years**.

- [ ] **Step 2b: Understand why the citizenship filter is inverted (read before writing the model)**

This is the single most important detail in this task, and it is the opposite of what the rest of the codebase does.

At region level, ISTAT publishes only **marginal** slices before 2022, not the full cross-tabulation:

| `sex_is_total` | `age_is_total` | `citizenship_is_total` | years available |
|---|---|---|---|
| true | true | **false** | **2007-2024 (18)** |
| false | true | true | 2008-2024 (17) |
| true | true | true | **2022-2024 only (3)** |

The triple-total combination — the obvious one to filter on — exists for **three years**. Filtering on `citizenship_is_total` would silently produce a 63-row panel instead of a 378-row one, and nothing would error.

The 18-year slice splits citizenship into `ITL` and `FRG`, so the model sums **across** the citizenship detail rows to reconstruct the total. That reconstruction was verified exact wherever both representations exist: summing `ITL + FRG` gives 67595 / 66454 / 70521 for 2022 / 2023 / 2024, matching the `TOTAL` rows to the unit.

Hence the `violent` CTE below uses `not o.citizenship_is_total` and sums. This is safe **only** because citizenship is the dimension being summed and its two categories partition the total exactly. Do not generalise the pattern to sex or age.

- [ ] **Step 3: Register the seed's column types**

In `dbt/dbt_project.yml`, under the existing `seeds: italy_dashboard:` block, add:

```yaml
    violent_crime_codes:
      +column_types:
        crime_code: varchar
        crime_name: varchar
```

- [ ] **Step 4: Write `dbt/models/marts/mart_climate_region.sql`**

```sql
-- Region-level climate, as the UNWEIGHTED mean of the member province capitals.
--
-- Not population-weighted: mart_population only covers 2019 onwards, so weights
-- do not exist for 1950-2018, and weighting only the last few years of a
-- 76-year series would be worse than not weighting at all.
--
-- `provinces_covered` makes the sample size behind each regional mean visible;
-- Valle d'Aosta and the two autonomous provinces have exactly one.

{{ config(
    materialized='external',
    location=env_var('ITALY_DATA_DIR', 'data') ~ '/marts/mart_climate_region.parquet',
    format='parquet',
) }}

with per_province as (
    select
        region_code,
        any_value(region_name) as region_name,
        province_code,
        year,
        avg(t_mean) as t_mean,
        avg(t_min)  as t_min_mean,
        avg(t_max)  as t_max_mean,
        sum(case when is_hot_day then 1 else 0 end)        as hot_days,
        sum(case when is_tropical_night then 1 else 0 end) as tropical_nights,
        sum(case when is_frost_day then 1 else 0 end)      as frost_days
    from {{ ref('mart_climate_daily') }}
    group by region_code, province_code, year
)

select
    region_code,
    any_value(region_name)        as region_name,
    year,
    round(avg(t_mean), 2)         as t_mean,
    round(avg(t_min_mean), 2)     as t_min_mean,
    round(avg(t_max_mean), 2)     as t_max_mean,
    round(avg(hot_days), 1)        as hot_days,
    round(avg(tropical_nights), 1) as tropical_nights,
    round(avg(frost_days), 1)      as frost_days,
    count(distinct province_code)  as provinces_covered
from per_province
group by region_code, year
```

- [ ] **Step 5: Write `dbt/models/marts/mart_crime_climate.sql`**

```sql
-- Region x year panel: summer heat against violent offending.
--
-- READ THIS BEFORE QUOTING ANY NUMBER FROM THIS MODEL.
--
-- This is an ECOLOGICAL, ANNUAL, UNDERPOWERED association. It is region-level,
-- so it says nothing about individuals. The heat-aggression literature works at
-- daily and monthly grain; annual data is a far blunter instrument. n is about
-- 21 regions x 18 years = 378.
--
-- The outcome is ln(offender COUNTS), not a rate: mart_offender_rates has no
-- population denominator before 2019, so a rate-based panel would collapse to
-- 21 x 6 = 126 rows. Region fixed effects absorb each region's population
-- LEVEL and year fixed effects absorb the national trend; what survives is
-- differential regional population growth, which is small over 2007-2024 but
-- not zero.
--
-- The two-way within (demeaning) transformation removes fixed regional
-- characteristics -- a hot southern region with its own reporting culture --
-- and shared national shocks such as a legal change or a nationwide hot year.
-- What remains is each region's deviation from its OWN norm. The raw,
-- untransformed columns are kept so the dashboard can show the naive
-- cross-section beside the panel and make the confound visible.

{{ config(
    materialized='external',
    location=env_var('ITALY_DATA_DIR', 'data') ~ '/marts/mart_crime_climate.parquet',
    format='parquet',
) }}

with summer_province as (
    select region_code, province_code, year, avg(t_max) as summer_tmax
    from {{ ref('mart_climate_daily') }}
    where month between 6 and 8
    group by region_code, province_code, year
),

summer_region as (
    select region_code, year, avg(summer_tmax) as summer_tmax
    from summer_province
    group by region_code, year
),

summer_baseline as (
    select
        region_code,
        avg(case when cast(year as integer) between 1981 and 2010 then summer_tmax end)
            as base_summer_tmax
    from summer_region
    group by region_code
),

climate as (
    select
        s.region_code,
        s.year,
        s.summer_tmax,
        s.summer_tmax - b.base_summer_tmax as summer_anomaly
    from summer_region s
    join summer_baseline b on s.region_code = b.region_code
),

-- Violent offenders per region-year.
--
-- NOTE THE INVERTED CITIZENSHIP FILTER -- it is deliberate, and it is the
-- opposite of what every other model here does.
--
-- Before 2022 ISTAT publishes only MARGINAL slices at region level, never the
-- full cross-tabulation. The triple-total combination (sex_is_total AND
-- age_is_total AND citizenship_is_total) exists for 2022-2024 ONLY -- three
-- years. Filtering on it yields a 63-row panel instead of 378, silently.
--
-- The slice that spans all 18 years is sex-total x age-total x citizenship
-- SPLIT, so this sums across the citizenship detail rows to rebuild the total.
-- Verified exact where both representations coexist: ITL + FRG reproduces the
-- TOTAL row to the unit (67595 / 66454 / 70521 for 2022 / 2023 / 2024).
--
-- Safe ONLY because ITL and FRG partition the total exactly. Do not copy this
-- pattern onto sex or age, whose categories do not.
--
-- region_level pins the admin level: the mart mixes country, macro-area,
-- region and province rows, and summing across them would multiply everything.
violent as (
    select
        o.region_code,
        any_value(o.region_name) as region_name,
        o.year,
        sum(o.value) as offenders
    from {{ ref('mart_offenders') }} o
    join {{ ref('violent_crime_codes') }} v on o.crime_code = v.crime_code
    where o.region_level = 'region'
      and o.sex_is_total
      and o.age_is_total
      and not o.citizenship_is_total
      and not o.crime_is_total
    group by o.region_code, o.year
),

panel as (
    select
        v.region_code,
        v.region_name,
        v.year,
        round(c.summer_tmax, 2)    as summer_tmax,
        round(c.summer_anomaly, 3) as summer_anomaly,
        v.offenders,
        ln(v.offenders)            as ln_offenders
    from violent v
    join climate c on v.region_code = c.region_code and v.year = c.year
    where v.offenders > 0
      and c.summer_anomaly is not null
)

select
    region_code,
    region_name,
    year,
    summer_tmax,
    summer_anomaly,
    offenders,
    round(ln_offenders, 4) as ln_offenders,
    -- Two-way within transformation: x - mean_region - mean_year + mean_overall
    round(
        summer_anomaly
        - avg(summer_anomaly) over (partition by region_code)
        - avg(summer_anomaly) over (partition by year)
        + avg(summer_anomaly) over (),
        4
    ) as summer_anomaly_dm,
    round(
        ln_offenders
        - avg(ln_offenders) over (partition by region_code)
        - avg(ln_offenders) over (partition by year)
        + avg(ln_offenders) over (),
        4
    ) as ln_offenders_dm
from panel
```

- [ ] **Step 6: Write the grain test**

Create `dbt/tests/assert_mart_crime_climate_unique_grain.sql`:

```sql
-- One row per region per year: the panel's whole design assumes it.
select region_code, year, count(*) as n
from {{ ref('mart_crime_climate') }}
group by region_code, year
having count(*) > 1
```

- [ ] **Step 7: Add not-null tests to `dbt/models/marts/schema.yml`**

```yaml
  - name: mart_crime_climate
    description: >
      Region x year panel of summer temperature anomaly against violent
      offender counts, with two-way demeaned columns. Ecological, annual,
      underpowered — association only.
    columns:
      - name: region_code
        tests: [not_null]
      - name: year
        tests: [not_null]
      - name: ln_offenders
        tests: [not_null]

  - name: mart_climate_region
    description: Region-level annual climate, unweighted mean of member capitals.
    columns:
      - name: region_code
        tests: [not_null]
      - name: year
        tests: [not_null]
```

- [ ] **Step 8: Build and verify the demeaning is correct**

```bash
just transform
uv run python -c "
import duckdb
c = duckdb.connect()
p = 'data/marts/mart_crime_climate.parquet'
print('rows/regions/years:', c.execute(f\"select count(*), count(distinct region_code), min(year), max(year) from '{p}'\").fetchone())
# A correct two-way within transformation sums to ~0 within every region AND every year.
print('max |region mean|:', c.execute(f\"select max(abs(m)) from (select region_code, avg(summer_anomaly_dm) m from '{p}' group by 1)\").fetchone())
print('max |year mean|  :', c.execute(f\"select max(abs(m)) from (select year, avg(ln_offenders_dm) m from '{p}' group by 1)\").fetchone())
print('slope, r, n:', c.execute(f\"select round(regr_slope(ln_offenders_dm, summer_anomaly_dm),4), round(corr(ln_offenders_dm, summer_anomaly_dm),3), count(*) from '{p}'\").fetchone())
"
```

Expected against sample data: 8 regions (the NUTS-2006/2013 overlap documented in Task 4) × 19 years, so ~152 rows. Both demeaned means must be within about 1e-3 of zero — this is only exactly zero on a fully balanced panel, and rounding to four decimals in SQL adds a little slack. A larger residual means the window partitions are wrong.

**Year coverage is the thing to check hardest.** Print the distinct years:

```bash
uv run python -c "
import duckdb
c = duckdb.connect()
print(c.execute(\"select min(year), max(year), count(distinct year) from 'data/marts/mart_crime_climate.parquet'\").fetchone())
"
```

Against sample data this must span the full synthetic range (2006-2024, 19 years). **If it returns 3 years, the citizenship filter was written as `citizenship_is_total` instead of `not citizenship_is_total`** — re-read Step 2b. Against real data the same check must return 2007-2024, 18 years, 378 rows.

- [ ] **Step 9: Commit**

```bash
git add dbt/seeds/violent_crime_codes.csv dbt/dbt_project.yml \
        dbt/models/marts/mart_climate_region.sql dbt/models/marts/mart_crime_climate.sql \
        dbt/models/marts/schema.yml dbt/tests/assert_mart_crime_climate_unique_grain.sql
git commit -m "feat: region climate rollup and crime-climate panel

Region x year panel of summer temperature anomaly against ln(violent
offenders), two-way demeaned in SQL. Counts rather than rates because
population denominators start only in 2019. Homicide sub-types excluded
after checking they nest inside INTENHOM.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Query layer

**Files:**
- Modify: `italy_dashboard/queries.py`
- Modify: `tests/unit/test_queries.py`

**Interfaces:**
- Consumes: the marts from Tasks 5 and 6.
- Produces, all in `italy_dashboard.queries`:
  `climate_ready() -> bool`,
  `climate_cities() -> list[str]` (capital city names, alphabetical),
  `climate_annual_series(city: str) -> list[Row]` with keys `period, t_mean, t_min, t_max`,
  `climate_stripes(city: str) -> list[Row]` with keys `period, anomaly`,
  `warming_rate_ranking(top_n: int = 20) -> list[Row]` with keys `name, value` (°C/decade),
  `climate_threshold_days(city: str) -> list[Row]` with keys `period, hot_days, tropical_nights, frost_days`,
  `climate_month_heatmap(city: str) -> list[Row]` with keys `period, m1..m12`,
  `climate_distribution(city: str) -> list[Row]` with keys `bucket, early, late`,
  `crime_climate_ready() -> bool`,
  `crime_climate_scatter() -> dict[str, list[Row]]` with keys `raw` and `panel`,
  `crime_climate_stats() -> dict[str, str]` with keys `raw`, `panel`, `n`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_queries.py`:

```python
# ------------------------------------------------------------------ climate


def test_climate_not_ready_without_a_snapshot(missing_db):
    assert q.climate_ready() is False
    assert q.climate_cities() == []
    assert q.climate_annual_series("Roma") == []
    assert q.warming_rate_ranking() == []


def test_climate_cities_are_the_sample_capitals(climate_db):
    cities = q.climate_cities()
    assert len(cities) == 20
    assert cities == sorted(cities)
    assert "Roma" in cities and "Palermo" in cities


def test_climate_annual_series_has_min_mean_max_per_year(climate_db):
    rows = q.climate_annual_series("Roma")
    assert rows
    assert {"period", "t_mean", "t_min", "t_max"} == set(rows[0])
    assert [r["period"] for r in rows] == sorted(r["period"] for r in rows)
    assert all(r["t_min"] <= r["t_mean"] <= r["t_max"] for r in rows)


def test_warming_rate_ranking_is_sorted_descending(climate_db):
    rows = q.warming_rate_ranking(top_n=5)
    assert len(rows) == 5
    values = [r["value"] for r in rows]
    assert values == sorted(values, reverse=True)


def test_threshold_days_are_non_negative_integers(climate_db):
    rows = q.climate_threshold_days("Palermo")
    assert rows
    assert {"period", "hot_days", "tropical_nights", "frost_days"} == set(rows[0])
    assert all(r["hot_days"] >= 0 and r["frost_days"] >= 0 for r in rows)


def test_month_heatmap_has_twelve_month_columns(climate_db):
    rows = q.climate_month_heatmap("Milano")
    assert rows
    assert {"period", *[f"m{i}" for i in range(1, 13)]} == set(rows[0])


def test_distribution_buckets_are_ordered_and_comparable(climate_db):
    rows = q.climate_distribution("Torino")
    assert rows
    assert {"bucket", "early", "late"} == set(rows[0])
    assert [r["bucket"] for r in rows] == sorted(r["bucket"] for r in rows)


def test_crime_climate_scatter_returns_both_views(climate_db):
    out = q.crime_climate_scatter()
    assert set(out) == {"raw", "panel"}
    assert out["panel"]
    assert {"x", "y", "region", "year"} == set(out["panel"][0])


def test_crime_climate_stats_report_n_and_never_a_p_value(climate_db):
    stats = q.crime_climate_stats()
    assert set(stats) == {"raw", "panel", "n"}
    assert stats["n"].isdigit()
    # No significance claim is made anywhere: 21 clusters cannot support one.
    assert "p =" not in stats["panel"] and "p<" not in stats["panel"]
```

Add this fixture to `tests/conftest.py`:

```python
@pytest.fixture
def climate_db(sample_db: Path) -> Path:
    """Sample snapshot with the dbt marts built, for climate query tests."""
    import os
    import subprocess

    root = Path(__file__).resolve().parent.parent
    (sample_db / "marts").mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["uv", "run", "dbt", "build", "--project-dir", "dbt", "--profiles-dir", "dbt"],
        cwd=root,
        env={**os.environ, "ITALY_DATA_DIR": str(sample_db)},
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return sample_db
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_queries.py -k climate -v`
Expected: FAIL — `AttributeError: module 'italy_dashboard.queries' has no attribute 'climate_ready'`

- [ ] **Step 3: Add the query functions**

Append to `italy_dashboard/queries.py`:

```python
# ------------------------------------------------------------------- climate
#
# Temperatures come from Open-Meteo's ERA5-Land reanalysis, sampled at one
# point per province capital city. Reanalysis is a model constrained by
# observations, not a station record: right for trends and anomalies, wrong
# for "the record high in Palermo".

CLIMATE_ANNUAL = "mart_climate_annual"

# Distribution chart: the first and last 30-year windows the series supports.
EARLY_WINDOW = (1951, 1980)
LATE_WINDOW = (1996, 2025)


def climate_ready() -> bool:
    return (MARTS_DIR / f"{CLIMATE_ANNUAL}.parquet").exists()


def climate_cities() -> list[str]:
    rows = _query(
        f"SELECT DISTINCT capital_city AS name FROM {CLIMATE_ANNUAL} "
        "WHERE capital_city IS NOT NULL ORDER BY name"
    )
    return [r["name"] for r in rows]


def climate_annual_series(city: str) -> list[Row]:
    """Annual mean of daily mean, of daily minima and of daily maxima.

    Three series, not one: Italian minima have risen faster than maxima, which
    a mean-only chart hides entirely.
    """
    return _query(
        f"""
        SELECT year AS period, t_mean, t_min_mean AS t_min, t_max_mean AS t_max
        FROM {CLIMATE_ANNUAL}
        WHERE capital_city = ?
        ORDER BY year
        """,
        [city],
    )


def climate_stripes(city: str) -> list[Row]:
    """Anomaly against the 1981-2010 normal, per year — the warming-stripes series."""
    return _query(
        f"""
        SELECT year AS period, anomaly_1981_2010 AS anomaly
        FROM {CLIMATE_ANNUAL}
        WHERE capital_city = ? AND anomaly_1981_2010 IS NOT NULL
        ORDER BY year
        """,
        [city],
    )


def warming_rate_ranking(top_n: int = 20) -> list[Row]:
    """Warming in degrees Celsius per decade per city, fastest first.

    regr_slope over (year, t_mean) is degrees per YEAR; x10 makes it per decade,
    which is how climate trends are conventionally quoted.
    """
    return _query(
        f"""
        SELECT capital_city AS name,
               ROUND(10.0 * regr_slope(t_mean, CAST(year AS INTEGER)), 2) AS value
        FROM {CLIMATE_ANNUAL}
        WHERE t_mean IS NOT NULL
        GROUP BY capital_city
        HAVING COUNT(*) >= 10  -- a slope from a handful of years is noise
        ORDER BY value DESC
        LIMIT {int(top_n)}
        """
    )


def climate_threshold_days(city: str) -> list[Row]:
    return _query(
        f"""
        SELECT year AS period, hot_days, tropical_nights, frost_days
        FROM {CLIMATE_ANNUAL}
        WHERE capital_city = ?
        ORDER BY year
        """,
        [city],
    )


def climate_month_heatmap(city: str) -> list[Row]:
    """Year x month anomalies, pivoted wide — one row per year, m1..m12."""
    months = ", ".join(
        f"ROUND(MAX(CASE WHEN month = {m} THEN anomaly_1981_2010 END), 2) AS m{m}"
        for m in range(1, 13)
    )
    return _query(
        f"""
        SELECT year AS period, {months}
        FROM mart_climate_monthly
        WHERE capital_city = ?
        GROUP BY year
        ORDER BY year
        """,
        [city],
    )


def climate_distribution(city: str) -> list[Row]:
    """Daily max-temperature histogram, early window against late window.

    Counts are normalized to percentages so unequal window lengths (a shorter
    late window near the present) do not make one curve look taller than the
    other for purely arithmetic reasons.
    """
    early_lo, early_hi = EARLY_WINDOW
    late_lo, late_hi = LATE_WINDOW
    return _query(
        """
        WITH d AS (
            SELECT CAST(year AS INTEGER) AS y,
                   CAST(FLOOR(t_max / 2.0) * 2 AS INTEGER) AS bucket
            FROM mart_climate_daily
            WHERE capital_city = ? AND t_max IS NOT NULL
        ),
        tot AS (
            SELECT
                COUNT(*) FILTER (WHERE y BETWEEN ? AND ?) AS n_early,
                COUNT(*) FILTER (WHERE y BETWEEN ? AND ?) AS n_late
            FROM d
        )
        SELECT d.bucket,
               ROUND(100.0 * COUNT(*) FILTER (WHERE y BETWEEN ? AND ?)
                     / NULLIF(ANY_VALUE(tot.n_early), 0), 3) AS early,
               ROUND(100.0 * COUNT(*) FILTER (WHERE y BETWEEN ? AND ?)
                     / NULLIF(ANY_VALUE(tot.n_late), 0), 3) AS late
        FROM d, tot
        GROUP BY d.bucket
        HAVING ANY_VALUE(tot.n_early) > 0 AND ANY_VALUE(tot.n_late) > 0
        ORDER BY d.bucket
        """,
        [city, early_lo, early_hi, late_lo, late_hi, early_lo, early_hi, late_lo, late_hi],
    )


# ------------------------------------------- crime vs temperature (ecological)


def crime_climate_ready() -> bool:
    return (MARTS_DIR / "mart_crime_climate.parquet").exists()


def crime_climate_scatter() -> dict[str, list[Row]]:
    """Both scatters: the naive cross-section and the two-way demeaned panel.

    The raw view is shown deliberately. It largely recovers "the South is hot
    and reports crime differently" — showing it beside the panel makes the
    confound the lesson of the page rather than a footnote nobody reads.
    """
    rows = _query(
        """
        SELECT region_name, year,
               summer_anomaly, ln_offenders,
               summer_anomaly_dm, ln_offenders_dm
        FROM mart_crime_climate
        WHERE summer_anomaly IS NOT NULL AND ln_offenders IS NOT NULL
        ORDER BY region_name, year
        """
    )
    return {
        "raw": [
            {
                "x": r["summer_anomaly"],
                "y": r["ln_offenders"],
                "region": r["region_name"],
                "year": r["year"],
            }
            for r in rows
        ],
        "panel": [
            {
                "x": r["summer_anomaly_dm"],
                "y": r["ln_offenders_dm"],
                "region": r["region_name"],
                "year": r["year"],
            }
            for r in rows
        ],
    }


def crime_climate_stats() -> dict[str, str]:
    """Slope and Pearson r for both views, plus n.

    Deliberately NO p-values and NO confidence intervals. With 21 clusters,
    unclustered standard errors would overstate precision and correct clustered
    ones need machinery this project does not have. A bare slope with an
    explicit "association only" caveat is the honest presentation.
    """
    out = {"raw": "—", "panel": "—", "n": "0"}
    rows = _query(
        """
        SELECT COUNT(*) AS n,
               ROUND(regr_slope(ln_offenders, summer_anomaly), 4) AS raw_slope,
               ROUND(corr(ln_offenders, summer_anomaly), 3) AS raw_r,
               ROUND(regr_slope(ln_offenders_dm, summer_anomaly_dm), 4) AS dm_slope,
               ROUND(corr(ln_offenders_dm, summer_anomaly_dm), 3) AS dm_r
        FROM mart_crime_climate
        WHERE summer_anomaly IS NOT NULL AND ln_offenders IS NOT NULL
        """
    )
    if not rows or not rows[0]["n"]:
        return out
    r = rows[0]
    out["n"] = str(int(r["n"]))
    if r["raw_slope"] is not None:
        out["raw"] = f"slope = {r['raw_slope']:+.3f}, r = {r['raw_r']:+.2f}"
    if r["dm_slope"] is not None:
        out["panel"] = f"slope = {r['dm_slope']:+.3f}, r = {r['dm_r']:+.2f}"
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_queries.py -v`
Expected: all climate tests PASS and every pre-existing query test still passes.

- [ ] **Step 5: Commit**

```bash
git add italy_dashboard/queries.py tests/unit/test_queries.py tests/conftest.py
git commit -m "feat: climate and crime-climate query layer

Warming series, stripes, per-city warming rate, threshold days, monthly
anomaly heatmap and distribution shift, plus both crime-climate scatters.
Statistics report slope, r and n only — no p-values, by design.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Climate page

**Files:**
- Create: `italy_dashboard/pages/climate.py`
- Modify: `italy_dashboard/state.py`, `italy_dashboard/translations.py`, `italy_dashboard/components.py`, `italy_dashboard/italy_dashboard.py`
- Modify: `tests/integration/test_app_pages.py`

**Interfaces:**
- Consumes: the `queries` functions from Task 7.
- Produces: `italy_dashboard.state.ClimateState` with vars `city`, `city_options`, `annual`, `stripes`, `ranking`, `thresholds`, `distribution`, `mart_ready`, and events `load`, `set_city`; `italy_dashboard.pages.climate.climate_page() -> rx.Component`; route `/climate`.

- [ ] **Step 1: Write the failing test**

In `tests/integration/test_app_pages.py`, add `("italy_dashboard.pages.climate", "climate_page")` to the parametrize list, and add `"climate"` to the expected route set in `test_app_registers_all_routes`.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/integration/test_app_pages.py -v -m integration`
Expected: FAIL — `ModuleNotFoundError: No module named 'italy_dashboard.pages.climate'`

- [ ] **Step 3: Add translations**

In `italy_dashboard/translations.py`, add to `EN`:

```python
    "nav_climate": "Climate",
    "climate_title": "Climate",
    "city": "City",
    "warming_title": "Annual temperature",
    "warming_sub": (
        "Mean of daily mean, minimum and maximum, per year. ERA5-Land "
        "reanalysis sampled at the province capital — not a station record."
    ),
    "t_mean": "Mean",
    "t_min": "Min (mean of daily minima)",
    "t_max": "Max (mean of daily maxima)",
    "stripes_title": "Anomaly against the 1981-2010 normal",
    "stripes_sub": "Degrees Celsius above or below the city's own 1981-2010 average",
    "ranking_title": "Fastest-warming cities",
    "ranking_sub": "Degrees Celsius per decade, ordinary least squares over annual means",
    "thresholds_title": "Hot days, tropical nights and frost days",
    "thresholds_sub": (
        "Days per year with max >= 30 C, min >= 20 C and min <= 0 C"
    ),
    "hot_days": "Hot days",
    "tropical_nights": "Tropical nights",
    "frost_days": "Frost days",
    "distribution_title": "Distribution of daily maxima",
    "distribution_sub": "Share of days per 2 C bucket, 1951-1980 against 1996-2025",
    "dist_early": "1951-1980",
    "dist_late": "1996-2025",
    "anomaly": "Anomaly (C)",
    "degrees_per_decade": "C / decade",
    "no_climate": (
        "No temperature data yet. Run  just refresh-weather  (or  just sample  "
        "for synthetic dev data), then reload."
    ),
```

Add the Italian equivalents to `IT` with the same keys:

```python
    "nav_climate": "Clima",
    "climate_title": "Clima",
    "city": "Città",
    "warming_title": "Temperatura annuale",
    "warming_sub": (
        "Media delle medie, delle minime e delle massime giornaliere, per anno. "
        "Rianalisi ERA5-Land campionata nel capoluogo — non è una serie da stazione."
    ),
    "t_mean": "Media",
    "t_min": "Minima (media delle minime giornaliere)",
    "t_max": "Massima (media delle massime giornaliere)",
    "stripes_title": "Anomalia rispetto alla norma 1981-2010",
    "stripes_sub": "Gradi Celsius sopra o sotto la media 1981-2010 della città",
    "ranking_title": "Città che si scaldano più in fretta",
    "ranking_sub": "Gradi Celsius per decennio, minimi quadrati sulle medie annuali",
    "thresholds_title": "Giorni caldi, notti tropicali e giorni di gelo",
    "thresholds_sub": (
        "Giorni all'anno con massima >= 30 C, minima >= 20 C e minima <= 0 C"
    ),
    "hot_days": "Giorni caldi",
    "tropical_nights": "Notti tropicali",
    "frost_days": "Giorni di gelo",
    "distribution_title": "Distribuzione delle massime giornaliere",
    "distribution_sub": "Quota di giorni per intervallo di 2 C, 1951-1980 contro 1996-2025",
    "dist_early": "1951-1980",
    "dist_late": "1996-2025",
    "anomaly": "Anomalia (C)",
    "degrees_per_decade": "C / decennio",
    "no_climate": (
        "Nessun dato di temperatura. Esegui  just refresh-weather  (oppure  just sample  "
        "per dati sintetici di sviluppo), poi ricarica."
    ),
```

- [ ] **Step 4: Add `ClimateState` to `italy_dashboard/state.py`**

```python
class ClimateState(AppState):
    """Climate explorer over the mart_climate_* marts."""

    city_options: list[str] = []
    city: str = ""
    annual: list[Row] = []
    stripes: list[Row] = []
    ranking: list[Row] = []
    thresholds: list[Row] = []
    distribution: list[Row] = []
    mart_ready: bool = False

    @rx.event
    def load(self):
        self.load_shared()
        self.mart_ready = q.climate_ready()
        if not self.mart_ready:
            return
        self.city_options = q.climate_cities()
        # Roma is the default when present: a familiar reference point beats an
        # alphabetically-first city nobody has intuitions about.
        if self.city not in self.city_options:
            self.city = "Roma" if "Roma" in self.city_options else self.city_options[0]
        self.ranking = q.warming_rate_ranking(top_n=20)
        self._refresh()

    @rx.event
    def set_city(self, value: str):
        self.city = value
        self._refresh()

    def _refresh(self):
        self.annual = q.climate_annual_series(self.city)
        self.stripes = q.climate_stripes(self.city)
        self.thresholds = q.climate_threshold_days(self.city)
        self.distribution = q.climate_distribution(self.city)
```

- [ ] **Step 5: Add the nav link**

In `italy_dashboard/components.py`, add to `NAV_LINKS` after the population entry:

```python
(("nav_climate", "/climate"),)
```

- [ ] **Step 6: Write `italy_dashboard/pages/climate.py`**

The month-heatmap view from the spec is deliberately **not** built here: Recharts has no heatmap mark, and the anomaly-stripes bar chart already carries the same "warming accelerates" message with a mark the chart library supports natively. The monthly mart still exists for the notebook and for a later choropleth. This is a scope reduction, recorded here rather than silently dropped.

```python
"""Climate page: warming trend, anomalies, per-city warming rate, thresholds."""

import reflex as rx

from italy_dashboard import theme
from italy_dashboard.components import (
    bar_chart,
    card,
    data_table,
    h_bar_chart,
    line_chart,
    shell,
)
from italy_dashboard.i18n import t
from italy_dashboard.state import ClimateState


def _city_select() -> rx.Component:
    return rx.hstack(
        rx.text(t("city"), color=theme.INK_SECONDARY, font_size="0.9em"),
        rx.select(
            ClimateState.city_options,
            value=ClimateState.city,
            on_change=ClimateState.set_city,
            width="260px",
        ),
        align="center",
        spacing="3",
    )


def climate_page() -> rx.Component:
    return shell(
        rx.hstack(
            rx.heading(t("climate_title"), size="6", color=theme.INK_PRIMARY),
            rx.spacer(),
            _city_select(),
            width="100%",
            align="center",
        ),
        rx.cond(
            ClimateState.mart_ready,
            rx.vstack(
                card(
                    t("warming_title"),
                    t("warming_sub"),
                    line_chart(
                        ClimateState.annual,
                        [
                            ("t_max", t("t_max"), theme.SERIES_2),
                            ("t_mean", t("t_mean"), theme.SERIES_1),
                            ("t_min", t("t_min"), theme.SERIES_3),
                        ],
                    ),
                    data_table(
                        ClimateState.annual,
                        [
                            ("period", t("year")),
                            ("t_min", t("t_min")),
                            ("t_mean", t("t_mean")),
                            ("t_max", t("t_max")),
                        ],
                    ),
                ),
                card(
                    t("stripes_title"),
                    t("stripes_sub"),
                    bar_chart(ClimateState.stripes, "anomaly", "period", theme.SERIES_2),
                ),
                card(
                    t("ranking_title"),
                    t("ranking_sub"),
                    h_bar_chart(ClimateState.ranking, "value", "name", theme.SERIES_1),
                    data_table(
                        ClimateState.ranking,
                        [("name", t("city")), ("value", t("degrees_per_decade"))],
                    ),
                ),
                card(
                    t("thresholds_title"),
                    t("thresholds_sub"),
                    line_chart(
                        ClimateState.thresholds,
                        [
                            ("hot_days", t("hot_days"), theme.SERIES_2),
                            ("tropical_nights", t("tropical_nights"), theme.SERIES_1),
                            ("frost_days", t("frost_days"), theme.SERIES_3),
                        ],
                    ),
                ),
                card(
                    t("distribution_title"),
                    t("distribution_sub"),
                    line_chart(
                        ClimateState.distribution,
                        [
                            ("early", t("dist_early"), theme.SERIES_1),
                            ("late", t("dist_late"), theme.SERIES_2),
                        ],
                    ),
                ),
                spacing="5",
                width="100%",
            ),
            rx.callout(t("no_climate"), icon="triangle_alert", color_scheme="orange", width="100%"),
        ),
    )
```

Note: the distribution chart's x-axis is `period` by convention in `line_chart`, but the data key is `bucket`. Fix by aliasing in the query — change `SELECT d.bucket,` to `SELECT d.bucket AS period,` and `ORDER BY d.bucket` to `ORDER BY period` in `climate_distribution`, and update the Task 7 test's expected key set from `{"bucket", "early", "late"}` to `{"period", "early", "late"}`. Do this now, in this step, rather than adding an x-key parameter to `line_chart`.

- [ ] **Step 7: Register the route**

In `italy_dashboard/italy_dashboard.py`, import `climate_page` and `ClimateState`, then add:

```python
app.add_page(
    climate_page, route="/climate", title="Climate · Italy Dashboard", on_load=ClimateState.load
)
```

- [ ] **Step 8: Run the tests**

Run: `uv run pytest tests/integration/test_app_pages.py -v -m integration && uv run pytest tests/unit/test_queries.py -k distribution -v`
Expected: PASS.

- [ ] **Step 9: Verify in the browser**

Run: `just sample && just run`

Open `http://localhost:3000/climate`. Confirm: the city selector lists 20 cities; the warming chart shows three separated lines with max above mean above min; the ranking bar chart is sorted; switching city changes every chart. Anomaly and stripes charts will be **empty** against sample data (the synthetic series starts in 2006 and never overlaps the 1981-2010 normal) — that is expected and is not a bug.

- [ ] **Step 10: Commit**

```bash
git add italy_dashboard/pages/climate.py italy_dashboard/state.py \
        italy_dashboard/translations.py italy_dashboard/components.py \
        italy_dashboard/italy_dashboard.py italy_dashboard/queries.py \
        tests/integration/test_app_pages.py tests/unit/test_queries.py
git commit -m "feat: climate page

Warming trend with min/mean/max, anomaly stripes, fastest-warming city
ranking, threshold days and the distribution shift. The month x year heatmap
is deferred: Recharts has no heatmap mark and the stripes carry the same
message.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: Crime versus temperature page

**Files:**
- Create: `italy_dashboard/pages/climate_crime.py`
- Modify: `italy_dashboard/state.py`, `italy_dashboard/translations.py`, `italy_dashboard/components.py`, `italy_dashboard/italy_dashboard.py`
- Modify: `tests/integration/test_app_pages.py`

**Interfaces:**
- Consumes: `queries.crime_climate_scatter`, `queries.crime_climate_stats`, `queries.crime_climate_ready`.
- Produces: `italy_dashboard.state.ClimateCrimeState` with vars `raw_points`, `panel_points`, `stat_raw`, `stat_panel`, `stat_n`, `mart_ready`, and event `load`; `italy_dashboard.pages.climate_crime.climate_crime_page() -> rx.Component`; route `/climate-crime`.

- [ ] **Step 1: Write the failing test**

In `tests/integration/test_app_pages.py`, add `("italy_dashboard.pages.climate_crime", "climate_crime_page")` to the parametrize list and `"climate-crime"` to the expected routes.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/integration/test_app_pages.py -v -m integration`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Add translations**

Add to `EN`:

```python
    "nav_climate_crime": "Climate × Crime",
    "climate_crime_title": "Summer heat and violent crime",
    "cc_raw_title": "Naive view: raw cross-section",
    "cc_raw_sub": (
        "Every region-year, untransformed. This mostly recovers that southern "
        "regions are hotter and report crime differently — a confound, not a finding."
    ),
    "cc_panel_title": "Panel view: within-region deviation",
    "cc_panel_sub": (
        "Region and year fixed effects removed, so each point is a region's "
        "deviation from its own norm in a year that was unusual nationally."
    ),
    "cc_x": "Summer max-temperature anomaly (C)",
    "cc_y": "ln(violent offenders)",
    "cc_stat_raw": "Raw",
    "cc_stat_panel": "Panel",
    "cc_stat_n": "Observations",
    "cc_caveat": (
        "Association only. This is an ECOLOGICAL comparison: it is region-level "
        "and says nothing about individuals. It is ANNUAL, while the "
        "heat-aggression literature works at daily and monthly grain. It is "
        "UNDERPOWERED, bounded by ISTAT publishing province-level offenders only "
        "from 2022. The outcome is offender counts, not rates, because population "
        "denominators start in 2019; region fixed effects absorb the population "
        "level but not differential regional growth. No p-values or confidence "
        "intervals are shown: with 21 clusters they would overstate precision."
    ),
    "no_climate_crime": (
        "The crime-climate panel needs both the offenders mart and temperature "
        "data. Run  just refresh  and  just refresh-weather  (or  just sample), "
        "then reload."
    ),
```

Add to `IT`:

```python
    "nav_climate_crime": "Clima × Criminalità",
    "climate_crime_title": "Caldo estivo e criminalità violenta",
    "cc_raw_title": "Vista ingenua: sezione trasversale grezza",
    "cc_raw_sub": (
        "Ogni regione-anno, senza trasformazioni. Ritrova soprattutto che le "
        "regioni del Sud sono più calde e denunciano in modo diverso: un "
        "fattore confondente, non un risultato."
    ),
    "cc_panel_title": "Vista panel: deviazione entro regione",
    "cc_panel_sub": (
        "Effetti fissi di regione e anno rimossi: ogni punto è lo scostamento "
        "di una regione dalla propria norma in un anno anomalo a livello nazionale."
    ),
    "cc_x": "Anomalia della massima estiva (C)",
    "cc_y": "ln(autori di reati violenti)",
    "cc_stat_raw": "Grezzo",
    "cc_stat_panel": "Panel",
    "cc_stat_n": "Osservazioni",
    "cc_caveat": (
        "Solo associazione. Confronto ECOLOGICO: è a livello regionale e non "
        "dice nulla sugli individui. È ANNUALE, mentre la letteratura su caldo "
        "e aggressività lavora su scala giornaliera e mensile. È POCO POTENTE, "
        "limitato dal fatto che ISTAT pubblica gli autori a livello provinciale "
        "solo dal 2022. L'esito è il conteggio degli autori, non un tasso, "
        "perché i denominatori di popolazione partono dal 2019; gli effetti "
        "fissi di regione assorbono il livello della popolazione ma non la "
        "crescita differenziale. Non sono mostrati p-value né intervalli di "
        "confidenza: con 21 cluster sovrastimerebbero la precisione."
    ),
    "no_climate_crime": (
        "Il panel clima-criminalità richiede sia il mart degli autori sia i dati "
        "di temperatura. Esegui  just refresh  e  just refresh-weather  (oppure  "
        "just sample), poi ricarica."
    ),
```

- [ ] **Step 4: Add `ClimateCrimeState` to `italy_dashboard/state.py`**

```python
class ClimateCrimeState(AppState):
    """Region x year panel: summer heat against violent offending."""

    raw_points: list[Row] = []
    panel_points: list[Row] = []
    stat_raw: str = "—"
    stat_panel: str = "—"
    stat_n: str = "0"
    mart_ready: bool = False

    @rx.event
    def load(self):
        self.load_shared()
        self.mart_ready = q.crime_climate_ready()
        if not self.mart_ready:
            return
        scatter = q.crime_climate_scatter()
        self.raw_points = scatter["raw"]
        self.panel_points = scatter["panel"]
        stats = q.crime_climate_stats()
        self.stat_raw = stats["raw"]
        self.stat_panel = stats["panel"]
        self.stat_n = stats["n"]
```

- [ ] **Step 5: Add the nav link**

In `italy_dashboard/components.py`, add to `NAV_LINKS` after the climate entry:

```python
(("nav_climate_crime", "/climate-crime"),)
```

- [ ] **Step 6: Write `italy_dashboard/pages/climate_crime.py`**

```python
"""Summer heat against violent crime: the naive view beside the panel view.

Both scatters are shown on purpose. The raw one largely recovers "the South is
hot and reports crime differently"; putting it next to the demeaned panel makes
the confound the lesson of the page rather than a footnote nobody reads.
"""

import reflex as rx

from italy_dashboard import theme
from italy_dashboard.components import card, scatter_chart, shell, stat_tile
from italy_dashboard.i18n import t
from italy_dashboard.state import ClimateCrimeState


def climate_crime_page() -> rx.Component:
    return shell(
        rx.heading(t("climate_crime_title"), size="6", color=theme.INK_PRIMARY),
        rx.cond(
            ClimateCrimeState.mart_ready,
            rx.vstack(
                rx.hstack(
                    stat_tile(t("cc_stat_panel"), ClimateCrimeState.stat_panel, t("cc_y")),
                    stat_tile(t("cc_stat_raw"), ClimateCrimeState.stat_raw, t("cc_y")),
                    stat_tile(t("cc_stat_n"), ClimateCrimeState.stat_n, t("cc_x")),
                    spacing="4",
                    width="100%",
                    wrap="wrap",
                ),
                card(
                    t("cc_panel_title"),
                    t("cc_panel_sub"),
                    scatter_chart(
                        [(ClimateCrimeState.panel_points, t("cc_panel_title"), theme.SERIES_1)],
                        x_key="x",
                        y_key="y",
                        x_label=t("cc_x"),
                        y_label=t("cc_y"),
                        label_key="region",
                        label_name=t("region"),
                    ),
                ),
                card(
                    t("cc_raw_title"),
                    t("cc_raw_sub"),
                    scatter_chart(
                        [(ClimateCrimeState.raw_points, t("cc_raw_title"), theme.SERIES_2)],
                        x_key="x",
                        y_key="y",
                        x_label=t("cc_x"),
                        y_label=t("cc_y"),
                        label_key="region",
                        label_name=t("region"),
                    ),
                ),
                rx.callout(t("cc_caveat"), icon="info", color_scheme="gray", width="100%"),
                spacing="5",
                width="100%",
            ),
            rx.callout(
                t("no_climate_crime"),
                icon="triangle_alert",
                color_scheme="orange",
                width="100%",
            ),
        ),
    )
```

- [ ] **Step 7: Register the route**

In `italy_dashboard/italy_dashboard.py`, import `climate_crime_page` and `ClimateCrimeState`, then add:

```python
app.add_page(
    climate_crime_page,
    route="/climate-crime",
    title="Climate × Crime · Italy Dashboard",
    on_load=ClimateCrimeState.load,
)
```

- [ ] **Step 8: Run the full check**

Run: `just check`
Expected: lint clean, typecheck clean, all tests pass.

- [ ] **Step 9: Verify in the browser**

Run: `just sample && just run`, open `http://localhost:3000/climate-crime`.

Confirm: both scatters render with points; the panel scatter is centred near the origin on both axes (that is what demeaning does) while the raw one is not; the caveat callout is visible without scrolling past the charts; the stat tiles show a slope, an r and an n.

- [ ] **Step 10: Commit**

```bash
git add italy_dashboard/pages/climate_crime.py italy_dashboard/state.py \
        italy_dashboard/translations.py italy_dashboard/components.py \
        italy_dashboard/italy_dashboard.py tests/integration/test_app_pages.py
git commit -m "feat: climate vs crime panel page

Naive cross-section beside the two-way demeaned panel, so the confound is the
lesson rather than a footnote. Slope, r and n only — no p-values with 21
clusters.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: Documentation

**Files:**
- Modify: `docs/02-architecture.md`, `docs/04-datasets.md`, `docs/07-methodology.md`, `docs/11-roadmap.md`

- [ ] **Step 1: Update `docs/04-datasets.md`**

The file opens with "All from ISTAT's SDMX API" — that is now false. Change that opening line to note that temperature comes from Open-Meteo, and add a section:

```markdown
## weather_daily — temperature (non-ISTAT)

**Source** [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api),
ERA5-Land reanalysis, 0.1° (≈11 km), **1950 to present**. Free, no API key,
**non-commercial licence** — if this dashboard ever becomes commercial, switch
to Copernicus CDS ERA5-Land or Open-Meteo's paid tier.

One point per province capital city (106 capitals, `dbt/seeds/province_capitals.csv`),
daily `temperature_2m_max/min/mean`. `models=era5_land` is pinned explicitly:
Open-Meteo's default "best match" switches models across a long series and
would inject discontinuities indistinguishable from real climate signal.

Fetch with `just refresh-weather`, or `just refresh-weather ITC45` for one city.
Raw JSON is cached per city per decade under `data/raw/weather/`, so an
interrupted run resumes.

Feeds `mart_climate_daily`, `mart_climate_monthly`, `mart_climate_annual`,
`mart_climate_region` and `mart_crime_climate`.

### Why not ISTAT

ISTAT publishes *Temperatura e precipitazione dei comuni capoluogo di provincia*,
but the machine-readable series for all capitals covers 2006 onwards only; the
1971-2022 series exists for about 27 regional capitals and is published as PDF
and Excel, not through the SDMX API. Neither reaches 1950 at province grain.
```

- [ ] **Step 2: Update `docs/02-architecture.md`**

Add the second fetcher to the mermaid diagram, after the ISTAT node:

```
    W["Open-Meteo archive API<br/>ERA5-Land, 1950+"] -->|"just refresh-weather"| X["data/raw/weather/*.json"]
    X --> C
```

And add a paragraph under "Design decisions and their reasons":

```markdown
**`ingestion/` is no longer ISTAT-only.** Temperature comes from Open-Meteo,
because no ISTAT source has province-level climate before 2006. The two
fetchers share one output contract — write a parquet snapshot into `data/` —
so everything downstream is unchanged. `ingestion/openmeteo.py` is the HTTP
client, `ingestion/weather.py` the orchestration, mirroring the
`sdmx_client.py` / `fetch.py` split.
```

- [ ] **Step 3: Update `docs/07-methodology.md`**

Add a section:

```markdown
## Temperature

**Reanalysis, not observations.** ERA5-Land is a physical model constrained by
observations. It is right for trends, anomalies and cross-city comparison, and
wrong for "the record high in Palermo". Do not present it as a station record.

**Point sampling, not area means.** One 0.1° cell at each province capital.
That is not the province's mean temperature and it carries urban heat island
bias. ISTAT samples the same way, so results stay comparable to the official
series.

**Region rollups are unweighted.** The plain mean of member province capitals.
`mart_population` covers only 2019 onwards, so population weights do not exist
for 1950-2018, and weighting the last few years of a 76-year series would be
worse than not weighting at all.

**Two senses of minimum and maximum.** `t_min_mean` / `t_max_mean` are the mean
of daily minima / maxima, ISTAT's definition. `t_min_abs` / `t_max_abs` are the
year's absolute extremes. They answer different questions; conflating them is
the usual error.

## Crime and temperature

The panel is region × year, 2007-2024, n ≈ 378. Province-level offenders exist
only from 2022, so a province panel is not possible.

The outcome is `ln(violent offender counts)`, not a rate: population
denominators start in 2019, and a rate-based panel would collapse to 126
observations. Region fixed effects absorb each region's population level; what
survives is differential regional population growth.

A two-way within transformation removes fixed regional characteristics and
shared national shocks. The naive cross-section is shown beside it deliberately,
because it largely recovers "the South is hot and reports crime differently".

Slope, Pearson r and n are reported. **No p-values, no confidence intervals.**
With 21 clusters, unclustered standard errors overstate precision, and correct
clustered ones need machinery this project does not have. The association is
ecological and annual, and a weak or null result is a legitimate finding.
```

- [ ] **Step 4: Update `docs/11-roadmap.md`**

Remove nothing; add:

```markdown
**Precipitation** — the Open-Meteo fetcher already exists; adding
`precipitation_sum` to `DAILY_VARS` and one mart column is most of the work.

**Monthly inflation × temperature** — statistically the strongest available
cross-phenomenon analysis, because inflation is the one monthly series. Needs
an ISTAT re-fetch with the food ECOICOP subgroup instead of all-items.

**Month × year anomaly heatmap** — deferred from the climate page because
Recharts has no heatmap mark. `mart_climate_monthly` already holds the data.
```

- [ ] **Step 5: Verify the docs build**

Run: `uv run zensical build`
Expected: builds with no broken-link warnings.

- [ ] **Step 6: Commit**

```bash
git add docs/
git commit -m "docs: temperature source, methodology and caveats

Records the non-commercial licence constraint, the reanalysis and
point-sampling caveats, and why the crime panel uses counts rather than rates.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage.** Every spec section maps to a task: territory model and seed → Task 1; source and client → Task 2; ingestion, chunking, cache and null gate → Task 3; sample data → Task 4; the six dbt models → Tasks 5 and 6; the climate page's six views → Task 8 (five built, the month heatmap explicitly deferred with its reason recorded); the crime page → Task 9; testing → distributed through every task; documentation → Task 10.

**Two deliberate deviations from the spec, both recorded in the plan text:**
1. The month × year anomaly heatmap is deferred. Recharts, the chart library already in the project, has no heatmap mark, and the anomaly stripes carry the same message. `mart_climate_monthly` is still built, so the view can be added later without rework.
2. `mart_climate_region` is built but no page reads it yet. It is a dependency-free rollup that the crime panel's logic mirrors, and the roadmap's choropleth work will consume it directly.

**Execution order is 2, 1, 3, 4, 5, 6, 7, 8, 9, 10.** `ingestion/capitals.py` imports `ingestion/openmeteo.py`, so the client is built first and the seed second. Everything after Task 1 runs in numeric order.

**Amended during pre-flight**, after running the plan's own diagnostics against the real `mart_offenders.parquet`:
- The violent-crime seed dropped to six codes. `CP572` is published only from 2022 and would put a step change in the outcome series that fixed effects cannot absorb.
- `mart_crime_climate`'s citizenship filter is **inverted** (`not citizenship_is_total`, summing `ITL + FRG`). Before 2022 ISTAT publishes only marginal slices at region level; the triple-total combination exists for three years, so the obvious filter would have silently produced a 63-row panel. The 18-year slice splits citizenship, and `ITL + FRG` was verified to reproduce the `TOTAL` row exactly. See Task 6 Step 2b.

**Type consistency.** `year` is VARCHAR in `stg_weather`, every climate mart and `mart_crime_climate`, matching `mart_offenders`, so the Task 6 join needs no cast. `month` is INTEGER throughout. `province_code` is the join key between the snapshot and the seed; `region_code` is the join key between the climate marts and the crime marts. Query functions return `period` as the x-axis key everywhere, which is why Task 8 Step 6 aliases `bucket` to `period` and fixes the corresponding Task 7 test in the same step.
