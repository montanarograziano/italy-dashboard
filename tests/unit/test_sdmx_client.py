"""Unit tests for the SDMX client, fully offline via httpx2.MockTransport."""

from __future__ import annotations

import httpx2
import pytest

from ingestion import sdmx_client
from ingestion.sdmx_client import BASE_URL, IstatClient, SdmxError

DATAFLOW_XML = """<?xml version="1.0" encoding="UTF-8"?>
<mes:Structure xmlns:mes="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message"
               xmlns:str="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure"
               xmlns:com="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common">
  <mes:Structures>
    <str:Dataflows>
      <str:Dataflow id="73_58" agencyID="IT1" version="1.2">
        <com:Name xml:lang="it">Delitti denunciati</com:Name>
        <com:Name xml:lang="en">Crimes reported</com:Name>
      </str:Dataflow>
      <str:Dataflow id="22_289" agencyID="IT1" version="1.0">
        <com:Name xml:lang="it">Popolazione residente</com:Name>
      </str:Dataflow>
    </str:Dataflows>
  </mes:Structures>
</mes:Structure>
"""

SAMPLE_CSV = b"DATAFLOW,REF_AREA,TIME_PERIOD,OBS_VALUE\nIT1:73_58(1.2),IT,2023,100\n"


def make_client(handler) -> IstatClient:
    return IstatClient(transport=httpx2.MockTransport(handler))


async def test_list_dataflows_parses_ids_versions_and_english_names():
    async def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path.endswith("/dataflow/IT1/ALL/latest")
        return httpx2.Response(200, text=DATAFLOW_XML)

    async with make_client(handler) as client:
        flows = await client.list_dataflows()

    assert [f.flow_id for f in flows] == ["73_58", "22_289"]
    assert flows[0].name == "Crimes reported"  # English preferred
    assert flows[1].name == "Popolazione residente"  # falls back to first
    assert flows[0].version == "1.2"


async def test_search_dataflows_matches_name_and_id_case_insensitive():
    async def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, text=DATAFLOW_XML)

    async with make_client(handler) as client:
        assert [f.flow_id for f in await client.search_dataflows("CRIMES")] == ["73_58"]
        assert [f.flow_id for f in await client.search_dataflows("22_2")] == ["22_289"]
        # Italian keyword matches even when the display name is English
        assert [f.flow_id for f in await client.search_dataflows("delitti")] == ["73_58"]
        assert await client.search_dataflows("nonexistent") == []


async def test_list_dataflows_rejects_unparseable_body():
    async def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, text="this is not xml")

    async with make_client(handler) as client:
        with pytest.raises(SdmxError, match="Could not parse"):
            await client.list_dataflows()


async def test_get_data_csv_returns_bytes_and_sends_period_params():
    seen: dict = {}

    async def handler(request: httpx2.Request) -> httpx2.Response:
        seen["params"] = dict(request.url.params)
        seen["accept"] = request.headers["Accept"]
        return httpx2.Response(200, content=SAMPLE_CSV)

    async with make_client(handler) as client:
        data = await client.get_data_csv("73_58", start_period="2006", end_period="2024")

    assert data == SAMPLE_CSV
    assert seen["params"] == {"startPeriod": "2006", "endPeriod": "2024"}
    assert "csv" in seen["accept"]


async def test_get_data_csv_rejects_xml_body():
    async def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, text="<error>no data</error>")

    async with make_client(handler) as client:
        with pytest.raises(SdmxError, match="Expected CSV"):
            await client.get_data_csv("73_58")


async def test_404_raises_immediately_with_helpful_message():
    calls = {"n": 0}

    async def handler(request: httpx2.Request) -> httpx2.Response:
        calls["n"] += 1
        return httpx2.Response(404, text="not found")

    async with make_client(handler) as client:
        with pytest.raises(SdmxError, match="check the dataflow ID"):
            await client.get_data_csv("BOGUS")
    assert calls["n"] == 1  # no retries on 404


async def test_transport_errors_are_retried_then_raised(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sdmx_client, "RETRY_BACKOFF_S", 0.0)
    calls = {"n": 0}

    async def handler(request: httpx2.Request) -> httpx2.Response:
        calls["n"] += 1
        raise httpx2.ConnectError("boom")

    async with make_client(handler) as client:
        with pytest.raises(SdmxError, match="Failed after"):
            await client.get_data_csv("73_58")
    assert calls["n"] == sdmx_client.MAX_RETRIES


async def test_transient_error_then_success(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sdmx_client, "RETRY_BACKOFF_S", 0.0)
    calls = {"n": 0}

    async def handler(request: httpx2.Request) -> httpx2.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx2.ConnectError("flaky")
        return httpx2.Response(200, content=SAMPLE_CSV)

    async with make_client(handler) as client:
        assert await client.get_data_csv("73_58") == SAMPLE_CSV
    assert calls["n"] == 2


def test_client_requires_context_manager():
    client = IstatClient()
    with pytest.raises(RuntimeError, match="context manager"):
        _ = client.client


def test_base_url_is_the_current_istat_endpoint():
    # Guards against regressing to the decommissioned sdmx.istat.it host.
    assert "esploradati.istat.it" in BASE_URL


STRUCTURE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<mes:Structure xmlns:mes="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message"
               xmlns:str="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure">
  <mes:Structures>
    <str:DataStructures>
      <str:DataStructure id="DCSP_NIC" agencyID="IT1" version="1.0">
        <str:DataStructureComponents>
          <str:DimensionList>
            <str:Dimension id="REF_AREA" position="2"/>
            <str:Dimension id="FREQ" position="1"/>
            <str:Dimension id="COICOP" position="3"/>
            <str:TimeDimension id="TIME_PERIOD" position="4"/>
          </str:DimensionList>
        </str:DataStructureComponents>
      </str:DataStructure>
    </str:DataStructures>
  </mes:Structures>
</mes:Structure>
"""


async def test_get_dimensions_returns_key_order_without_time():
    async def handler(request: httpx2.Request) -> httpx2.Response:
        assert dict(request.url.params) == {"references": "all"}
        return httpx2.Response(200, text=STRUCTURE_XML)

    async with make_client(handler) as client:
        dims = await client.get_dimensions("167_744")

    # sorted by position, TimeDimension excluded
    assert dims == ["FREQ", "REF_AREA", "COICOP"]
