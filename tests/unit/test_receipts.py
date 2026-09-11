"""Unit tests: ingestion/receipts.py's upsert helper and its call sites.

Covers merge semantics (other datasets AND other keys on the same dataset
survive), atomicity (no .tmp left behind), and the fetch-vs-normalize split:
`fetch_dataset` (a real fetch) writes a receipt, `normalize_raw_csv` (re-run
of already-downloaded bytes) never does.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

from ingestion import fetch
from ingestion.fetch import ColumnMap, DatasetConfig
from ingestion.receipts import upsert_fetch_receipt, upsert_receipt

# --------------------------------------------------------------- upsert_receipt


def test_upsert_receipt_preserves_other_datasets(tmp_path: Path):
    path = tmp_path / "source-receipts.json"
    path.write_text(json.dumps({"other_dataset": {"status": "kept", "extra": 1}}))

    upsert_receipt(path, "crime_offenders", {"status": "fetched", "provider": "ISTAT"})

    data = json.loads(path.read_text())
    assert data["other_dataset"] == {"status": "kept", "extra": 1}
    assert data["crime_offenders"] == {"status": "fetched", "provider": "ISTAT"}


def test_upsert_receipt_preserves_extra_keys_on_the_same_dataset(tmp_path: Path):
    path = tmp_path / "source-receipts.json"
    path.write_text(
        json.dumps({"crime_offenders": {"interim_raw": {"path": "x"}, "status": "old"}})
    )

    upsert_receipt(path, "crime_offenders", {"status": "fetched"})

    entry = json.loads(path.read_text())["crime_offenders"]
    assert entry["interim_raw"] == {"path": "x"}
    assert entry["status"] == "fetched"


def test_upsert_receipt_creates_a_missing_file(tmp_path: Path):
    path = tmp_path / "source-receipts.json"
    upsert_receipt(path, "new_ds", {"status": "fetched"})
    assert json.loads(path.read_text())["new_ds"] == {"status": "fetched"}


def test_upsert_receipt_is_atomic_no_tmp_left(tmp_path: Path):
    path = tmp_path / "source-receipts.json"
    upsert_receipt(path, "x", {"a": 1})
    assert not path.with_name(path.name + ".tmp").exists()


# ----------------------------------------------------------- upsert_fetch_receipt


def test_upsert_fetch_receipt_records_hash_bytes_lines(tmp_path: Path):
    path = tmp_path / "source-receipts.json"
    raw = b"a,b\n1,2\n3,4\n"

    upsert_fetch_receipt(
        path,
        "ds",
        provider="ISTAT",
        source_flow="73_1",
        request_url="https://esploradati.istat.it/SDMXWS/rest/data/73_1/ALL",
        raw_path="data/raw/ds.csv",
        raw_bytes=raw,
    )

    entry = json.loads(path.read_text())["ds"]
    assert entry["status"] == "fetched"
    assert entry["provider"] == "ISTAT"
    assert entry["source_flow"] == "73_1"
    assert entry["raw_path"] == "data/raw/ds.csv"
    assert entry["raw_sha256"] == hashlib.sha256(raw).hexdigest()
    assert entry["bytes"] == len(raw)
    assert entry["lines"] == 3
    assert entry["retrieved_at"]  # non-empty ISO timestamp


def test_upsert_fetch_receipt_count_lines_false_omits_lines(tmp_path: Path):
    path = tmp_path / "source-receipts.json"

    upsert_fetch_receipt(
        path,
        "weather",
        provider="Open-Meteo",
        source_flow=None,
        request_url="https://archive-api.open-meteo.com/v1/archive",
        raw_path=None,
        raw_bytes=b"\x00\x01binary-parquet-bytes",
        count_lines=False,
    )

    entry = json.loads(path.read_text())["weather"]
    assert "lines" not in entry
    assert "raw_path" not in entry
    assert "source_flow" not in entry


# ------------------------------------------------------- fetch.py integration


def _config() -> DatasetConfig:
    return DatasetConfig(
        domain="crime",
        title="Test dataset",
        dataflow_id="73_58",
        search_hint="test",
        provider="istat",
        columns=ColumnMap(territory="ITTER107", category="REATI"),
    )


class _FakeClient:
    def __init__(self, payload: bytes, request_url: str):
        self._payload = payload
        self.last_request_url = request_url

    async def get_data_csv(self, flow_id, key="ALL", start_period=None, end_period=None):
        return self._payload


def test_fetch_dataset_upserts_a_fetched_receipt(data_dir: Path):
    csv_bytes = b"ITTER107,REATI,TIME_PERIOD,OBS_VALUE\nIT,A,2023,1\n"
    url = "https://esploradati.istat.it/SDMXWS/rest/data/73_58/ALL"
    client: Any = _FakeClient(csv_bytes, url)

    asyncio.run(fetch.fetch_dataset(client, "test_ds", _config()))

    entry = json.loads((data_dir / "source-receipts.json").read_text())["test_ds"]
    assert entry["status"] == "fetched"
    assert entry["provider"] == "ISTAT"
    assert entry["source_flow"] == "73_58"
    assert entry["request_url"] == url
    assert entry["raw_path"] == "data/raw/test_ds.csv"
    assert entry["raw_sha256"] == hashlib.sha256(csv_bytes).hexdigest()
    assert entry["bytes"] == len(csv_bytes)


def test_fetch_dataset_preserves_other_receipt_keys(data_dir: Path):
    receipts_path = data_dir / "source-receipts.json"
    receipts_path.write_text(json.dumps({"crime_offenders": {"interim_raw": {"a": 1}}}))
    csv_bytes = b"ITTER107,REATI,TIME_PERIOD,OBS_VALUE\nIT,A,2023,1\n"
    client: Any = _FakeClient(csv_bytes, "https://example/x")

    asyncio.run(fetch.fetch_dataset(client, "test_ds", _config()))

    data = json.loads(receipts_path.read_text())
    assert data["crime_offenders"] == {"interim_raw": {"a": 1}}
    assert data["test_ds"]["status"] == "fetched"


def test_normalize_raw_csv_does_not_write_a_receipt(data_dir: Path, monkeypatch):
    calls: list[object] = []
    monkeypatch.setattr(fetch, "upsert_fetch_receipt", lambda *a, **k: calls.append((a, k)))
    raw = data_dir / "raw.csv"
    raw.write_text("ITTER107,REATI,TIME_PERIOD,OBS_VALUE\nIT,A,2023,1\n")

    fetch.normalize_raw_csv("test_ds", _config(), raw)

    assert calls == []
    assert not (data_dir / "source-receipts.json").exists()
