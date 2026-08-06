"""Unit tests: registry validation and the CSV -> Parquet normalization step."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from ingestion.fetch import ColumnMap, DatasetConfig, load_registry, normalize_raw_csv

# --------------------------------------------------------------- registry


def test_registry_loads_and_validates():
    registry = load_registry()
    assert len(registry.datasets) >= 5
    assert "crime_reported" in registry.datasets


def test_registry_datasets_have_expected_domains():
    registry = load_registry()
    domains = {cfg.domain for cfg in registry.datasets.values()}
    assert {"crime", "population", "labor", "economy"} <= domains


def test_registry_dataflow_ids_nonempty():
    registry = load_registry()
    for name, cfg in registry.datasets.items():
        assert cfg.dataflow_id.strip(), f"{name} has an empty dataflow_id"
        assert cfg.search_hint.strip(), f"{name} has an empty search_hint"


# ------------------------------------------------------------- normalize


def _config(columns: ColumnMap) -> DatasetConfig:
    return DatasetConfig(
        domain="crime",
        title="Test dataset",
        dataflow_id="73_58",
        search_hint="test",
        columns=columns,
    )


PLAIN_COLUMNS = ColumnMap(
    territory="ITTER107",
    territory_name="Territorio",
    category="REATI",
    category_name="Tipo",
    period="TIME_PERIOD",
    value="OBS_VALUE",
)

CANDIDATE_COLUMNS = ColumnMap(
    territory=["ITTER107", "REF_AREA"],
    category=["TIPO_REATO", "REATI"],
)


def test_normalize_plain_headers_with_separate_label_columns(data_dir: Path):
    raw = data_dir / "raw.csv"
    raw.write_text(
        "ITTER107,Territorio,REATI,Tipo,TIME_PERIOD,OBS_VALUE,EXTRA\n"
        "ITC4,Lombardia,FURTO,Furti,2023,181000,x\n"
        "ITI4,Lazio,FURTO,Furti,2023,possibly-bad,x\n"  # non-numeric -> dropped
    )
    out = normalize_raw_csv("test_ds", _config(PLAIN_COLUMNS), raw)

    df = pl.read_parquet(out)
    assert df.columns == [
        "territory",
        "territory_name",
        "category",
        "category_name",
        "period",
        "value",
    ]
    assert df.height == 1  # the non-numeric row is filtered out
    row = df.row(0, named=True)
    assert row["territory"] == "ITC4"
    assert row["territory_name"] == "Lombardia"
    assert row["value"] == 181000.0
    assert isinstance(row["value"], float)


def test_normalize_labels_both_combined_headers_and_values(data_dir: Path):
    """ISTAT SDMX-CSV with labels=both: 'ID: Label' headers AND cell values."""
    raw = data_dir / "raw.csv"
    raw.write_text(
        '"DATAFLOW","REF_AREA: Territorio","TIPO_REATO: Tipo di reato",'
        '"TIME_PERIOD: Periodo","OBS_VALUE: Valore"\n'
        '"IT1:73_58(1.2)","ITC4: Lombardia","FURTO: Furti in abitazione",2023,181000\n'
        '"IT1:73_58(1.2)","ITI4: Lazio","FURTO: Furti in abitazione",2023,150000\n'
    )
    out = normalize_raw_csv("test_ds", _config(CANDIDATE_COLUMNS), raw)

    df = pl.read_parquet(out).sort("territory")
    assert df.height == 2
    row = df.row(0, named=True)
    assert row["territory"] == "ITC4"  # code split from combined value
    assert row["territory_name"] == "Lombardia"  # label split from combined value
    assert row["category"] == "FURTO"
    # label keeps everything after the first separator
    assert row["category_name"] == "Furti in abitazione"
    assert row["period"] == "2023"
    assert row["value"] == 181000.0


def test_normalize_candidates_fall_back_across_naming_schemes(data_dir: Path):
    """The same config works for a dataflow using the older ITTER107 naming."""
    raw = data_dir / "raw.csv"
    raw.write_text("ITTER107,TIPO_REATO,TIME_PERIOD,OBS_VALUE\nITC4,FURTO,2023,42\n")
    out = normalize_raw_csv("test_ds", _config(CANDIDATE_COLUMNS), raw)

    row = pl.read_parquet(out).row(0, named=True)
    assert row["territory"] == "ITC4"
    assert row["territory_name"] == "ITC4"  # no label anywhere -> falls back to code
    assert row["category"] == "FURTO"


def test_normalize_missing_component_becomes_null_not_crash(data_dir: Path, caplog):
    raw = data_dir / "raw.csv"
    raw.write_text("ITTER107,TIME_PERIOD,OBS_VALUE\nITC4,2023,42\n")

    out = normalize_raw_csv("test_ds", _config(CANDIDATE_COLUMNS), raw)

    df = pl.read_parquet(out)
    assert df.height == 1
    row = df.row(0, named=True)
    assert row["category"] is None  # no candidate matched
    assert row["category_name"] is None
    assert row["territory"] == "ITC4"  # the rest still works
    assert "no column matches" in caplog.text  # loudly warned, not silent
    assert "ITTER107" in caplog.text  # full column list printed for debugging


def test_normalize_empty_csv_gives_empty_parquet(data_dir: Path):
    raw = data_dir / "raw.csv"
    raw.write_text("ITTER107,Territorio,REATI,Tipo,TIME_PERIOD,OBS_VALUE\n")
    out = normalize_raw_csv("test_ds", _config(PLAIN_COLUMNS), raw)
    assert pl.read_parquet(out).height == 0


def test_normalize_handles_mixed_annual_and_quarterly_periods(data_dir: Path):
    """Regression: DuckDB's sniffer typed TIME_PERIOD as BIGINT from annual
    rows, then crashed on '2018-Q1'. all_varchar parsing must prevent that."""
    raw = data_dir / "raw.csv"
    rows = "".join(
        f"ITC4,FURTO,{2006 + i},100\n"
        for i in range(30)  # numeric-looking sample
    )
    raw.write_text("ITTER107,TIPO_REATO,TIME_PERIOD,OBS_VALUE\n" + rows + "ITC4,FURTO,2018-Q1,42\n")

    out = normalize_raw_csv("test_ds", _config(CANDIDATE_COLUMNS), raw)
    df = pl.read_parquet(out)
    assert df.height == 31
    assert "2018-Q1" in df["period"].to_list()


def test_normalize_filters_keep_only_matching_codes(data_dir: Path):
    """Registry filters drop non-headline slices (quarterly, males-only, ...)."""
    cfg = DatasetConfig(
        domain="labor",
        title="Test",
        dataflow_id="151_914",
        search_hint="test",
        columns=CANDIDATE_COLUMNS,
        filters={"FREQ": "A", "SEX": ["9", "TOTAL"]},
    )
    raw = data_dir / "raw.csv"
    raw.write_text(
        '"ITTER107","TIPO_REATO","FREQ: Frequenza","SEX: Sesso","TIME_PERIOD","OBS_VALUE"\n'
        '"IT","X","A: annual","9: total",2023,8.1\n'
        '"IT","X","Q: quarterly","9: total",2023-Q1,8.3\n'  # dropped: FREQ
        '"IT","X","A: annual","1: males",2023,7.2\n'  # dropped: SEX
    )
    out = normalize_raw_csv("test_ds", cfg, raw)
    df = pl.read_parquet(out)
    assert df.height == 1
    assert df.row(0, named=True)["value"] == 8.1


def test_normalize_unknown_filter_component_is_skipped_with_warning(data_dir: Path, caplog):
    cfg = DatasetConfig(
        domain="labor",
        title="Test",
        dataflow_id="151_914",
        search_hint="test",
        columns=CANDIDATE_COLUMNS,
        filters={"NO_SUCH_DIM": "A"},
    )
    raw = data_dir / "raw.csv"
    raw.write_text("ITTER107,TIPO_REATO,TIME_PERIOD,OBS_VALUE\nIT,X,2023,1\n")
    out = normalize_raw_csv("test_ds", cfg, raw)
    assert pl.read_parquet(out).height == 1  # filter skipped, rows kept
    assert "filter component" in caplog.text


def test_normalize_is_idempotent(data_dir: Path):
    """Re-normalizing the same raw CSV overwrites; never appends or errors."""
    raw = data_dir / "raw.csv"
    raw.write_text("ITTER107,TIPO_REATO,TIME_PERIOD,OBS_VALUE\nITC4,FURTO,2023,42\n")
    out1 = normalize_raw_csv("test_ds", _config(CANDIDATE_COLUMNS), raw)
    first = pl.read_parquet(out1)
    out2 = normalize_raw_csv("test_ds", _config(CANDIDATE_COLUMNS), raw)
    second = pl.read_parquet(out2)
    assert out1 == out2
    assert first.equals(second)
    assert second.height == 1  # no accumulation
    assert not (data_dir / "test_ds.parquet.tmp").exists()  # tmp cleaned up


def test_placeholder_snapshots_do_not_overwrite_real_data(data_dir: Path, monkeypatch):
    import duckdb

    from ingestion import fetch as f
    from ingestion.fetch import ensure_placeholder_snapshots, load_registry

    monkeypatch.setattr(f, "DATA_DIR", data_dir)
    real = data_dir / "labor_unemployment.parquet"
    pl.DataFrame(
        {
            "territory": ["IT"],
            "territory_name": ["Italy"],
            "category": ["T"],
            "category_name": ["t"],
            "period": ["2023"],
            "value": [1.0],
        }
    ).write_parquet(real)

    ensure_placeholder_snapshots(load_registry())
    ensure_placeholder_snapshots(load_registry())  # second call: still safe

    assert pl.read_parquet(real).height == 1  # untouched
    # every registry dataset now has a snapshot file, empty but readable
    for name in load_registry().datasets:
        p = data_dir / f"{name}.parquet"
        assert p.exists()
        duckdb.sql(f"SELECT * FROM read_parquet('{p}')")
