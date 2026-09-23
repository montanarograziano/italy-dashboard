"""Fill the two elevation columns of the province-capitals seed.

ERA5-Land is a 0.1 degree grid, and a grid cell's temperature is the
temperature at the cell's mean model orography, not at the city. Around the
Alps that gap is over a kilometre (Aosta sits at 583 m, its cell at ~1,800 m),
so raw cell values read up to 8 C too cold. stg_weather corrects every daily
value with a standard lapse rate, which needs, per capital:

- ``elevation_m``: the city centre's height, from the Open-Meteo geocoder's
  GeoNames record (the seed coordinate is NOT used: coastal capitals were
  nudged onto inland cells, where a DEM lookup would return a hillside);
- ``cell_elevation_m``: the ERA5-Land orography (geopotential / g) of the grid
  cell nearest the seed coordinate, which is the cell the ARCO point API and
  Open-Meteo (with ``elevation=nan``) both return.

Run with `just seed-elevations`, then REVIEW and COMMIT the seed. Needs the
`cds` extra and a CDS account (same as the ARCO backfill).
"""

from __future__ import annotations

import asyncio
import csv
import logging
import sys
from pathlib import Path
from typing import Any

from ingestion.capitals import SEED_COLUMNS, SEED_PATH
from ingestion.cds import ITALY_BBOX, _new_client, _require_xarray
from ingestion.openmeteo import OpenMeteoClient
from ingestion.weather import DATA_DIR

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ingestion.elevation")

STANDARD_GRAVITY = 9.80665  # m/s^2, the constant ECMWF uses for z -> height
OROGRAPHY_DATASET_ID = "reanalysis-era5-land"
# ERA5-Land geopotential is time-invariant; any one valid timestep returns it.
OROGRAPHY_REQUEST: dict[str, Any] = {
    "variable": ["geopotential"],
    "year": "2020",
    "month": "01",
    "day": "01",
    "time": "00:00",
    "area": list(ITALY_BBOX),
    "data_format": "netcdf",
    "download_format": "unarchived",
}
# Half the diagonal of a 0.1 degree cell: a "nearest" cell farther than this
# means the seed point fell outside the downloaded grid.
MAX_CELL_OFFSET_DEG = 0.071


def orography_path(data_dir: Path = DATA_DIR) -> Path:
    return data_dir / "raw" / "cds" / "era5_land_geopotential.nc"


def fetch_orography(path: Path) -> Path:
    """Download the ERA5-Land geopotential once; reuse the cached file after."""
    if path.exists():
        logger.info("orography cached: %s", path)
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    logger.info("requesting ERA5-Land geopotential from CDS...")
    try:
        _new_client().retrieve(OROGRAPHY_DATASET_ID, OROGRAPHY_REQUEST, str(tmp))
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(path)
    return path


def cell_elevation(orography: Any, lat: float, lon: float) -> float:
    """Model orography (m) of the ERA5-Land cell nearest (lat, lon)."""
    cell = orography.sel(latitude=lat, longitude=lon, method="nearest")
    offset = max(abs(float(cell.latitude) - lat), abs(float(cell.longitude) - lon))
    if offset > MAX_CELL_OFFSET_DEG:
        raise ValueError(
            f"Nearest orography cell to ({lat}, {lon}) is {offset:.3f} deg away: "
            "the point is outside the downloaded grid."
        )
    return float(cell) / STANDARD_GRAVITY


def load_orography(path: Path) -> Any:
    xr = _require_xarray()
    with xr.open_dataset(path) as ds:
        z = ds["z"]
        if "time" in z.dims:
            z = z.isel(time=0)
        elif "valid_time" in z.dims:
            z = z.isel(valid_time=0)
        return z.load()


async def city_elevations(cities: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    async with OpenMeteoClient() as client:
        for city in cities:
            out[city] = await client.city_elevation(city)
            logger.info("%s: %.0f m", city, out[city])
    return out


def fill_seed(seed_path: Path, orography: Any, elevations: dict[str, float]) -> int:
    with seed_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        row["elevation_m"] = round(elevations[row["capital_city"]])
        # pi-lens-ignore: unchecked-throwing-call-python
        row["cell_elevation_m"] = round(
            cell_elevation(orography, float(row["lat"]), float(row["lon"]))
        )
    with seed_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=SEED_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main(argv: list[str]) -> int:
    if argv:
        print(__doc__)
        return 2
    orography = load_orography(fetch_orography(orography_path()))
    with SEED_PATH.open(newline="", encoding="utf-8") as fh:
        cities = sorted({r["capital_city"] for r in csv.DictReader(fh)})
    elevations = asyncio.run(city_elevations(cities))
    count = fill_seed(SEED_PATH, orography, elevations)
    logger.info(
        "Filled elevations for %d capitals in %s: REVIEW before committing.", count, SEED_PATH
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
