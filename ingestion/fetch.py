"""Fetch/refresh CLI: ISTAT SDMX -> raw CSV -> normalized Parquet snapshot.

Usage:
    python -m ingestion.fetch discover "delitti"     # find dataflow IDs
    python -m ingestion.fetch dims economy_inflation  # dimension order for `key`
    python -m ingestion.fetch normalize               # re-normalize existing raw CSVs
    python -m ingestion.fetch refresh                 # fetch all registry datasets
    python -m ingestion.fetch refresh crime_reported  # fetch one dataset
    python -m ingestion.fetch sample                  # generate synthetic dev data

The dashboard reads ONLY the normalized Parquet files in data/ (via DuckDB).
It never calls the ISTAT API directly.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import duckdb
import yaml
from pydantic import BaseModel, Field

from ingestion.sdmx_client import IstatClient, SdmxError

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ingestion.fetch")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
MARTS_DIR = DATA_DIR / "marts"  # dbt writes marts here; dbt won't mkdir itself
REGISTRY_PATH = Path(__file__).resolve().parent / "registry.yaml"

NORMALIZED_COLUMNS = [
    "territory",
    "territory_name",
    "category",
    "category_name",
    "period",
    "value",
]


# A component spec is one dimension ID or a list of candidates tried in order
# (ISTAT dataflows disagree on names, e.g. ITTER107 vs REF_AREA).
Candidates = str | list[str]


class ColumnMap(BaseModel):
    territory: Candidates
    territory_name: Candidates | None = None  # derived from combined labels if absent
    category: Candidates
    category_name: Candidates | None = None  # derived from combined labels if absent
    period: Candidates = "TIME_PERIOD"
    value: Candidates = "OBS_VALUE"


class DatasetConfig(BaseModel):
    domain: str
    title: str
    dataflow_id: str
    search_hint: str
    key: str = "ALL"
    start_period: str | None = None
    timeout_s: int = 900  # hard cap per dataset; huge ALL extractions can crawl
    columns: ColumnMap
    # Keep only rows whose component code is in the list, e.g. {FREQ: A}.
    # Keys are component IDs (candidates ok), values one code or a list.
    filters: dict[str, Candidates] = Field(default_factory=dict)


class Registry(BaseModel):
    datasets: dict[str, DatasetConfig] = Field(default_factory=dict)


def load_registry() -> Registry:
    with REGISTRY_PATH.open() as fh:
        return Registry.model_validate(yaml.safe_load(fh))


def _candidates(spec: Candidates | None) -> list[str]:
    if spec is None:
        return []
    return [spec] if isinstance(spec, str) else list(spec)


def _resolve_column(available: set[str], spec: Candidates | None) -> str | None:
    """Find the raw CSV column for a component spec.

    Matches exactly first, then by SDMX-CSV `labels=both` combined headers,
    where a component ID becomes a header like "REF_AREA: Territorio".
    """
    lower_map = {c.lower(): c for c in available}
    for cand in _candidates(spec):
        exact = lower_map.get(cand.lower())
        if exact is not None:
            return exact
        prefix = cand.lower() + ":"
        for col in sorted(available):
            if col.lower().startswith(prefix):
                return col
    return None


def _code_expr(col: str) -> str:
    """The code part of a possibly-combined "CODE: Label" cell value."""
    c = f'CAST("{col}" AS VARCHAR)'
    return (
        f"CASE WHEN strpos({c}, ': ') > 0 THEN substr({c}, 1, strpos({c}, ': ') - 1) ELSE {c} END"
    )


def _label_expr(col: str) -> str:
    """The label part of a possibly-combined "CODE: Label" cell value (else NULL)."""
    c = f'CAST("{col}" AS VARCHAR)'
    return f"CASE WHEN strpos({c}, ': ') > 0 THEN substr({c}, strpos({c}, ': ') + 2) ELSE NULL END"


def normalize_raw_csv(name: str, cfg: DatasetConfig, raw_csv: Path) -> Path:
    """Raw SDMX-CSV -> normalized Parquet with a fixed schema, via DuckDB.

    Handles both header styles ISTAT produces:
    - plain component IDs ("ITTER107", "TIME_PERIOD", ...)
    - `labels=both` combined headers ("REF_AREA: Territorio") whose cell
      values are also combined ("ITC4: Lombardia") — split into code + label.
    """
    out_path = DATA_DIR / f"{name}.parquet"
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    con = duckdb.connect()
    try:
        available = {
            row[0]
            for row in con.execute(
                "SELECT column_name FROM (DESCRIBE SELECT * FROM read_csv_auto(?, header=true, all_varchar=true))",
                [str(raw_csv)],
            ).fetchall()
        }
        cols = cfg.columns

        def missing(spec: Candidates | None, target: str) -> None:
            logger.warning(
                "[%s] no column matches %r — writing NULL %s; fix `columns` in "
                "registry.yaml. Raw CSV columns: %s",
                name,
                spec,
                target,
                ", ".join(sorted(available)),
            )

        def dim_exprs(
            code_spec: Candidates, name_spec: Candidates | None, code_target: str, name_target: str
        ) -> list[str]:
            """SELECT expressions for a dimension: code column + label column."""
            code_col = _resolve_column(available, code_spec)
            if code_col is None:
                missing(code_spec, code_target)
                return [
                    f"CAST(NULL AS VARCHAR) AS {code_target}",
                    f"CAST(NULL AS VARCHAR) AS {name_target}",
                ]
            name_col = _resolve_column(available, name_spec)
            if name_col is not None and name_col != code_col:
                name_expr = f'CAST("{name_col}" AS VARCHAR)'
            else:
                # Derive the label from the combined cell; fall back to the code.
                name_expr = f"COALESCE({_label_expr(code_col)}, {_code_expr(code_col)})"
            return [
                f"{_code_expr(code_col)} AS {code_target}",
                f"{name_expr} AS {name_target}",
            ]

        select_parts: list[str] = []
        select_parts += dim_exprs(
            cols.territory, cols.territory_name, "territory", "territory_name"
        )
        select_parts += dim_exprs(cols.category, cols.category_name, "category", "category_name")

        period_col = _resolve_column(available, cols.period)
        if period_col is None:
            missing(cols.period, "period")
            select_parts.append("CAST(NULL AS VARCHAR) AS period")
        else:
            select_parts.append(f"{_code_expr(period_col)} AS period")

        value_col = _resolve_column(available, cols.value)
        clauses: list[str] = []
        if value_col is None:
            missing(cols.value, "value")
            select_parts.append("CAST(NULL AS DOUBLE) AS value")
        else:
            select_parts.append(f'TRY_CAST("{value_col}" AS DOUBLE) AS value')
            clauses.append(f'TRY_CAST("{value_col}" AS DOUBLE) IS NOT NULL')

        for component, allowed in cfg.filters.items():
            col = _resolve_column(available, component)
            if col is None:
                logger.warning(
                    "[%s] filter component %r not found in raw CSV — filter skipped (columns: %s)",
                    name,
                    component,
                    ", ".join(sorted(available)),
                )
                continue
            codes = ", ".join("'" + c.replace("'", "''") + "'" for c in _candidates(allowed))
            clauses.append(f"{_code_expr(col)} IN ({codes})")

        where = " AND ".join(clauses) if clauses else "TRUE"

        select = ",\n            ".join(select_parts)
        con.execute(
            f"""
            COPY (
                SELECT {select}
                FROM read_csv_auto(?, header=true, all_varchar=true)
                WHERE {where}
            ) TO '{tmp_path}' (FORMAT PARQUET)
            """,
            [str(raw_csv)],
        )
        count_row = con.execute(f"SELECT count(*) FROM read_parquet('{tmp_path}')").fetchone()
        rows = int(count_row[0]) if count_row is not None else 0
    finally:
        con.close()
    # Atomic swap: a crash mid-write leaves the previous snapshot intact
    # instead of a corrupt/truncated parquet that later runs would consume.
    tmp_path.replace(out_path)
    if rows == 0:
        logger.warning(
            "[%s] wrote %s with 0 rows — filters may be too strict or mappings wrong",
            name,
            out_path,
        )
    else:
        logger.info("[%s] wrote %s (%d rows)", name, out_path, rows)
    return out_path


async def fetch_dataset(client: IstatClient, name: str, cfg: DatasetConfig) -> None:
    logger.info("[%s] fetching dataflow %s ...", name, cfg.dataflow_id)
    raw = await client.get_data_csv(cfg.dataflow_id, key=cfg.key, start_period=cfg.start_period)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_DIR / f"{name}.csv"
    tmp_raw = raw_path.with_name(raw_path.name + ".tmp")
    tmp_raw.write_bytes(raw)
    tmp_raw.replace(raw_path)  # atomic: no truncated raw CSVs on interrupt
    logger.info("[%s] saved raw CSV (%.1f MB)", name, len(raw) / 1e6)
    normalize_raw_csv(name, cfg, raw_path)


async def cmd_refresh(only: str | None = None) -> int:
    registry = load_registry()
    targets = registry.datasets
    if only is not None:
        if only not in targets:
            logger.error("Unknown dataset %r. Known: %s", only, ", ".join(targets))
            return 2
        targets = {only: targets[only]}

    # Sequential on purpose: gentler on ISTAT, clearer logs, and the DuckDB
    # snapshot is rebuilt after EACH dataset so the dashboard fills up
    # incrementally instead of all-or-nothing.
    MARTS_DIR.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    async with IstatClient() as client:
        for i, (name, cfg) in enumerate(targets.items(), start=1):
            logger.info("=== [%d/%d] %s ===", i, len(targets), name)
            if cfg.dataflow_id.startswith("TODO"):
                logger.warning(
                    "[%s] dataflow_id is a placeholder (%s) — skipped. "
                    'Find the real ID with: just discover "%s"',
                    name,
                    cfg.dataflow_id,
                    cfg.search_hint,
                )
                continue
            try:
                async with asyncio.timeout(cfg.timeout_s):
                    await fetch_dataset(client, name, cfg)
            except TimeoutError:
                failures.append(name)
                logger.error(
                    "[%s] gave up after %ds — the extraction is too big for key=%r. "
                    "Narrow the `key` or raise `timeout_s` in registry.yaml.",
                    name,
                    cfg.timeout_s,
                    cfg.key,
                )
                continue
            except Exception as exc:  # one bad dataset must not sink the rest
                failures.append(name)
                logger.error("[%s] FAILED: %s", name, exc)
                continue
            logger.info("[%s] snapshot updated — dashboard can use it now", name)
    ensure_placeholder_snapshots(registry)
    if failures:
        logger.error("Refresh finished with failures: %s", ", ".join(failures))
        return 1
    logger.info("Refresh complete.")
    return 0


async def cmd_discover(keyword: str) -> int:
    async with IstatClient() as client:
        try:
            flows = await client.search_dataflows(keyword)
        except SdmxError as exc:
            logger.error("Discovery failed: %s", exc)
            return 1
    if not flows:
        print(f"No dataflows matching {keyword!r}")
        return 0
    width = max(len(f.flow_id) for f in flows)
    for f in flows:
        print(f"{f.flow_id:<{width}}  v{f.version:<6} {f.name}")
    return 0


def ensure_placeholder_snapshots(registry: Registry) -> None:
    """Write an EMPTY normalized parquet for any registry dataset that has no
    snapshot yet, so dbt sources always resolve (models degrade to 0 rows
    instead of failing the whole build)."""
    con = duckdb.connect()
    try:
        for name in registry.datasets:
            out = DATA_DIR / f"{name}.parquet"
            if out.exists():
                continue
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            con.execute(
                f"""
                COPY (
                    SELECT CAST(NULL AS VARCHAR) AS territory,
                           CAST(NULL AS VARCHAR) AS territory_name,
                           CAST(NULL AS VARCHAR) AS category,
                           CAST(NULL AS VARCHAR) AS category_name,
                           CAST(NULL AS VARCHAR) AS period,
                           CAST(NULL AS DOUBLE) AS value
                    WHERE FALSE
                ) TO '{out}' (FORMAT PARQUET)
                """
            )
            logger.info("[%s] no snapshot yet — wrote empty placeholder %s", name, out.name)
    finally:
        con.close()


def cmd_normalize(only: str | None = None) -> int:
    """Re-normalize existing raw CSVs without re-downloading anything."""
    registry = load_registry()
    targets = registry.datasets
    if only is not None:
        if only not in targets:
            logger.error("Unknown dataset %r. Known: %s", only, ", ".join(targets))
            return 2
        targets = {only: targets[only]}

    done = 0
    for name, cfg in targets.items():
        raw_path = RAW_DIR / f"{name}.csv"
        if not raw_path.exists():
            logger.info("[%s] no raw CSV at %s — skipped", name, raw_path)
            continue
        normalize_raw_csv(name, cfg, raw_path)
        done += 1
    ensure_placeholder_snapshots(registry)
    if done == 0:
        logger.error("Nothing to normalize — run `refresh` first.")
        return 1
    return 0


async def cmd_dims(dataset_or_flow: str) -> int:
    """Print a dataflow's dimension order, for narrowing `key` in registry.yaml."""
    registry = load_registry()
    cfg = registry.datasets.get(dataset_or_flow)
    flow_id = cfg.dataflow_id if cfg is not None else dataset_or_flow
    async with IstatClient() as client:
        try:
            dims = await client.get_dimensions(flow_id)
        except SdmxError as exc:
            logger.error("Could not read dimensions: %s", exc)
            return 1
    print(f"Dimension order for {flow_id} (dotted `key` uses this order):")
    for i, dim in enumerate(dims, start=1):
        print(f"  {i}. {dim}")
    print()
    print("key syntax: one slot per dimension, joined by '.', blank slot = all values.")
    example = ["A"] + [""] * (len(dims) - 1)
    print(f'example — annual only, everything else unfiltered: key: "{".".join(example)}"')
    print("multiple codes in one slot: A+Q ; time is filtered via start_period, not the key.")
    return 0


def cmd_sample() -> int:
    from ingestion.sample_data import generate_all

    generate_all(DATA_DIR)
    MARTS_DIR.mkdir(parents=True, exist_ok=True)
    ensure_placeholder_snapshots(load_registry())
    logger.info("Sample data generated. NOTE: this is SYNTHETIC data for dev only.")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 1:
        print(__doc__)
        return 2
    command, *rest = argv
    if command == "discover":
        if not rest:
            print("usage: python -m ingestion.fetch discover <keyword>")
            return 2
        return asyncio.run(cmd_discover(rest[0]))
    if command == "refresh":
        return asyncio.run(cmd_refresh(rest[0] if rest else None))
    if command == "normalize":
        return cmd_normalize(rest[0] if rest else None)
    if command == "dims":
        if not rest:
            print("usage: python -m ingestion.fetch dims <dataset-name-or-dataflow-id>")
            return 2
        return asyncio.run(cmd_dims(rest[0]))
    if command == "sample":
        return cmd_sample()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
