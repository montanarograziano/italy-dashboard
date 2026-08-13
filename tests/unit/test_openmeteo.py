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
