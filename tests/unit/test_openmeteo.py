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
        "precipitation_sum": [0.0, 3.4],
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


async def test_city_elevation_reads_the_most_populous_italian_match():
    payload = json.loads(json.dumps(GEO_MULTI))
    payload["results"][1]["elevation"] = 21.0
    payload["results"][2]["elevation"] = 400.0

    async def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=payload)

    async with make_client(handler) as client:
        assert await client.city_elevation("Roma") == 21.0


async def test_city_elevation_raises_when_the_match_has_none():
    async def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=GEO_MULTI)

    async with make_client(handler) as client:
        with pytest.raises(OpenMeteoError, match="no elevation"):
            await client.city_elevation("Roma")


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
    assert seen["elevation"] == "nan"  # raw cell values; dbt downscales once
    assert seen["start_date"] == "1950-01-01"
    assert seen["end_date"] == "1950-01-02"
    assert out["time"] == ["1950-01-01", "1950-01-02"]
    assert out["t_max"] == [11.4, 12.0]
    assert out["t_min"] == [2.1, 3.0]
    assert out["t_mean"] == [6.5, 7.2]
    assert out["precip_sum"] == [0.0, 3.4]


async def test_daily_temperatures_accepts_model_suffixed_variable_names():
    """Open-Meteo suffixes variables with the model name in some responses."""
    payload = {
        "daily": {
            "time": ["1950-01-01"],
            "temperature_2m_max_era5_land": [11.4],
            "temperature_2m_min_era5_land": [2.1],
            "temperature_2m_mean_era5_land": [6.5],
            "precipitation_sum_era5_land": [1.2],
        }
    }

    async def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=payload)

    async with make_client(handler) as client:
        out = await client.daily_temperatures(41.9, 12.5, date(1950, 1, 1), date(1950, 1, 1))

    assert out["t_max"] == [11.4]
    assert out["t_min"] == [2.1]
    assert out["t_mean"] == [6.5]
    assert out["precip_sum"] == [1.2]


async def test_daily_temperatures_preserves_nulls_as_none():
    payload = {
        "daily": {
            "time": ["1950-01-01", "1950-01-02"],
            "temperature_2m_max": [11.4, None],
            "temperature_2m_min": [2.1, None],
            "temperature_2m_mean": [6.5, None],
            "precipitation_sum": [0.0, None],
        }
    }

    async def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=payload)

    async with make_client(handler) as client:
        out = await client.daily_temperatures(41.9, 12.5, date(1950, 1, 1), date(1950, 1, 2))

    assert out["t_mean"] == [6.5, None]
    assert out["precip_sum"] == [0.0, None]


async def test_daily_temperatures_raises_when_precipitation_is_missing():
    """precip_sum is required from a LIVE fetch: only cached pre-existing
    JSON on disk is allowed to lack it (handled in ingestion.weather, not
    here). A fresh API response missing the var we asked for is a real
    response-shape problem."""
    payload = {
        "daily": {
            "time": ["1950-01-01"],
            "temperature_2m_max": [11.4],
            "temperature_2m_min": [2.1],
            "temperature_2m_mean": [6.5],
        }
    }

    async def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=payload)

    async with make_client(handler) as client:
        with pytest.raises(OpenMeteoError, match="precipitation_sum"):
            await client.daily_temperatures(41.9, 12.5, date(1950, 1, 1), date(1950, 1, 1))


async def test_api_error_body_is_raised_with_its_reason():
    async def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(400, json={"error": True, "reason": "Invalid date range"})

    async with make_client(handler) as client:
        with pytest.raises(OpenMeteoError, match="Invalid date range"):
            await client.daily_temperatures(41.9, 12.5, date(1950, 1, 1), date(1950, 1, 2))


async def test_error_body_on_a_200_response_is_still_raised():
    """Open-Meteo signals some failures with HTTP 200 and an error body."""

    async def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"error": True, "reason": "No data for this location"})

    async with make_client(handler) as client:
        with pytest.raises(OpenMeteoError, match="No data for this location"):
            await client.daily_temperatures(41.9, 12.5, date(1950, 1, 1), date(1950, 1, 2))


@pytest.fixture
def recorded_sleeps(monkeypatch) -> list[float]:
    """Record every backoff instead of serving it, so tests stay instant."""
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(openmeteo.asyncio, "sleep", fake_sleep)
    return waits


async def test_rate_limit_is_retried_then_succeeds(monkeypatch, recorded_sleeps):
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


async def test_rate_limit_backs_off_at_least_a_minute(recorded_sleeps):
    """A 3s/6s backoff cannot outlast a rate-limit window measured in minutes.

    Backing off inside the window guarantees every retry is spent on a door
    that is still shut, and the run dies on a limit it could have waited out.
    """

    async def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(429, text="Minutely API request limit exceeded")

    async with make_client(handler) as client:
        with pytest.raises(OpenMeteoError):
            await client.daily_temperatures(41.9, 12.5, date(1950, 1, 1), date(1950, 1, 2))

    assert recorded_sleeps  # it did back off
    assert all(w >= 60.0 for w in recorded_sleeps), recorded_sleeps


async def test_server_errors_keep_the_short_backoff(monkeypatch, recorded_sleeps):
    """5xx is a blip, not a quota: it must not inherit the rate-limit wait."""
    monkeypatch.setattr(openmeteo, "RETRY_BACKOFF_S", 3.0)

    async def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(503, text="boom")

    async with make_client(handler) as client:
        with pytest.raises(OpenMeteoError):
            await client.daily_temperatures(41.9, 12.5, date(1950, 1, 1), date(1950, 1, 2))

    assert recorded_sleeps == [3.0, 6.0]


async def test_retry_after_header_is_honoured(recorded_sleeps):
    calls = {"n": 0}

    async def handler(request: httpx2.Request) -> httpx2.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx2.Response(429, text="slow down", headers={"Retry-After": "90"})
        return httpx2.Response(200, json=ARCHIVE_OK)

    async with make_client(handler) as client:
        out = await client.daily_temperatures(41.9, 12.5, date(1950, 1, 1), date(1950, 1, 2))

    assert recorded_sleeps == [90.0]
    assert out["t_mean"] == [6.5, 7.2]


async def test_retry_after_zero_is_floored_to_the_rate_limit_backoff(recorded_sleeps):
    """Retry-After: 0 must not be taken literally: it would burn all retries
    instantly against a quota window measured in minutes."""
    calls = {"n": 0}

    async def handler(request: httpx2.Request) -> httpx2.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx2.Response(429, text="slow down", headers={"Retry-After": "0"})
        return httpx2.Response(200, json=ARCHIVE_OK)

    async with make_client(handler) as client:
        out = await client.daily_temperatures(41.9, 12.5, date(1950, 1, 1), date(1950, 1, 2))

    assert recorded_sleeps == [openmeteo.RATE_LIMIT_BACKOFF_S]
    assert out["t_mean"] == [6.5, 7.2]


async def test_retry_after_past_http_date_is_floored_to_the_rate_limit_backoff(recorded_sleeps):
    """A Retry-After HTTP-date already in the past clamps to 0.0s upstream in
    _retry_after_seconds; that 0.0 must still be floored here, not honoured."""
    calls = {"n": 0}

    async def handler(request: httpx2.Request) -> httpx2.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx2.Response(
                429,
                text="slow down",
                headers={"Retry-After": "Sun, 06 Nov 1994 08:49:37 GMT"},
            )
        return httpx2.Response(200, json=ARCHIVE_OK)

    async with make_client(handler) as client:
        out = await client.daily_temperatures(41.9, 12.5, date(1950, 1, 1), date(1950, 1, 2))

    assert recorded_sleeps == [openmeteo.RATE_LIMIT_BACKOFF_S]
    assert out["t_mean"] == [6.5, 7.2]


async def test_retry_after_above_the_floor_is_honoured_as_is(recorded_sleeps):
    """A Retry-After between the floor and the ceiling is a real, larger wait
    from the server and must not be flattened down to the floor."""
    calls = {"n": 0}

    async def handler(request: httpx2.Request) -> httpx2.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx2.Response(429, text="slow down", headers={"Retry-After": "90"})
        return httpx2.Response(200, json=ARCHIVE_OK)

    async with make_client(handler) as client:
        out = await client.daily_temperatures(41.9, 12.5, date(1950, 1, 1), date(1950, 1, 2))

    assert recorded_sleeps == [90.0]
    assert out["t_mean"] == [6.5, 7.2]


async def test_rate_limit_reason_is_preserved_in_the_error(recorded_sleeps):
    """A daily limit and a minutely limit call for different operator
    responses, so the body's reason must survive into the message."""

    async def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(429, json={"reason": "Daily API request limit exceeded"})

    async with make_client(handler) as client:
        with pytest.raises(OpenMeteoError, match="Daily API request limit exceeded"):
            await client.daily_temperatures(41.9, 12.5, date(1950, 1, 1), date(1950, 1, 2))


async def test_a_long_retry_after_stops_the_run_instead_of_blocking(recorded_sleeps):
    """Hours of Retry-After means the daily quota is gone. Stop, do not sleep:
    the raw cache makes resuming tomorrow cost only the missing chunks."""

    async def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            429,
            json={"reason": "Daily API request limit exceeded"},
            headers={"Retry-After": "7200"},
        )

    async with make_client(handler) as client:
        with pytest.raises(OpenMeteoError, match="re-run the same command to resume"):
            await client.daily_temperatures(41.9, 12.5, date(1950, 1, 1), date(1950, 1, 2))

    assert recorded_sleeps == []


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
        "precipitation_sum",
    )
    assert json.loads(json.dumps(ARCHIVE_OK))  # payload fixture stays JSON-serialisable
