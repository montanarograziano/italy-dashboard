"""Unit tests for the USTAT (MUR) DSU client, fully offline via
httpx2.MockTransport.

Covers the two behaviors that regressed in the field: CKAN dataset discovery
(picking the latest "Numero di interventi" resource out of a package list)
and CSV decoding (USTAT has published the same resource as both UTF-8 and
ISO-8859-1, so the byte-sniffing fallback in `_decode_csv` is load-bearing,
not decorative).
"""

from __future__ import annotations

import httpx2

from ingestion.ustat_client import (
    USTAT_API_BASE,
    Dataflow,
    USTATClient,
    _decode_csv,
    get_latest_interventi_csv_url,
    list_available_datasets,
)

PACKAGE_LIST = {
    "result": [
        "2022-diritto-allo-studio-universitario-dsu-regionale",
        "2023-diritto-allo-studio-universitario-dsu-regionale",
        "some-unrelated-dataset",
    ]
}

PACKAGE_SHOW_2023 = {
    "result": {
        "resources": [
            {"name": "2023 Altro file", "url": "https://example.org/other.csv"},
            {
                "name": "2023 Numero di interventi",
                "url": "https://example.org/2023_interventi.csv",
            },
        ]
    }
}


def _client(handler) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


# --------------------------------------------------------------- discovery


async def test_list_available_datasets_keeps_only_dsu_packages_by_version():
    async def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path.endswith("/package_list")
        return httpx2.Response(200, json=PACKAGE_LIST)

    async with _client(handler) as client:
        versions = await list_available_datasets(client)

    assert versions == {
        "2022": "2022-diritto-allo-studio-universitario-dsu-regionale",
        "2023": "2023-diritto-allo-studio-universitario-dsu-regionale",
    }


async def test_get_latest_interventi_csv_url_picks_the_highest_version():
    async def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/package_list"):
            return httpx2.Response(200, json=PACKAGE_LIST)
        assert request.url.path.endswith("/package_show")
        assert "2023-diritto" in request.url.params["id"]
        return httpx2.Response(200, json=PACKAGE_SHOW_2023)

    async with _client(handler) as client:
        csv_url, version = await get_latest_interventi_csv_url(client)

    # Not "2023 Altro file": name-matching must select the interventi
    # resource specifically, not just any resource in the newest package.
    assert csv_url == "https://example.org/2023_interventi.csv"
    assert version == "2023"


async def test_search_dataflows_matches_known_keywords_case_insensitively():
    async with USTATClient() as client:
        flows = await client.search_dataflows("Borse")
        assert flows == [
            Dataflow("diritto-allo-studio-universitario-dsu-regionale", "1.0", "DSU Scholarships")
        ]
        assert await client.search_dataflows("nonexistent") == []


def test_api_base_is_the_documented_mur_endpoint():
    assert "dati-ustat.mur.gov.it" in USTAT_API_BASE


# ---------------------------------------------------------------- encoding


def test_decode_csv_prefers_utf8():
    raw = "città;valore\nRoma;10\n".encode("utf-8-sig")
    assert _decode_csv(raw) == "città;valore\nRoma;10\n"


def test_decode_csv_falls_back_to_iso_8859_1_when_bytes_are_not_valid_utf8():
    # USTAT has published this same resource in ISO-8859-1 in the past; the
    # accented byte alone is not valid UTF-8, so utf-8-sig decoding must fail
    # and fall back rather than raise or mangle the text.
    raw = "città;valore\nRoma;10\n".encode("iso-8859-1")
    with_utf8_error = True
    try:
        raw.decode("utf-8-sig")
        with_utf8_error = False
    except UnicodeDecodeError:
        pass
    assert with_utf8_error, "fixture must actually exercise the fallback branch"

    assert _decode_csv(raw) == "città;valore\nRoma;10\n"
