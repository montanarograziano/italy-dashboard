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
