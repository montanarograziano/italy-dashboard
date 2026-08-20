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
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime

import httpx2

logger = logging.getLogger(__name__)

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"

MODEL = "era5_land"
DAILY_VARS = (
    "temperature_2m_max",
    "temperature_2m_min",
    "temperature_2m_mean",
    "precipitation_sum",
)

# Maps the API's variable names onto our column names.
VAR_TO_COLUMN = {
    "temperature_2m_max": "t_max",
    "temperature_2m_min": "t_min",
    "temperature_2m_mean": "t_mean",
    "precipitation_sum": "precip_sum",
}

DEFAULT_TIMEOUT = httpx2.Timeout(180.0, connect=30.0, read=120.0)
MAX_RETRIES = 3
RETRY_BACKOFF_S = 3.0
# A rate limit is not a transient blip: Open-Meteo's free quotas are per minute,
# per hour and per day, so the shortest window that can possibly have reopened
# is a minute. Retrying a 429 after 3s then 6s is guaranteed to hit the same
# closed door and burn the attempt budget for nothing.
RATE_LIMIT_BACKOFF_S = 60.0
# Longest we will sit blocked on a Retry-After. Beyond this the hourly or daily
# quota is gone, and the right move is to stop and resume later: every decade
# chunk already fetched is on disk, so re-running the same command costs
# nothing but the chunks that are actually missing.
MAX_RETRY_WAIT_S = 300.0
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

        Rate limits (429) are backed off differently from server errors: at
        least RATE_LIMIT_BACKOFF_S, or whatever Retry-After asks for. A wait
        longer than MAX_RETRY_WAIT_S ends the run immediately instead, with the
        server's own reason attached, since the caller's raw cache makes
        resuming later cheap.
        """
        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            retry_after: float | None = None
            rate_limited = False
            try:
                resp = await self.client.get(url, params=params)
                if resp.status_code == 429:
                    # Keep the body's reason: it says WHICH quota was hit
                    # (minutely, hourly, daily), which is what decides between
                    # waiting a minute and resuming tomorrow.
                    rate_limited = True
                    retry_after = _retry_after_seconds(resp)
                    last_error = OpenMeteoError(f"HTTP 429 from {url}: {_reason(resp)}")
                    if retry_after is not None and retry_after > MAX_RETRY_WAIT_S:
                        raise OpenMeteoError(
                            f"Rate limited for {retry_after:.0f}s by {url}: {_reason(resp)}. "
                            "Stopping; re-run the same command to resume from the cache."
                        )
                elif resp.status_code >= 500:
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
                if rate_limited:
                    # Servers can send Retry-After: 0, a small value, or a date already in
                    # the past. Never retry a rate limit faster than the limit window, or
                    # all three attempts burn instantly and the run dies on a limit that
                    # would have cleared.
                    wait = (
                        max(retry_after, RATE_LIMIT_BACKOFF_S)
                        if retry_after is not None
                        else RATE_LIMIT_BACKOFF_S
                    )
                else:
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
        raise OpenMeteoError(
            f"Failed after {MAX_RETRIES} attempts: {url} ({last_error})"
        ) from last_error

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
        """Daily max/min/mean/precipitation for one point over a date range.

        Returns {"time": [...], "t_max": [...], "t_min": [...], "t_mean": [...],
        "precip_sum": [...]}. Missing days keep their None: the caller's null-rate
        gate decides whether a city's coordinate landed on an ERA5-Land ocean cell.
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


def _retry_after_seconds(resp: httpx2.Response) -> float | None:
    """Retry-After as seconds, accepting both forms the RFC allows.

    Returns None when the header is absent or unparseable, in which case the
    caller falls back to RATE_LIMIT_BACKOFF_S. A header in the past clamps to
    zero rather than going negative.
    """
    raw = resp.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def _reason(resp: httpx2.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:200]
    if isinstance(body, dict):
        return str(body.get("reason", body))[:200]
    return str(body)[:200]
