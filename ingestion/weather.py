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
