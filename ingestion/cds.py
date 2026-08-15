"""Bulk ERA5-Land fetcher via the Copernicus Climate Data Store (CDS).

Usage:
    python -m ingestion.cds refresh          # full backfill, 1950 to this year
    python -m ingestion.cds refresh 1950 1979  # one year range (e.g. a resume)

Design notes:
- Same underlying data as ingestion/openmeteo.py (ERA5-Land, 2m temperature),
  fetched in BULK instead of per-point. Open-Meteo's free tier caps a real
  backfill at roughly a week's worth of cities a day (see ingestion/weather.py);
  CDS has no such per-point throttle, at the cost of per-request queueing that
  can take minutes to hours, and it REQUIRES a CDS account with the ERA5-Land
  licence accepted first.
- Writes the SAME data/weather_daily.parquet snapshot as ingestion/weather.py,
  through the SAME write_snapshot() and the SAME MAX_NULL_RATE gate: every
  downstream dbt model and page is agnostic to which fetcher populated the
  snapshot. This module REUSES that contract; it does not reimplement it.
- Chunked by (year, statistic): one request per calendar year per
  daily_statistic (mean / minimum / maximum) — about 76 x 3 = 228 requests for
  a full backfill. Each downloaded NetCDF is cached under data/raw/cds/, keyed
  by year and statistic, so a rerun after a queue timeout or a Ctrl-C only
  re-requests chunks that never finished.
- cdsapi and xarray are optional dependencies (the `cds` extra in
  pyproject.toml): most of this project, including every other ingestion
  module, must keep running for someone who never touches temperature data.
  Both are therefore imported lazily, inside the functions that need them,
  with an actionable error (CDSError) if the extra was never installed.
- Point extraction happens locally and offline, with xarray's nearest-neighbour
  selection. The requested coordinate and the selected cell centre can differ
  by up to roughly half a grid step on a 0.1 deg grid; MAX_CELL_DISTANCE_DEG is
  set above that, so a genuine mismatch (wrong area, wrong seed coordinate)
  fails loudly instead of silently sampling the wrong place.

UNVERIFIED — read before running a real fetch: the exact request parameter set
and the NetCDF variable/dimension naming for `derived-era5-land-daily-statistics`
are taken from CDS's published documentation, not from an actual response: this
environment has no CDS credentials and the licence has not been accepted (see
docs/04-datasets.md). Variable and coordinate names are therefore detected
defensively (a single data variable, latitude/longitude coordinates, one
datetime64 coordinate) rather than hardcoded, so a reasonable naming variation
does not silently break extraction; anything outside that shape raises
CDSError instead of guessing.
"""

from __future__ import annotations

import logging
import math
import sys
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from ingestion.weather import (
    DATA_DIR,
    MAX_NULL_RATE,
    SNAPSHOT_NAME,
    START_DATE,
    WEATHER_COLUMNS,
    Capital,
    WeatherError,
    load_capitals,
    null_rate,
    write_snapshot,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ingestion.cds")

CDS_DATASET_ID = "derived-era5-land-daily-statistics"

# CDS's own area convention: [North, West, South, East].
ITALY_BBOX: tuple[float, float, float, float] = (48.0, 6.0, 35.0, 19.0)

# One retrieval per (year, statistic); each maps onto a weather_daily column.
STATISTIC_TO_COLUMN = {
    "daily_mean": "t_mean",
    "daily_minimum": "t_min",
    "daily_maximum": "t_max",
}
STATISTICS = tuple(STATISTIC_TO_COLUMN)

KELVIN_TO_CELSIUS_OFFSET = 273.15

# 0.1 deg cells: the nearest-cell distance is at most ~0.07 deg on a diagonal.
# Anything beyond this margin means the area or the seed coordinate is wrong,
# not that the grid is merely coarse.
MAX_CELL_DISTANCE_DEG = 0.15

START_YEAR = START_DATE.year  # 1950, the same first year as ingestion/weather.py

RAW_DIR_NAME = "cds"


class CDSError(WeatherError):
    """Raised when a CDS request, or the local extraction of its NetCDF, is unusable."""


# --------------------------------------------------------------------------
# Optional dependencies: imported lazily so the rest of the project runs
# without them. `uv sync --extra cds` installs both (see pyproject.toml).
# --------------------------------------------------------------------------


def _require_cdsapi() -> Any:
    try:
        import cdsapi
    except ImportError as exc:
        raise CDSError(
            "cdsapi is not installed. Install the optional extra with "
            "`uv sync --extra cds`, then complete a CDS account and accept the "
            "ERA5-Land licence at https://cds.climate.copernicus.eu before "
            "running a real fetch. See docs/04-datasets.md."
        ) from exc
    return cdsapi


def _require_xarray() -> Any:
    try:
        import xarray as xr
    except ImportError as exc:
        raise CDSError(
            "xarray is not installed. Install the optional extra with "
            "`uv sync --extra cds`. See docs/04-datasets.md."
        ) from exc
    return xr


def _new_client() -> Any:
    """A fresh cdsapi.Client(), reading credentials from ~/.cdsapirc.

    Never pass or log a token: the client reads ~/.cdsapirc entirely on its
    own. Exists as a seam so tests can monkeypatch it to a fake client instead
    of constructing a real one.
    """
    cdsapi = _require_cdsapi()
    return cdsapi.Client()


# --------------------------------------------------------------------------
# Pre-flight: every capital must fall inside the area we are about to request.
# --------------------------------------------------------------------------


def verify_capitals_in_bbox(
    capitals: list[Capital], bbox: tuple[float, float, float, float] = ITALY_BBOX
) -> None:
    """Fail loudly before spending a single CDS request on the wrong area.

    A capital outside `bbox` would come back with no data at best, or get
    silently clipped to the nearest edge cell at worst — sampling a location
    hundreds of kilometres from the one the operator thinks they configured.
    """
    north, west, south, east = bbox
    outside = [c for c in capitals if not (south <= c.lat <= north and west <= c.lon <= east)]
    if outside:
        listed = ", ".join(f"{c.province_code} ({c.lat}, {c.lon})" for c in outside)
        raise CDSError(f"Capitals outside the CDS area {bbox} (N, W, S, E): {listed}")


# --------------------------------------------------------------------------
# Download, one (year, statistic) chunk at a time, cached and resumable.
# --------------------------------------------------------------------------


def _chunk_path(raw_dir: Path, year: int, statistic: str) -> Path:
    return raw_dir / f"{year}_{statistic}.nc"


def _year_is_final(year: int, today: date) -> bool:
    """The current year keeps accumulating days until it ends, so its cache is
    always stale; mirrors ingestion/weather.py's handling of the still-growing
    decade. Every earlier year is complete and safe to skip on a rerun."""
    return year < today.year


def _cds_request(
    year: int, statistic: str, bbox: tuple[float, float, float, float]
) -> dict[str, Any]:
    return {
        "variable": ["2m_temperature"],
        "year": [str(year)],
        "month": [f"{m:02d}" for m in range(1, 13)],
        "day": [f"{d:02d}" for d in range(1, 32)],
        "daily_statistic": statistic,
        "time_zone": "utc+00:00",
        "frequency": "1_hourly",
        "area": list(bbox),
    }


def download_chunk(
    client: Any,
    raw_dir: Path,
    year: int,
    statistic: str,
    bbox: tuple[float, float, float, float],
    today: date,
) -> Path:
    """One (year, statistic) NetCDF file: cached, or requested from CDS.

    CDS requests are queued server-side and can take minutes to hours, so the
    cache is what makes a re-run of a multi-year backfill cheap: only chunks
    that never finished downloading are requested again.
    """
    target = _chunk_path(raw_dir, year, statistic)
    if target.exists() and _year_is_final(year, today):
        logger.info("[%d %s] cached, skipping: %s", year, statistic, target.name)
        return target
    logger.info(
        "[%d %s] requesting from CDS (queued server-side, can take a while)...", year, statistic
    )
    tmp = target.with_name(target.name + ".tmp")
    client.retrieve(CDS_DATASET_ID, _cds_request(year, statistic, bbox), str(tmp))
    tmp.replace(target)
    logger.info("[%d %s] downloaded -> %s", year, statistic, target.name)
    return target


# --------------------------------------------------------------------------
# Local, offline point extraction from the downloaded NetCDFs.
# --------------------------------------------------------------------------


def _sole_data_variable(ds: Any) -> str:
    names = list(ds.data_vars)
    if len(names) != 1:
        raise CDSError(
            f"Expected exactly one data variable in the NetCDF, found {names}. "
            "The request likely asked for more than one `variable`."
        )
    return names[0]


def _time_coord_name(ds: Any) -> str:
    for name, coord in ds.coords.items():
        if str(coord.dtype).startswith("datetime64"):
            return name
    raise CDSError(f"No datetime64 coordinate found; coordinates present: {list(ds.coords)}")


def _select_nearest(ds: Any, lat: float, lon: float, province_code: str) -> Any:
    """The nearest grid cell to (lat, lon), logging and gating the distance."""
    point = ds.sel(latitude=lat, longitude=lon, method="nearest")
    cell_lat = float(point["latitude"])
    cell_lon = float(point["longitude"])
    distance = math.hypot(cell_lat - lat, cell_lon - lon)
    logger.info(
        "[%s] requested (%.4f, %.4f) -> nearest cell (%.4f, %.4f), distance %.4f deg",
        province_code,
        lat,
        lon,
        cell_lat,
        cell_lon,
        distance,
    )
    if distance > MAX_CELL_DISTANCE_DEG:
        raise CDSError(
            f"[{province_code}] nearest ERA5-Land cell is {distance:.4f} deg from "
            f"({lat}, {lon}), beyond the {MAX_CELL_DISTANCE_DEG} deg limit. "
            "The requested area probably does not cover this point, or the "
            "seed coordinate in dbt/seeds/province_capitals.csv is wrong."
        )
    return point


def _kelvin_to_celsius_or_none(value: Any) -> float | None:
    fvalue = float(value)
    return None if math.isnan(fvalue) else fvalue - KELVIN_TO_CELSIUS_OFFSET


def _row(
    province_code: str, day: date, t_min: float | None, t_mean: float | None, t_max: float | None
) -> dict:
    row = {
        "province_code": province_code,
        "date": day,
        "t_min": t_min,
        "t_mean": t_mean,
        "t_max": t_max,
    }
    assert list(row) == WEATHER_COLUMNS, "row shape must track the shared weather_daily schema"
    return row


def extract_year_rows(paths: dict[str, Path], capitals: list[Capital]) -> list[dict]:
    """Rows for one year, across every capital, from the three per-statistic files.

    `paths` maps daily_statistic -> its downloaded NetCDF path (mean, minimum,
    maximum, all three present). Opens each file once, extracts every
    capital's nearest cell, converts Kelvin to Celsius, and closes the files
    again — this is pure local computation, no network involved.
    """
    xr = _require_xarray()
    datasets = {statistic: xr.open_dataset(path) for statistic, path in paths.items()}
    try:
        rows: list[dict] = []
        for cap in capitals:
            celsius_by_column: dict[str, list[float | None]] = {}
            days: list[date] | None = None
            for statistic, ds in datasets.items():
                column = STATISTIC_TO_COLUMN[statistic]
                point = _select_nearest(ds, cap.lat, cap.lon, cap.province_code)
                var = _sole_data_variable(ds)
                values = point[var].values
                celsius_by_column[column] = [_kelvin_to_celsius_or_none(v) for v in values]
                if days is None:
                    time_values = point[_time_coord_name(ds)].values
                    days = [date.fromisoformat(str(t)[:10]) for t in time_values]
            assert days is not None
            rows.extend(
                _row(
                    cap.province_code,
                    days[i],
                    celsius_by_column["t_min"][i],
                    celsius_by_column["t_mean"][i],
                    celsius_by_column["t_max"][i],
                )
                for i in range(len(days))
            )
        return rows
    finally:
        for ds in datasets.values():
            ds.close()


# --------------------------------------------------------------------------
# Orchestration.
# --------------------------------------------------------------------------


def cmd_refresh(
    start_year: int | None = None,
    end_year: int | None = None,
    data_dir: Path = DATA_DIR,
) -> int:
    capitals = load_capitals()
    verify_capitals_in_bbox(capitals)

    today = date.today()
    explicit_range = start_year is not None or end_year is not None
    start = start_year if start_year is not None else START_YEAR
    end = end_year if end_year is not None else today.year
    if start > end:
        logger.error("start year %d is after end year %d", start, end)
        return 2

    raw_dir = data_dir / "raw" / RAW_DIR_NAME
    raw_dir.mkdir(parents=True, exist_ok=True)

    client = _new_client()
    years = list(range(start, end + 1))
    total_chunks = len(years) * len(STATISTICS)
    chunk_i = 0
    rows_by_province: dict[str, list[dict]] = {c.province_code: [] for c in capitals}

    for year in years:
        paths: dict[str, Path] = {}
        for statistic in STATISTICS:
            chunk_i += 1
            logger.info("=== chunk [%d/%d]: %d %s ===", chunk_i, total_chunks, year, statistic)
            paths[statistic] = download_chunk(client, raw_dir, year, statistic, ITALY_BBOX, today)
        for row in extract_year_rows(paths, capitals):
            rows_by_province[row["province_code"]].append(row)

    bad: list[tuple[str, float]] = []
    all_rows: list[dict] = []
    for cap in capitals:
        rows = rows_by_province[cap.province_code]
        rate = null_rate(rows)
        if rate > MAX_NULL_RATE:
            bad.append((cap.province_code, rate))
            logger.error(
                "[%s] %s: %.1f%% of days are null (limit %.1f%%). Its ERA5-Land "
                "cell is probably ocean — nudge lat/lon inland in "
                "dbt/seeds/province_capitals.csv and rerun.",
                cap.province_code,
                cap.capital_city,
                100 * rate,
                100 * MAX_NULL_RATE,
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

    if explicit_range:
        # A partial year range must not erase years outside it: keep the
        # existing snapshot's rows for every year this run did not touch.
        existing = data_dir / SNAPSHOT_NAME
        if existing.exists():
            kept = pl.read_parquet(existing).filter(
                (pl.col("date").dt.year() < start) | (pl.col("date").dt.year() > end)
            )
            all_rows = kept.to_dicts() + all_rows

    write_snapshot(all_rows, data_dir)
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] != "refresh":
        print(__doc__)
        return 2
    rest = argv[1:]
    if not rest:
        return cmd_refresh()
    if len(rest) == 2:
        try:
            return cmd_refresh(int(rest[0]), int(rest[1]))
        except ValueError:
            print(__doc__)
            return 2
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
