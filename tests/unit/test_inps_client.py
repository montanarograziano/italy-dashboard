"""Unit tests for the INPS hub client, fully offline via httpx2.MockTransport.

Fixtures follow the shapes documented in
https://github.com/ondata/opensdmx docs/inps/middleware-api.md (verified
against opensdmx's released source, not a live INPS response — see
ingestion/inps_client.py's module docstring for why).
"""

from __future__ import annotations

import httpx2
import pytest

from ingestion import inps_client
from ingestion.inps_client import BASE_URL, InpsClient, InpsError

CATALOG_NODE_1 = {
    "categoryGroups": [
        {
            "categories": [
                {
                    "id": "OS15",
                    "label": "Politiche occupazionali",
                    "datasetIdentifiers": [],
                    "childrenCategories": [
                        {
                            "id": "OS15_NASPI",
                            "label": "NASPI",
                            "datasetIdentifiers": ["INPS,DFB_NASPI_REG,1.0"],
                            "childrenCategories": [],
                        }
                    ],
                }
            ]
        }
    ],
    "datasetMap": {"INPS,DFB_NASPI_REG,1.0": {"title": "Beneficiari NASPI per regione"}},
}

EMPTY_CATALOG = {"categoryGroups": [], "datasetMap": {}}

STRUCTURE = {
    "criteria": [
        {
            "id": "TERRITORIO",
            "label": "Territory of work",
            "extra": {"DataStructureRef": "INPS+CL_HIER_TERRITORIO_REG+1.0"},
        },
        {"id": "SESSO", "label": "Sex"},
    ],
    "timeDimension": "TIME_PERIOD",
    "territorialDimension": "TERRITORIO",
}

SAMPLE_CSV = b"TERRITORIO,SESSO,TIME_PERIOD,OBS_VALUE\nITC4,T,2023,1000\n"


def make_client(handler) -> InpsClient:
    return InpsClient(transport=httpx2.MockTransport(handler))


def _node_from_path(path: str) -> int:
    """Pull the numeric node id out of `.../nodes/{n}/...` regardless of the
    base URL's own path prefix (BASE_URL already has 3 path segments)."""
    parts = path.strip("/").split("/")
    return int(parts[parts.index("nodes") + 1])


def catalog_handler(node_to_catalog: dict[int, dict]):
    async def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path.endswith("/catalog")
        node = _node_from_path(request.url.path)
        return httpx2.Response(200, json=node_to_catalog.get(node, EMPTY_CATALOG))

    return handler


async def test_list_dataflows_walks_every_node_and_uses_catalog_title():
    handler = catalog_handler({1: CATALOG_NODE_1})

    async with make_client(handler) as client:
        flows = await client.list_dataflows()

    assert [f.flow_id for f in flows] == ["DFB_NASPI_REG"]
    assert flows[0].node == 1
    assert flows[0].version == "1.0"
    assert flows[0].name == "Beneficiari NASPI per regione"  # datasetMap title wins


async def test_list_dataflows_falls_back_to_leaf_category_label():
    catalog = {
        "categoryGroups": [
            {
                "categories": [
                    {
                        "id": "OS15",
                        "label": "Politiche occupazionali",
                        "datasetIdentifiers": ["INPS,DFB_NO_TITLE,1.0"],
                        "childrenCategories": [],
                    }
                ]
            }
        ],
        "datasetMap": {},  # no title for this dataflow
    }
    handler = catalog_handler({1: catalog})

    async with make_client(handler) as client:
        flows = await client.list_dataflows()

    assert flows[0].name == "Politiche occupazionali"  # leaf label fallback


async def test_list_dataflows_raises_when_every_node_is_empty():
    handler = catalog_handler({})

    async with make_client(handler) as client:
        with pytest.raises(InpsError, match="empty across every node"):
            await client.list_dataflows()


async def test_search_dataflows_matches_id_or_name_case_insensitively():
    handler = catalog_handler({1: CATALOG_NODE_1})

    async with make_client(handler) as client:
        assert [f.flow_id for f in await client.search_dataflows("naspi")] == ["DFB_NASPI_REG"]
        assert [f.flow_id for f in await client.search_dataflows("regione")] == ["DFB_NASPI_REG"]
        assert await client.search_dataflows("nonexistent") == []


async def test_get_dimensions_excludes_time_dimension_and_keeps_order():
    async def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/catalog"):
            return httpx2.Response(200, json=CATALOG_NODE_1)
        assert request.url.path.endswith(
            "/nodes/1/datasets/INPS,DFB_NASPI_REG,1.0/structure"
        )
        return httpx2.Response(200, json=STRUCTURE)

    async with make_client(handler) as client:
        dims = await client.get_dimensions("DFB_NASPI_REG")

    assert dims == ["TERRITORIO", "SESSO"]


async def test_get_dimensions_raises_on_unknown_flow():
    handler = catalog_handler({1: CATALOG_NODE_1})

    async with make_client(handler) as client:
        with pytest.raises(InpsError, match="not found in any node catalog"):
            await client.get_dimensions("BOGUS_FLOW")


async def test_get_codelist_returns_flat_code_to_name_map():
    async def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/catalog"):
            return httpx2.Response(200, json=CATALOG_NODE_1)
        assert request.url.path.endswith(
            "/nodes/1/datasets/INPS,DFB_NASPI_REG,1.0/PartialCodelists/SESSO"
        )
        return httpx2.Response(
            200,
            json={
                "criteria": [
                    {
                        "id": "SESSO",
                        "values": [
                            {"id": "1", "name": "Maschi", "isSelectable": True},
                            {"id": "2", "name": "Femmine", "isSelectable": True},
                        ],
                    }
                ]
            },
        )

    async with make_client(handler) as client:
        codes = await client.get_codelist("DFB_NASPI_REG", "SESSO")

    assert codes == {"1": "Maschi", "2": "Femmine"}


async def test_get_codelist_descends_into_non_selectable_parents():
    """A hierarchical dimension (e.g. TERRITORIO) returns parent nodes flagged
    isSelectable: false; their children must be fetched and the parent itself
    dropped from the result, not returned as if it were a leaf code."""

    async def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/catalog"):
            return httpx2.Response(200, json=CATALOG_NODE_1)
        body = request.content.decode()
        if body == "[]":
            # Root level: one selectable leaf, one non-selectable parent.
            return httpx2.Response(
                200,
                json={
                    "criteria": [
                        {
                            "id": "TERRITORIO",
                            "values": [
                                {"id": "IT", "name": "Italia", "isSelectable": True},
                                {"id": "ITC", "name": "Nord-ovest", "isSelectable": False},
                            ],
                        }
                    ]
                },
            )
        # Children of the ITC parent.
        assert "ITC" in body
        return httpx2.Response(
            200,
            json={
                "criteria": [
                    {
                        "id": "TERRITORIO",
                        "values": [{"id": "ITC4", "name": "Lombardia", "isSelectable": True}],
                    }
                ]
            },
        )

    async with make_client(handler) as client:
        codes = await client.get_codelist("DFB_NASPI_REG", "TERRITORIO")

    assert codes == {"IT": "Italia", "ITC4": "Lombardia"}  # ITC (parent) is not a code


async def test_get_data_csv_posts_empty_criteria_and_returns_bytes():
    seen: dict = {}

    async def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/catalog"):
            return httpx2.Response(200, json=CATALOG_NODE_1)
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = request.content
        return httpx2.Response(200, content=SAMPLE_CSV)

    async with make_client(handler) as client:
        data = await client.get_data_csv("DFB_NASPI_REG")

    assert data == SAMPLE_CSV
    assert seen["method"] == "POST"
    assert seen["path"].endswith("/nodes/1/datasets/INPS,DFB_NASPI_REG,1.0/download/csv")
    assert seen["body"] == b"[]"


async def test_get_data_csv_ignores_key_and_period_arguments():
    """Signature-compatible with IstatClient.get_data_csv, but these do nothing:
    the hub has no server-side filter or period window."""

    async def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/catalog"):
            return httpx2.Response(200, json=CATALOG_NODE_1)
        assert "startPeriod" not in request.url.params
        assert "endPeriod" not in request.url.params
        return httpx2.Response(200, content=SAMPLE_CSV)

    async with make_client(handler) as client:
        data = await client.get_data_csv(
            "DFB_NASPI_REG", key="A.ITC4..", start_period="2010", end_period="2020"
        )

    assert data == SAMPLE_CSV


async def test_get_data_csv_rejects_a_json_error_body_served_as_200():
    async def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/catalog"):
            return httpx2.Response(200, json=CATALOG_NODE_1)
        return httpx2.Response(200, json={"error": "truncated"})

    async with make_client(handler) as client:
        with pytest.raises(InpsError, match="got JSON"):
            await client.get_data_csv("DFB_NASPI_REG")


async def test_404_raises_immediately_with_no_retries():
    calls = {"n": 0}

    async def handler(request: httpx2.Request) -> httpx2.Response:
        calls["n"] += 1
        return httpx2.Response(404, text="not found")

    async with make_client(handler) as client:
        with pytest.raises(InpsError, match="Not found"):
            await client._request_json("nodes/1/catalog")
    assert calls["n"] == 1


async def test_transport_errors_are_retried_then_raised(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(inps_client, "RETRY_BACKOFF_S", 0.0)
    calls = {"n": 0}

    async def handler(request: httpx2.Request) -> httpx2.Response:
        calls["n"] += 1
        raise httpx2.ConnectError("boom")

    async with make_client(handler) as client:
        with pytest.raises(InpsError, match="Failed after"):
            await client.list_dataflows()
    assert calls["n"] == inps_client.MAX_RETRIES


async def test_transient_error_then_success(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(inps_client, "RETRY_BACKOFF_S", 0.0)
    calls = {"n": 0}

    async def handler(request: httpx2.Request) -> httpx2.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx2.ConnectError("flaky")
        node = _node_from_path(request.url.path)
        return httpx2.Response(200, json=CATALOG_NODE_1 if node == 1 else EMPTY_CATALOG)

    async with make_client(handler) as client:
        flows = await client.list_dataflows()
    # 1 failed + 1 retried attempt for node 1, plus one call each for nodes 2-4.
    assert calls["n"] == 5
    assert [f.flow_id for f in flows] == ["DFB_NASPI_REG"]


def test_client_requires_context_manager():
    client = InpsClient()
    with pytest.raises(RuntimeError, match="context manager"):
        _ = client.client


def test_base_url_is_the_documented_hub_endpoint():
    assert "opendata.inps.it" in BASE_URL


def test_node_map_matches_the_documented_observatories():
    assert inps_client.NODES == {
        "politiche_occupazionali": 1,
        "pensioni": 2,
        "dipendenti": 3,
        "imprese": 4,
    }
