"""ERA5-Land backfill via the Copernicus ARCO point time-series dataset.

Usage:
    python -m ingestion.cds refresh-timeseries            # all cities, 1950-01-02 to the last published day
    python -m ingestion.cds refresh-timeseries 1950 1979  # one year range

Design notes:
- Same underlying data as ingestion/openmeteo.py (ERA5-Land, 2m temperature),
  fetched from `reanalysis-era5-land-timeseries`: one request per capital per
  decade returns hourly values at the nearest 0.1 deg grid cell, aggregated
  locally to daily min/mean/max (UTC days). A full 106-city backfill avoids
  both Open-Meteo's per-point quota and the CDS year-grid queue. Requires a CDS
  account with the ERA5-Land licence accepted (credentials in ~/.cdsapirc).
- Values are RAW grid-cell values, i.e. at the cell's mean orography, not at
  the city. dbt's stg_weather corrects them to the capital's height with a
  lapse rate, using the seed's elevation_m and cell_elevation_m columns (filled
  by ingestion/elevation.py).
- Writes the SAME data/weather_daily.parquet snapshot as ingestion/weather.py,
  through the SAME write_snapshot() and the SAME MAX_NULL_RATE gate: every
  downstream dbt model and page is agnostic to which fetcher populated it.
- Each decade chunk is cached under data/raw/cds_timeseries/, so an aborted run
  resumes; the open (current) decade is always refetched, since it grows.
- cdsapi and xarray are optional dependencies (the `cds` extra in
  pyproject.toml), imported lazily with an actionable CDSError if missing, so
  the rest of the project runs without them.
"""

from __future__ import annotations

import logging
import math
import sys
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    Capital,
    WeatherError,
    load_capitals,
    null_rate,
    write_snapshot,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ingestion.cds")


# CDS's own area convention: [North, West, South, East].
ITALY_BBOX: tuple[float, float, float, float] = (48.0, 6.0, 35.0, 19.0)

KELVIN_TO_CELSIUS_OFFSET = 273.15


# --------------------------------------------------------------------------
# ARCO point-time-series dataset (reanalysis-era5-land-timeseries).
# Each request asks for ONE lat/lon point over a
# date range and gets hourly values at the nearest grid cell back, which is
# what the ECMWF ARCO Data Lake is optimised for. A full 106-city backfill is
# therefore a few lightweight queries per city instead of 228 queued year-grid
# downloads (or 848 quota-limited decade chunks against Open-Meteo).
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


def last_available_day(today: date) -> date:
    """The most recent day ERA5-Land can possibly have published.

    Shares PUBLICATION_LAG_DAYS with ingestion/weather.py so the ARCO and the
    Open-Meteo fetcher cannot disagree about where history ends.
    """
    return today - timedelta(days=PUBLICATION_LAG_DAYS)


def _time_coord_name(ds: Any) -> str:
    for name, coord in ds.coords.items():
        if str(coord.dtype).startswith("datetime64"):
            return name
    raise CDSError(f"No datetime64 coordinate found; coordinates present: {list(ds.coords)}")


def _kelvin_to_celsius_or_none(value: Any) -> float | None:
    # pi-lens-ignore: unchecked-throwing-call-python
    fvalue = float(value)
    return None if math.isnan(fvalue) else fvalue - KELVIN_TO_CELSIUS_OFFSET


# --------------------------------------------------------------------------
# ARCO point-time-series backfill (reanalysis-era5-land-timeseries).
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
    ``date`` range, and ``data_format``. Note this is NOT the ``area`` form of the
    gridded datasets: requesting a point is what makes the ARCO response fast.
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
    import numpy as np  # pyrefly: ignore[missing-import]  # optional extra

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
        exc: Exception | None = None
        queue_limit = False
        try:
            client.retrieve(TIMESERIES_DATASET_ID, request, str(target))
        except Exception as caught:
            exc = caught
            queue_limit = _is_queue_limit_error(caught)
        else:
            return

        if not queue_limit or attempt == QUEUE_LIMIT_RETRIES:
            target.unlink(missing_ok=True)
            assert exc is not None
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
        # The current decade is still growing, so its cache is always stale:
        # keyed on the decade start, a cached 2020s chunk would otherwise be
        # replayed forever and no new day would ever reach the snapshot.
        is_current_decade = chunk_end == end
        if cache.exists() and not is_current_decade:
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
        start = max(date(start_year, 1, 1), TIMESERIES_START_DATE)
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


def main(argv: list[str]) -> int:
    if not argv or argv[0] != "refresh-timeseries":
        print(__doc__)
        return 2
    rest = argv[1:]
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


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
