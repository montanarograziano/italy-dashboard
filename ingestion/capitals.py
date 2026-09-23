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
    # Filled by `just seed-elevations` (ingestion/elevation.py), not here.
    "elevation_m",
    "cell_elevation_m",
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
    logger.info(
        "Wrote %d rows to %s. Elevation columns are EMPTY: run `just seed-elevations` "
        "before `just transform` (dbt rejects a seed without them), then REVIEW.",
        len(rows),
        path,
    )
    return path


def main(argv: list[str]) -> int:
    if argv:
        print(__doc__)
        return 2
    asyncio.run(build_seed())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
