"""Bulk ERA5-Land fetcher via the Copernicus Climate Data Store (CDS).

Usage:
    python -m ingestion.cds refresh          # bulk year-grid backfill, 1950 to the last published month
    python -m ingestion.cds refresh 1950 1979  # one year range (e.g. a resume)
    python -m ingestion.cds refresh-timeseries          # ARCO point backfill — fast, all cities
    python -m ingestion.cds refresh-timeseries 1950 1979  # one year range

Design notes:
- Same underlying data as ingestion/openmeteo.py (ERA5-Land, 2m temperature),
  fetched in BULK instead of per-point. Open-Meteo's free tier caps a real
  backfill at roughly a week's worth of cities a day (see ingestion/weather.py);
  CDS has no such per-point throttle, at the cost of per-request queueing that
  can take minutes to hours, and it REQUIRES a CDS account with the ERA5-Land
  licence accepted first.

  The `refresh-timeseries` subcommand is the FAST alternative: it uses the
  ARCO `reanalysis-era5-land-timeseries` dataset, which returns hourly values
  at a single request point (nearest grid cell) and is optimised for exactly
  this use case. A full backfill is 106 lightweight point queries instead of
  228 queued year-grid downloads, so it completes in minutes rather than days,
  even with modest concurrency (see cmd_refresh_timeseries).
- Writes the SAME data/weather_daily.parquet snapshot as ingestion/weather.py,
  through the SAME write_snapshot() and the SAME MAX_NULL_RATE gate: every
  downstream dbt model and page is agnostic to which fetcher populated the
  snapshot. This module REUSES that contract; it does not reimplement it.
- Chunked by (year, statistic): one request per calendar year per
  daily_statistic (mean / minimum / maximum) — about 76 x 3 = 228 requests for
  a full backfill. Each downloaded NetCDF is cached under data/raw/cds/, keyed
  by year, statistic AND the last day it covers, so a rerun after a queue
  timeout or a Ctrl-C only re-requests chunks that never finished, and a
  partial current year cannot be replayed as if it were complete.
- ERA5-Land is published with a lag (PUBLICATION_LAG_DAYS, shared with
  ingestion/weather.py so the two fetchers agree on where history ends). Only
  calendar months that have entirely ended on or before that boundary are
  requested: the CDS request is a year x month x day cross product, so a whole
  month is the finest slice expressible without asking for dates that do not
  exist yet. The remaining tail (at most ~37 days) is what the incremental
  Open-Meteo path is for.
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

Status: the request shape and the extraction path have been validated against
a real CDS response (one data variable `t2m`, dims (valid_time, latitude,
longitude), Kelvin), and cross-checked against the Open-Meteo path for Torino
to within 0.07 C. A full backfill has NOT completed yet, so the queueing,
timeout and resume behaviour of a 228-chunk run is still unexercised at scale.
Variable and coordinate names are still detected defensively (a single data
variable, latitude/longitude coordinates, one datetime64 coordinate) rather
than hardcoded, so a naming change on the CDS side raises CDSError instead of
silently misreading data.
"""

from __future__ import annotations

import calendar
import logging
import math
import sys
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from ingestion.receipts import upsert_fetch_receipt
from ingestion.weather import (
    DATA_DIR,
    MAX_NULL_RATE,
    PUBLICATION_LAG_DAYS,
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

# Every temperature column is gated independently: the three statistics are
# three separate downloads here, so daily_minimum can come back empty while
# daily_mean is perfect. The Open-Meteo path gets all three from one response
# and cannot drift this way, which is why it only gates t_mean.
GATED_COLUMNS = tuple(sorted(STATISTIC_TO_COLUMN.values()))
COLUMN_TO_STATISTIC = {column: statistic for statistic, column in STATISTIC_TO_COLUMN.items()}

KELVIN_TO_CELSIUS_OFFSET = 273.15

# 0.1 deg cells: the nearest-cell distance is at most ~0.07 deg on a diagonal.
# Anything beyond this margin means the area or the seed coordinate is wrong,
# not that the grid is merely coarse.
MAX_CELL_DISTANCE_DEG = 0.15

START_YEAR = START_DATE.year  # 1950, the same first year as ingestion/weather.py

RAW_DIR_NAME = "cds"

# --------------------------------------------------------------------------
# ARCO point-time-series dataset (reanalysis-era5-land-timeseries).
# Unlike the bulk path above, each request asks for ONE lat/lon point over a
# date range and gets hourly values at the nearest grid cell back, which is
# what the ECMWF ARCO Data Lake is optimised for. A full 106-city backfill is
# therefore 106 lightweight queries instead of 228 queued year-grid downloads
# (or 848 quota-limited decade chunks against Open-Meteo).
# --------------------------------------------------------------------------
TIMESERIES_DATASET_ID = "reanalysis-era5-land-timeseries"

# The dataset's own first published day (the form in the CDS UI shows
# 1950-01-02; requesting 1950-01-01 would be rejected).
TIMESERIES_START_DATE = date(1950, 1, 2)
TIMESERIES_START_YEAR = TIMESERIES_START_DATE.year

# Requested variable names (CDS) -> their NetCDF short names. The ARCO
# time-series response names them t2m / tp per the CF conventions, matching the
# sibling reanalysis-era5-single-levels-timeseries dataset. We detect them
# defensively by long_name anyway (see _find_var).
TIMESERIES_VARIABLES = {
    "2m_temperature": "t2m",
    "total_precipitation": "tp",
}

# Precip is returned in metres; the weather_daily snapshot column (fed by
# Open-Meteo's precipitation_sum) is in millimetres. Convert to match.
METRES_TO_MM = 1000.0

# CDS limits the number of SIMULTANEOUSLY QUEUED requests for a dataset per
# account (a live run with 4 concurrent workers was rejected with "Number
# queued requests for this dataset is temporarily limited"). Each ARCO point
# request is lightweight, so serial is the honest default: it avoids tripping
# the queued-job limit, which concurrency does not help with. A caller may
# still raise `workers` if the queue limit is later raised, but the server is
# the constraint, not local throughput.
DEFAULT_TIMESERIES_WORKERS = 1

# How many times to retry a request rejected because too many jobs are queued,
# and how long (seconds) to pause between attempts. The queue needs time to
# drain; retrying immediately is guaranteed to hit the same closed door, so
# the backoff is the useful part, not the retry count.
QUEUE_LIMIT_RETRIES = 5
QUEUE_LIMIT_BACKOFF_S = 20.0


class CDSError(WeatherError):
    """Raised when a CDS request, or the local extraction of its NetCDF, is unusable."""


# --------------------------------------------------------------------------
# Optional dependencies: imported lazily so the rest of the project runs
# without them. `uv sync --extra cds` installs both (see pyproject.toml).
# --------------------------------------------------------------------------


def _require_cdsapi() -> Any:
    try:
        import cdsapi  # pyrefly: ignore[missing-import]  # optional extra, see above
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
        import xarray as xr  # pyrefly: ignore[missing-import]  # optional extra, see above
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


@dataclass(frozen=True)
class YearPlan:
    """The slice of one calendar year that CDS can actually serve right now.

    `months` holds only calendar months that have entirely ended on or before
    the publication boundary, so `last_day` never runs past it. A year with no
    such month has no plan at all (see `plan_year`).
    """

    year: int
    months: tuple[int, ...]
    last_day: date

    @property
    def is_partial(self) -> bool:
        return len(self.months) < 12


def last_available_day(today: date) -> date:
    """The most recent day ERA5-Land can possibly have published.

    Shares PUBLICATION_LAG_DAYS with ingestion/weather.py so the bulk and the
    incremental fetcher cannot disagree about where history ends.
    """
    return today - timedelta(days=PUBLICATION_LAG_DAYS)


def plan_year(year: int, last_available: date) -> YearPlan | None:
    """What to request for `year`, or None if nothing in it is published yet.

    Whole months only. The CDS request is a year x month x day cross product,
    so "January through 8 August" is not expressible in a single request;
    asking for the days after the boundary anyway would put dates that do not
    exist yet inside the request. Dropping the incomplete tail month is the
    conservative reading and costs at most ~37 days of the newest data.
    """
    months = tuple(
        month
        for month in range(1, 13)
        if date(year, month, calendar.monthrange(year, month)[1]) <= last_available
    )
    if not months:
        return None
    last = months[-1]
    return YearPlan(year, months, date(year, last, calendar.monthrange(year, last)[1]))


def requested_days(plan: YearPlan) -> list[date]:
    """Every real calendar date the plan asks CDS for, in order.

    The request itself sends days 01-31 for every month (as the CDS web form
    does); combinations that are not real dates, like 30 February, are ignored
    server-side. This is that request expanded to the dates it can actually
    match, which is what the publication-lag boundary has to be checked against.
    """
    return [
        date(plan.year, month, day)
        for month in plan.months
        for day in range(1, calendar.monthrange(plan.year, month)[1] + 1)
    ]


def _chunk_path(raw_dir: Path, plan: YearPlan, statistic: str) -> Path:
    """Cache filename for one (year, statistic) chunk, KEYED BY COVERAGE.

    A complete year keeps the plain name. A partial year carries the last day
    it covers, so next month's rerun misses the cache and downloads the longer
    chunk instead of silently reusing a truncated year forever.
    """
    if plan.is_partial:
        return raw_dir / f"{plan.year}_{statistic}_through_{plan.last_day:%Y%m%d}.nc"
    return raw_dir / f"{plan.year}_{statistic}.nc"


def _cds_request(
    plan: YearPlan, statistic: str, bbox: tuple[float, float, float, float]
) -> dict[str, Any]:
    return {
        "variable": ["2m_temperature"],
        "year": [str(plan.year)],
        "month": [f"{m:02d}" for m in plan.months],
        "day": [f"{d:02d}" for d in range(1, 32)],
        "daily_statistic": statistic,
        "time_zone": "utc+00:00",
        "frequency": "1_hourly",
        "area": list(bbox),
    }


def _opens_cleanly(path: Path) -> bool:
    """Whether `path` is a NetCDF file xarray can actually read.

    A chunk truncated by a killed process or a half-written disk stays on disk
    looking like a valid cache entry; without this check every later run dies
    on the same OSError deep inside the extraction step.
    """
    xr = _require_xarray()
    try:
        with xr.open_dataset(path):
            return True
    except Exception:  # any failure to open at all means "throw it away and re-download"
        return False


def _retrieve(
    client: Any,
    target: Path,
    plan: YearPlan,
    statistic: str,
    bbox: tuple[float, float, float, float],
) -> None:
    """One real CDS retrieval, written through a .tmp file.

    The rename is what makes the cache trustworthy: a crash, a timeout or a
    Ctrl-C mid-download leaves only the .tmp behind, never a truncated file
    under the final name that a later run would happily reuse.
    """
    logger.info(
        "[%d %s] requesting from CDS (queued server-side, can take a while)...",
        plan.year,
        statistic,
    )
    tmp = target.with_name(target.name + ".tmp")
    try:
        client.retrieve(CDS_DATASET_ID, _cds_request(plan, statistic, bbox), str(tmp))
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        raise CDSError(
            f"[{plan.year} {statistic}] the CDS request failed: {exc!r}. "
            f"Nothing is lost: every chunk that finished is cached under {target.parent}/, "
            "so re-running the same command resumes and requests only what is still "
            "missing. A 403 usually means the ERA5-Land licence has not been accepted "
            "for this account; a 500 or a timeout is usually transient queue pressure."
        ) from exc
    tmp.replace(target)


def download_chunk(
    client: Any,
    raw_dir: Path,
    plan: YearPlan,
    statistic: str,
    bbox: tuple[float, float, float, float],
) -> Path:
    """One (year, statistic) NetCDF file: cached, or requested from CDS.

    CDS requests are queued server-side and can take minutes to hours, so the
    cache is what makes a re-run of a multi-year backfill cheap: only chunks
    that never finished downloading are requested again. Because the cache key
    encodes the coverage, a cached file always covers exactly what this plan
    asks for, including for a still-growing current year.
    """
    target = _chunk_path(raw_dir, plan, statistic)
    if target.exists():
        if _opens_cleanly(target):
            logger.info("[%d %s] cached, skipping: %s", plan.year, statistic, target.name)
            return target
        logger.warning(
            "[%d %s] cached chunk %s does not open as NetCDF (truncated download?); "
            "deleting it and re-downloading once.",
            plan.year,
            statistic,
            target.name,
        )
        target.unlink()
    _retrieve(client, target, plan, statistic, bbox)
    if not _opens_cleanly(target):
        raise CDSError(
            f"[{plan.year} {statistic}] the freshly downloaded chunk {target} does not open "
            "as a NetCDF file. This is the second attempt (the cached copy was already "
            f"discarded once), so it is not a stale cache. Remove {target} and investigate "
            "before re-running: the request may be returning an error document, or the "
            "`netcdf4` package may be missing from the `cds` extra."
        )
    logger.info("[%d %s] downloaded -> %s", plan.year, statistic, target.name)
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
    # pi-lens-ignore: unchecked-throwing-call-python
    cell_lat = float(point["latitude"])
    # pi-lens-ignore: unchecked-throwing-call-python
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
    # pi-lens-ignore: unchecked-throwing-call-python
    fvalue = float(value)
    return None if math.isnan(fvalue) else fvalue - KELVIN_TO_CELSIUS_OFFSET


def _row(
    province_code: str, day: date, t_min: float | None, t_mean: float | None, t_max: float | None
) -> dict:
    return {
        "province_code": province_code,
        "date": day,
        "t_min": t_min,
        "t_mean": t_mean,
        "t_max": t_max,
        # This CDS backfill only retrieves temperature (see RETRIEVAL_STATISTIC
        # above); precip_sum is Open-Meteo-only for now, same as any legacy
        # weather_daily.parquet row written before the column existed.
        "precip_sum": None,
    }


def verify_row_schema() -> None:
    """The row dict's key order IS the snapshot's column order.

    Checked once per year rather than per row, and with a real raise rather
    than an `assert`: `python -O` strips asserts, and this invariant silently
    reordering t_min and t_max would swap two columns in every published chart.
    """
    keys = list(_row("", date(1950, 1, 1), None, None, None))
    if keys != WEATHER_COLUMNS:
        raise CDSError(
            f"Row shape {keys} no longer matches the shared weather_daily schema "
            f"{WEATHER_COLUMNS}. Fix _row() in ingestion/cds.py: writing these rows "
            "would put values under the wrong column names."
        )


def _days_axis(ds: Any) -> list[date]:
    """The dates one chunk covers, in file order."""
    values = ds[_time_coord_name(ds)].values
    return [date.fromisoformat(str(t)[:10]) for t in values]


def _shared_days(days_by_statistic: dict[str, list[date]], year: int) -> list[date]:
    """The single time axis all three statistics agree on, or a loud failure.

    The three statistics are three independent downloads. Pairing them by
    position, as this function's caller does, is only valid if they cover the
    SAME dates: a one-day offset (a chunk that starts late, or ends early)
    would attach every minimum and maximum to the wrong day's mean, producing
    a snapshot that is plausible everywhere and wrong everywhere. Mirrors the
    length-mismatch guard in ingestion.weather.payload_to_rows.
    """
    reference_statistic, reference = next(iter(days_by_statistic.items()))
    remedy = (
        f"Delete the {year} chunks under data/raw/cds/ and re-download them; if they "
        "come back the same, the CDS request for this year is returning a different "
        "period per statistic and must be investigated before trusting the snapshot."
    )
    for statistic, days in days_by_statistic.items():
        if days == reference:
            continue
        if len(days) != len(reference):
            raise CDSError(
                f"[{year}] time axes differ between {reference_statistic} "
                f"({len(reference)} days) and {statistic} ({len(days)} days). "
                f"Pairing them positionally would misdate every row. {remedy}"
            )
        index, (expected, found) = next(
            (i, pair)
            for i, pair in enumerate(zip(reference, days, strict=True))
            if pair[0] != pair[1]
        )
        raise CDSError(
            f"[{year}] time axes differ between {reference_statistic} and {statistic}: "
            f"both cover {len(days)} days but they first diverge at position {index}, "
            f"where {reference_statistic} has {expected} and {statistic} has {found}. "
            f"Pairing them positionally would misdate every row. {remedy}"
        )
    return reference


def extract_year_rows(paths: dict[str, Path], capitals: list[Capital], year: int) -> list[dict]:
    """Rows for one year, across every capital, from the three per-statistic files.

    `paths` maps daily_statistic -> its downloaded NetCDF path (mean, minimum,
    maximum, all three present). Opens each file once, checks that all three
    cover the same dates, extracts every capital's nearest cell, converts
    Kelvin to Celsius, and closes the files again — this is pure local
    computation, no network involved.
    """
    verify_row_schema()
    xr = _require_xarray()
    datasets = {statistic: xr.open_dataset(path) for statistic, path in paths.items()}
    try:
        days = _shared_days({s: _days_axis(ds) for s, ds in datasets.items()}, year)
        rows: list[dict] = []
        for cap in capitals:
            celsius_by_column: dict[str, list[float | None]] = {}
            for statistic, ds in datasets.items():
                column = STATISTIC_TO_COLUMN[statistic]
                point = _select_nearest(ds, cap.lat, cap.lon, cap.province_code)
                var = _sole_data_variable(ds)
                values = point[var].values
                if len(values) != len(days):
                    raise CDSError(
                        f"[{year} {statistic}] {cap.province_code}: {len(values)} values "
                        f"for {len(days)} dates. The chunk has a dimension beyond "
                        "(time, latitude, longitude) that nearest-cell selection did not "
                        "collapse; extraction cannot pair values with dates."
                    )
                celsius_by_column[column] = [_kelvin_to_celsius_or_none(v) for v in values]
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


def null_rates(rows: list[dict]) -> dict[str, float]:
    """Share of days with no value, per temperature column.

    ingestion.weather.null_rate answers this for t_mean only, which is all the
    Open-Meteo path needs: it receives all three series in one response, so
    they cannot go missing independently. Here they are three separate
    downloads, and an empty daily_minimum chunk would otherwise sail through a
    t_mean-only gate and publish a snapshot with no minimum temperatures at
    all. Empty input counts as fully null, as it does there.
    """
    if not rows:
        return dict.fromkeys(GATED_COLUMNS, 1.0)
    return {
        column: sum(1 for r in rows if r[column] is None) / len(rows) for column in GATED_COLUMNS
    }


# --------------------------------------------------------------------------
# ARCO point-time-series backfill (reanalysis-era5-land-timeseries).
#
# This is the "fast" full backfill path. Unlike the bulk path above, which
# downloads whole-year grids and is throttled by CDS's server-side queue, each
# request here asks for ONE coordinate over a date range and gets hourly values
# at the nearest grid cell back — exactly what the ECMWF ARCO Data Lake is
# optimised for. A 106-city backfill is 106 lightweight queries rather than 228
# queued year-grid downloads, so modest concurrency actually helps.
# --------------------------------------------------------------------------


def _timeseries_decade_chunks(start: date, end: date) -> list[tuple[date, date]]:
    """Split a range into calendar decades, clipped to the edges.

    Chunking keeps a single response small enough to retry cheaply and makes
    the raw cache resumable at decade granularity, mirroring the Open-Meteo
    path. The ARCO API is fast, but a partial failure should not re-download
    the whole 1950-present series for a city.
    """
    chunks: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        decade_end = date((cursor.year // 10) * 10 + 9, 12, 31)
        chunk_end = min(decade_end, end)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def _timeseries_request(
    cap: Capital, start: date, end: date, variables: tuple[str, ...]
) -> dict[str, Any]:
    """One CDS request for a single point, matching the ARCO timeseries form.

    The request shape here is the one documented by ECMWF's own examples for
    the ARCO time-series datasets: a ``location`` object with ``longitude`` and
    ``latitude`` keys (the nearest grid cell is selected server-side), a
    ``date`` range, and ``data_format``. Note this is NOT the ``area`` form the
    bulk path uses — requesting a point is what makes the ARCO response fast.
    """
    return {
        "variable": list(variables),
        "location": {"longitude": cap.lon, "latitude": cap.lat},
        "date": [f"{start.isoformat()}/{end.isoformat()}"],
        "data_format": "netcdf",
    }


def _timeseries_cache_path(raw_dir: Path, cap: Capital, start: date) -> Path:
    """Cache filename for one city-decade, keyed by coordinate and coverage.

    The file stores the RAW CDS download. For ``data_format=netcdf`` the v2
    ARCO API returns a ZIP archive (one NetCDF per requested variable), so this
    file is really a zip despite the ``.nc`` suffix — ``_read_arco_arrays``
    inspects the actual bytes and handles both, so the suffix is just a stable
    cache key, not a claim about the format.
    """
    return raw_dir / f"{cap.province_code}_{cap.lat:.4f}_{cap.lon:.4f}_{start.year}.nc"


def _find_var(ds: Any, short_name: str, long_name_fragment: str) -> str:
    """The data variable matching a short name or long-name fragment.

    The ARCO time-series response names the temperature field ``t2m`` and the
    precipitation field ``tp`` per the CF conventions (matching the sibling
    reanalysis-era5-single-levels-timeseries dataset). We detect defensively by
    short name OR long name, so a naming change on the CDS side raises
    CDSError instead of silently misreading data.
    """
    for name, var in ds.data_vars.items():
        if name == short_name:
            return name
        long_name = str(getattr(var, "long_name", "")).lower()
        if long_name_fragment in long_name:
            return name
    names = list(ds.data_vars)
    raise CDSError(
        f"Expected a '{short_name}' (or '{long_name_fragment}') variable in the "
        f"ARCO time-series response; found {names}."
    )


def _datetime64_to_date(value: Any) -> date:
    """numpy.datetime64 -> datetime.date, for grouping hourly values by day."""
    import numpy as np  # part of the `cds` extra

    ts = np.datetime64(value, "s").item()
    return ts.date() if hasattr(ts, "date") else date.fromisoformat(str(value)[:10])


def _float_or_none(value: Any) -> float | None:
    """float(value), or None if it is NaN/unparseable (missing cell value)."""
    try:
        fvalue = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(fvalue) else fvalue


def _collect_arco_arrays(sources: list[Path], xr: Any, origin: Path) -> tuple[list[Any], Any, Any]:
    """Pull the time axis, ``t2m`` (K) and ``tp`` (m) out of NetCDF sources.

    ``sources`` is one or more read-able NetCDF paths — the members of an ARCO
    zip, or the plain file itself for synthetic fixtures. Each real member
    carries exactly ONE variable (the t2m member or the tp member); synthetic
    fixtures may carry both in one file. Returns ``(times, t2m_kelvin,
    tp_metres)``, where a variable is ``None`` if it was absent from every
    source — the caller's null gate decides whether that is acceptable. The
    time axis comes from whichever source has a datetime coordinate.
    """
    times: list[Any] | None = None
    t2m_kelvin: Any = None
    tp_metres: Any = None
    for source in sources:
        try:
            ds = xr.open_dataset(source)
        except Exception:
            continue
        try:
            if times is None:
                try:
                    time_name = _time_coord_name(ds)
                    times = ds[time_name].values
                except CDSError:
                    # pi-lens-ignore: python-empty-except
                    pass
            try:
                t2m_name = _find_var(ds, "t2m", "2 metre temperature")
                t2m_kelvin = ds[t2m_name].values
            except CDSError:
                # pi-lens-ignore: python-empty-except
                pass
            try:
                tp_name = _find_var(ds, "tp", "total precipitation")
                tp_metres = ds[tp_name].values
            except CDSError:
                # pi-lens-ignore: python-empty-except
                pass
        finally:
            ds.close()
    if times is None:
        raise CDSError(f"No time coordinate found in the ARCO response {origin}")
    if t2m_kelvin is None and tp_metres is None:
        raise CDSError(f"No t2m or tp variable found in the ARCO response {origin}")
    return times, t2m_kelvin, tp_metres


def _read_arco_arrays(path: Path) -> tuple[list[Any], Any, Any]:
    """Read the time axis and t2m/tp arrays from an ARCO time-series response.

    The real Copernicus response is a ZIP archive whose members are NetCDF
    files, one per requested variable: a 2m-temperature member exposing
    ``t2m``, a total-precipitation member exposing ``tp``. The synthetic test
    fixtures instead write a single plain NetCDF holding both variables in one
    file. Both are accepted: this inspects the file's bytes, extracts whichever
    NetCDFs are present, and hands them to ``_collect_arco_arrays``.
    """
    xr = _require_xarray()
    try:
        # Combined into one `with` (SIM117): the temp dir must outlive the
        # member extraction, and both are closed together.
        with (
            zipfile.ZipFile(path) as archive,
            tempfile.TemporaryDirectory(prefix="arco_") as tmp_dir,
        ):
            sources: list[Path] = []
            for member in archive.infolist():
                member_path = Path(tmp_dir) / member.filename
                member_path.write_bytes(archive.read(member))
                sources.append(member_path)
            # Arrays are materialised (numpy) before the temp dir is torn
            # down, so returning inside the `with` is safe.
            return _collect_arco_arrays(sources, xr, path)
    except zipfile.BadZipFile:
        # Not a zip: a single plain NetCDF (synthetic fixture).
        return _collect_arco_arrays([path], xr, path)


def _aggregate_point_to_daily(path: Path, province_code: str) -> list[dict]:
    """Hourly point NetCDF(s) -> per-day rows for one city.

    The ARCO time-series response is a ZIP archive holding one NetCDF per
    requested variable (a 2m-temperature member exposing ``t2m``, a
    total-precipitation member exposing ``tp``) — see ``_read_arco_arrays``.
    After extracting the time axis and both arrays, this takes the
    min/mean/max of 2m temperature and the sum of total precipitation per
    calendar day, matching the weather_daily columns the rest of the pipeline
    expects. Precipitation arrives in metres (de-accumulated hourly) and is
    converted to millimetres to match Open-Meteo's precipitation_sum.
    """
    times, t2m_kelvin, tp_metres = _read_arco_arrays(path)

    daily: dict[date, dict[str, list[float | None]]] = {}
    for i, raw_time in enumerate(times):
        day = _datetime64_to_date(raw_time)
        bucket = daily.setdefault(day, {"t2m": [], "tp": []})
        if t2m_kelvin is not None:
            bucket["t2m"].append(_kelvin_to_celsius_or_none(t2m_kelvin[i]))
        if tp_metres is not None:
            tp = _float_or_none(tp_metres[i])
            bucket["tp"].append(None if tp is None else tp * METRES_TO_MM)

    rows: list[dict] = []
    for day in sorted(daily):
        bucket = daily[day]
        temps = [v for v in bucket["t2m"] if v is not None]
        precip = [v for v in bucket["tp"] if v is not None]
        rows.append(
            {
                "province_code": province_code,
                "date": day,
                "t_min": min(temps) if temps else None,
                "t_mean": sum(temps) / len(temps) if temps else None,
                "t_max": max(temps) if temps else None,
                "precip_sum": sum(precip) if precip else None,
            }
        )
    return rows


def _is_queue_limit_error(exc: Exception) -> bool:
    """Whether a CDS exception is the "too many queued requests" rejection.

    CDS rejects a request whose job would exceed the account's simultaneous
    queued-job limit for a dataset. The message ("Number queued requests for
    this dataset is temporarily limited") is surfaced through the HTTPError it
    raises when polling the job's results. Matching on the phrase, rather than
    the status code (400 is shared with other bad requests), keeps us from
    retrying a genuinely malformed request.
    """
    return "queued requests" in str(exc).lower() and "temporarily limited" in str(exc).lower()


def _retrieve_arco_with_retry(client: Any, request: dict, target: Path, label: str) -> None:
    """client.retrieve() with pause-and-retry on the queued-job limit.

    A queue-limit rejection is not a transient blip to hammer: the limit is how
    many jobs the account may have queued at once, and only time (the queue
    draining) clears it. So on that specific rejection we wait a bounded few
    seconds and retry, rather than retrying immediately (which hits the same
    closed door) or failing the whole city (which is over-fatal: the chunk cache
    means a later rerun would just pay for the same chunk again anyway).
    """
    for attempt in range(1, QUEUE_LIMIT_RETRIES + 1):
        try:
            client.retrieve(TIMESERIES_DATASET_ID, request, str(target))
            return
        # pi-lens-ignore: no-boolean-in-except
        except Exception as exc:
            if not _is_queue_limit_error(exc) or attempt == QUEUE_LIMIT_RETRIES:
                target.unlink(missing_ok=True)
                raise exc
            logger.warning(
                "%s: queued-job limit hit (attempt %d/%d); waiting %.0fs before retrying...",
                label,
                attempt,
                QUEUE_LIMIT_RETRIES,
                QUEUE_LIMIT_BACKOFF_S,
            )
            import time

            time.sleep(QUEUE_LIMIT_BACKOFF_S)


def _fetch_capital_timeseries(
    client: Any, cap: Capital, start: date, end: date, raw_dir: Path
) -> list[dict]:
    """All decades for one city via the ARCO point-timeseries API.

    Each chunk is cached the moment it arrives, so an aborted run (network
    error, Ctrl-C, rate limit) keeps every decade it already paid for and
    re-running the same command re-fetches only what is missing. A request
    rejected because too many jobs are queued for this dataset is retried
    after a pause (see _retrieve_arco_with_retry), because a whole-city failure
    on a transient queue squeeze is over-fatal when the queue drains in seconds.
    """
    rows: list[dict] = []
    for chunk_start, chunk_end in _timeseries_decade_chunks(start, end):
        cache = _timeseries_cache_path(raw_dir, cap, chunk_start)
        if cache.exists():
            logger.info("[%s] cached, skipping: %s", cap.province_code, cache.name)
        else:
            request = _timeseries_request(cap, chunk_start, chunk_end, tuple(TIMESERIES_VARIABLES))
            tmp = cache.with_name(cache.name + ".tmp")
            label = f"[{cap.province_code}] {chunk_start}..{chunk_end}"
            logger.info("%s requesting from ARCO time-series...", label)
            try:
                _retrieve_arco_with_retry(client, request, tmp, label)
            except Exception as exc:
                tmp.unlink(missing_ok=True)
                raise CDSError(
                    f"[{cap.province_code}] ARCO time-series request for "
                    f"{chunk_start}..{chunk_end} failed: {exc!r}. Nothing is lost: "
                    f"completed chunks are cached under {raw_dir}/."
                ) from exc
            tmp.replace(cache)
        rows.extend(_aggregate_point_to_daily(cache, cap.province_code))
    return rows


def cmd_refresh_timeseries(
    start_year: int | None = None,
    end_year: int | None = None,
    data_dir: Path = DATA_DIR,
    today: date | None = None,
    workers: int = DEFAULT_TIMESERIES_WORKERS,
) -> int:
    """Backfill every capital via the ARCO point-time-series dataset.

    Runs across cities, by default SERIALLY. Each task is independent (one
    point, per-decade cache), but the ARCO API limits how many jobs one
    account may have queued for a dataset at once, so concurrency trips that
    limit rather than helping (a live 4-worker run was rejected outright).
    Serial avoids the limit; a caller may raise `workers` if the limit is
    later raised, but local throughput was never the bottleneck.
    """
    capitals = load_capitals()
    verify_capitals_in_bbox(capitals)

    today = today if today is not None else date.today()
    last_available = last_available_day(today)
    start = TIMESERIES_START_DATE
    if start_year is not None:
        start = date(max(start_year, TIMESERIES_START_YEAR), 1, 1)
    end = last_available
    if end_year is not None:
        end = min(end, date(end_year, 12, 31))
    if start > end:
        logger.error("start date %s is after end date %s", start, end)
        return 2

    raw_dir = data_dir / "raw" / "cds_timeseries"
    raw_dir.mkdir(parents=True, exist_ok=True)

    client = _new_client()

    all_rows: list[dict] = []
    bad: list[tuple[str, float]] = []
    errors: list[tuple[str, str]] = []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_fetch_capital_timeseries, client, cap, start, end, raw_dir): cap
            for cap in capitals
        }
        for future in as_completed(futures):
            cap = futures[future]
            try:
                rows = future.result()
            except CDSError as exc:
                logger.error("[%s] fetch failed: %s", cap.province_code, exc)
                errors.append((cap.province_code, str(exc)))
                continue
            rate = null_rate(rows)
            if rate > MAX_NULL_RATE:
                bad.append((cap.province_code, rate))
                logger.error(
                    "[%s] %s: %.1f%% of days are null (limit %.1f%%). Its ERA5-Land "
                    "cell is probably ocean — nudge lat/lon inland in "
                    "dbt/seeds/province_capitals.csv and rerun "
                    "`just refresh-weather-cds-timeseries`.",
                    cap.province_code,
                    cap.capital_city,
                    100 * rate,
                    100 * MAX_NULL_RATE,
                )
            all_rows.extend(r for r in rows if r["t_mean"] is not None)

    if errors:
        logger.error(
            "Aborting: %d city/cities failed to fetch and the snapshot is NOT written. "
            "Completed chunks are cached under %s; re-running resumes.",
            len(errors),
            raw_dir,
        )
        return 1
    if bad:
        logger.error(
            "Refusing to write the snapshot: %d cities exceed the null limit (%s). "
            "A partially-null city produces a plausible but wrong warming rate.",
            len(bad),
            ", ".join(code for code, _ in bad),
        )
        return 1

    # A partial year range must not erase years outside it: keep the existing
    # snapshot's rows for every year this run did not touch.
    if start_year is not None or end_year is not None:
        existing = data_dir / SNAPSHOT_NAME
        if existing.exists():
            kept = pl.read_parquet(existing).filter(
                (pl.col("date").dt.year() < start.year) | (pl.col("date").dt.year() > end.year)
            )
            all_rows = kept.to_dicts() + all_rows

    snapshot_path = write_snapshot(all_rows, data_dir)
    upsert_fetch_receipt(
        data_dir / "source-receipts.json",
        "weather",
        provider="Copernicus C3S ERA5-Land",
        source_flow=TIMESERIES_DATASET_ID,
        request_url=f"https://cds.climate.copernicus.eu/datasets/{TIMESERIES_DATASET_ID}",
        raw_path=f"data/{raw_dir.relative_to(data_dir)}",
        raw_bytes=snapshot_path.read_bytes(),
        count_lines=False,
    )
    return 0


# --------------------------------------------------------------------------
# Orchestration.
# --------------------------------------------------------------------------


def cmd_refresh(
    start_year: int | None = None,
    end_year: int | None = None,
    data_dir: Path = DATA_DIR,
    today: date | None = None,
) -> int:
    capitals = load_capitals()
    verify_capitals_in_bbox(capitals)

    today = today if today is not None else date.today()
    last_available = last_available_day(today)
    explicit_range = start_year is not None or end_year is not None
    start = start_year if start_year is not None else START_YEAR
    end = end_year if end_year is not None else last_available.year
    if end > last_available.year:
        logger.warning(
            "end year %d is past the last year ERA5-Land can have published "
            "(data lags reality by %d days, so history ends %s); clamping to %d.",
            end,
            PUBLICATION_LAG_DAYS,
            last_available,
            last_available.year,
        )
        end = last_available.year
    if start > end:
        logger.error("start year %d is after end year %d", start, end)
        return 2

    plans: list[YearPlan] = []
    for year in range(start, end + 1):
        plan = plan_year(year, last_available)
        if plan is None:
            logger.warning(
                "[%d] no calendar month of this year is fully published yet "
                "(ERA5-Land currently reaches %s); skipping it.",
                year,
                last_available,
            )
            continue
        if plan.is_partial:
            logger.info(
                "[%d] partial year: requesting months %s only, through %s. ERA5-Land lags "
                "by %d days and a CDS request cannot stop mid-month, so the remaining days "
                "are left to `just refresh-weather`. This chunk is cached under a key that "
                "names its end date, so next month's run re-downloads a longer one instead "
                "of reusing this truncated year.",
                year,
                ", ".join(f"{m:02d}" for m in plan.months),
                plan.last_day,
                PUBLICATION_LAG_DAYS,
            )
        plans.append(plan)
    if not plans:
        logger.error(
            "Nothing to request: no year in %d-%d has a fully published month yet.", start, end
        )
        return 2

    raw_dir = data_dir / "raw" / RAW_DIR_NAME
    raw_dir.mkdir(parents=True, exist_ok=True)

    client = _new_client()
    total_chunks = len(plans) * len(STATISTICS)
    chunk_i = 0
    rows_by_province: dict[str, list[dict]] = {c.province_code: [] for c in capitals}

    for plan in plans:
        paths: dict[str, Path] = {}
        for statistic in STATISTICS:
            chunk_i += 1
            logger.info("=== chunk [%d/%d]: %d %s ===", chunk_i, total_chunks, plan.year, statistic)
            paths[statistic] = download_chunk(client, raw_dir, plan, statistic, ITALY_BBOX)
        for row in extract_year_rows(paths, capitals, plan.year):
            rows_by_province[row["province_code"]].append(row)

    bad: list[tuple[str, str]] = []
    all_rows: list[dict] = []
    for cap in capitals:
        rows = rows_by_province[cap.province_code]
        for column, rate in null_rates(rows).items():
            if rate > MAX_NULL_RATE:
                bad.append((cap.province_code, column))
                logger.error(
                    "[%s] %s: %.1f%% of %s values are null (limit %.1f%%). If all three "
                    "columns are null, its ERA5-Land cell is probably ocean — nudge lat/lon "
                    "inland in dbt/seeds/province_capitals.csv and rerun. If only this one "
                    "is, the %s chunks under data/raw/cds/ are bad: delete them and rerun.",
                    cap.province_code,
                    cap.capital_city,
                    100 * rate,
                    column,
                    100 * MAX_NULL_RATE,
                    COLUMN_TO_STATISTIC[column],
                )
        all_rows.extend(r for r in rows if r["t_mean"] is not None)

    if bad:
        logger.error(
            "Refusing to write the snapshot: %d city/column pair(s) exceed the null limit "
            "(%s). A partially-null city produces a plausible but wrong warming rate.",
            len(bad),
            ", ".join(f"{code}.{column}" for code, column in bad),
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

    snapshot_path = write_snapshot(all_rows, data_dir)
    upsert_fetch_receipt(
        data_dir / "source-receipts.json",
        "weather",
        provider="Copernicus C3S ERA5-Land",
        source_flow=CDS_DATASET_ID,
        request_url=f"https://cds.climate.copernicus.eu/datasets/{CDS_DATASET_ID}",
        raw_path=f"data/{raw_dir.relative_to(data_dir)}",
        raw_bytes=snapshot_path.read_bytes(),
        count_lines=False,
    )
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    command, rest = argv[0], argv[1:]
    if command == "refresh-timeseries":
        if not rest:
            return cmd_refresh_timeseries()
        if len(rest) == 2:
            try:
                return cmd_refresh_timeseries(int(rest[0]), int(rest[1]))
            except ValueError:
                print(__doc__)
                return 2
        print(__doc__)
        return 2
    if command != "refresh":
        print(__doc__)
        return 2
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
