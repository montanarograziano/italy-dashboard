"""Fetch/refresh CLI: SDMX/hub source -> raw CSV -> normalized Parquet snapshot.

Usage:
    python -m ingestion.fetch discover "delitti"          # find ISTAT dataflow IDs
    python -m ingestion.fetch discover "naspi" inps        # find INPS dataflow IDs
    python -m ingestion.fetch dims economy_inflation       # dimension order for `key`
    python -m ingestion.fetch dims DFB_SOME_FLOW inps      # same, for an INPS flow id
    python -m ingestion.fetch normalize                    # re-normalize existing raw CSVs
    python -m ingestion.fetch refresh                      # fetch all registry datasets
    python -m ingestion.fetch refresh crime_reported       # fetch one dataset
    python -m ingestion.fetch sample                       # generate synthetic dev data

The dashboard reads ONLY the normalized Parquet files in data/ (via DuckDB).
It never calls a live provider API directly. Each registry dataset has a
`provider` (default `istat`); `inps` routes through ingestion/inps_client.py
instead of ingestion/sdmx_client.py, everything downstream (normalize,
filters, snapshot) is identical.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import duckdb  # type: ignore[import-not-found]
import yaml
from pydantic import BaseModel, Field  # type: ignore[import-not-found]

from ingestion.inps_client import InpsClient, InpsError
from ingestion.sdmx_client import IstatClient, SdmxError
from ingestion.ustat_client import USTATClient

AnyClient = IstatClient | InpsClient | USTATClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ingestion.fetch")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("ITALY_DATA_DIR", str(PROJECT_ROOT / "data")))
RAW_DIR = DATA_DIR / "raw"
MARTS_DIR = DATA_DIR / "marts"  # compatibility for callers; paths derive from DATA_DIR
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
    observation_status: Candidates | None = None  # optional OBS_STATUS-like field


class DatasetConfig(BaseModel):
    domain: str
    title: str
    dataflow_id: str
    search_hint: str
    # "inps" routes through ingestion/inps_client.py (StatKit hub middleware)
    # instead of ISTAT's SDMX-REST. The hub has no server-side filter at all,
    # so `key`/`start_period` below are silently ignored for it — narrow with
    # `filters` only, same as any ISTAT dataflow that needs client-side filters.
    # "ustat" routes through ingestion/ustat_client.py (CKAN REST API).
    provider: Literal["istat", "inps", "ustat"] = "istat"
    key: str = "ALL"
    start_period: str | None = None
    timeout_s: int = 900  # hard cap per dataset; huge ALL extractions can crawl
    columns: ColumnMap
    # Keep only rows whose component code is in the list, e.g. {FREQ: A}.
    # Keys are component IDs (candidates ok), values one code or a list.
    filters: dict[str, Candidates] = Field(default_factory=dict)
    # Provider-specific "value not available" markers (e.g. USTAT's 'N').
    # Rows carrying one are excluded like blank cells, never published as
    # numbers and never fatal. Anything else non-numeric stays fatal.
    value_na_codes: list[str] = Field(default_factory=list)


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


# Same concept, different SDMX component IDs across dataflows. A filter
# names one semantic dimension; one available spelling is sufficient.
_SEMANTIC_ALIASES = {
    "sex": ("SEX", "SEXISTAT1"),
    "sexistat1": ("SEX", "SEXISTAT1"),
    "age": ("AGE", "ETA1"),
    "eta1": ("AGE", "ETA1"),
    "marital_status": ("MARITAL_STATUS", "STATCIV2"),
    "statciv2": ("MARITAL_STATUS", "STATCIV2"),
}


def _semantic_candidates(component: str) -> list[str]:
    return list(_SEMANTIC_ALIASES.get(component.lower(), (component,)))


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
        for spec, target in (
            (cols.territory, "territory"),
            (cols.category, "category"),
            (cols.period, "period"),
            (cols.value, "value"),
        ):
            if _resolve_column(available, spec) is None:
                raise ValueError(
                    f"[{name}] required mapping {target!r} absent for {spec!r}; "
                    f"available columns: {', '.join(sorted(available))}"
                )

        def dim_exprs(
            code_spec: Candidates, name_spec: Candidates | None, code_target: str, name_target: str
        ) -> list[str]:
            """SELECT expressions for a dimension: code column + label column."""
            code_col = _resolve_column(available, code_spec)
            assert code_col is not None
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
        value_col = _resolve_column(available, cols.value)
        assert period_col is not None and value_col is not None
        select_parts += [
            f"{_code_expr(period_col)} AS period",
            # Italian extracts (USTAT) may carry decimal commas ('9,335' ≈ 9.34
            # €/hour). The fallback only fires when the plain cast fails AND
            # the cell is exactly digits-comma-digits, so dot-decimal SDMX
            # values can never be reinterpreted.
            f"""COALESCE(
                TRY_CAST("{value_col}" AS DOUBLE),
                CASE WHEN regexp_matches(trim("{value_col}"), '^[0-9]+,[0-9]+$')
                     THEN TRY_CAST(replace(trim("{value_col}"), ',', '.') AS DOUBLE)
                END
            ) AS value""",
        ]

        clauses: list[str] = []
        for component, allowed in cfg.filters.items():
            col = next(
                (
                    resolved
                    for candidate in _semantic_candidates(component)
                    if (resolved := _resolve_column(available, candidate)) is not None
                ),
                None,
            )
            if col is None:
                raise ValueError(
                    f"[{name}] required filter dimension {component!r} absent; "
                    f"available columns: {', '.join(sorted(available))}"
                )
            codes = ", ".join("'" + c.replace("'", "''") + "'" for c in _candidates(allowed))
            clauses.append(f"{_code_expr(col)} IN ({codes})")

        # Empty observation cells and declared not-available markers are
        # legitimate in SDMX/CKAN extracts (an institution row without this
        # intervention type, a suppressed cell): EXCLUDED, not fatal. Any
        # other non-numeric value stays fatal — schema drift, validated below.
        clauses.append(f"NULLIF(trim(\"{value_col}\"), '') IS NOT NULL")
        if cfg.value_na_codes:
            na = ", ".join("'" + c.replace("'", "''") + "'" for c in cfg.value_na_codes)
            clauses.append(f'trim("{value_col}") NOT IN ({na})')

        status_col = _resolve_column(
            available,
            cols.observation_status or ["OBS_STATUS", "OBS_STATUS_DESCR", "OBS_STATUS_LABEL"],
        )
        if status_col is not None:
            select_parts.append(f'CAST("{status_col}" AS VARCHAR) AS observation_status')
        where = " AND ".join(clauses) if clauses else "TRUE"

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp_path.unlink(missing_ok=True)
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
        invalid_row = con.execute(
            f"""
            SELECT count(*) FROM read_parquet('{tmp_path}')
            WHERE value IS NULL
               OR NULLIF(trim(CAST(territory AS VARCHAR)), '') IS NULL
               OR NULLIF(trim(CAST(category AS VARCHAR)), '') IS NULL
               OR NULLIF(trim(CAST(period AS VARCHAR)), '') IS NULL
            """
        ).fetchone()
        rows = int(count_row[0]) if count_row is not None else 0
        invalid = int(invalid_row[0]) if invalid_row is not None else 0
        if rows == 0:
            raise ValueError(f"[{name}] normalization produced no rows")
        if invalid:
            raise ValueError(f"[{name}] normalization produced {invalid} invalid key/value rows")
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    finally:
        con.close()
    # Atomic swap: failed validation leaves previous snapshot untouched.
    tmp_path.replace(out_path)
    logger.info("[%s] wrote %s (%d rows)", name, out_path, rows)
    return out_path


async def fetch_dataset(client: AnyClient, name: str, cfg: DatasetConfig) -> None:
    logger.info("[%s] fetching dataflow %s ...", name, cfg.dataflow_id)
    raw = await client.get_data_csv(cfg.dataflow_id, key=cfg.key, start_period=cfg.start_period)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_DIR / f"{name}.csv"
    tmp_raw = raw_path.with_name(raw_path.name + ".tmp")
    tmp_raw.write_bytes(raw)
    try:
        # Normalize staged bytes first; failed validation preserves raw and
        # normalized snapshots from previous successful refreshes.
        normalize_raw_csv(name, cfg, tmp_raw)
        tmp_raw.replace(raw_path)
    finally:
        tmp_raw.unlink(missing_ok=True)
    logger.info("[%s] saved raw CSV (%.1f MB)", name, len(raw) / 1e6)


async def cmd_refresh(only: str | None = None) -> int:
    registry = load_registry()
    targets = registry.datasets
    if only is not None:
        if only not in targets:
            logger.error("Unknown dataset %r. Known: %s", only, ", ".join(targets))
            return 2
        targets = {only: targets[only]}

    # Sequential on purpose: gentler on the source APIs, clearer logs, and the
    # DuckDB snapshot is rebuilt after EACH dataset so the dashboard fills up
    # incrementally instead of all-or-nothing. One client per provider actually
    # used, opened once and shared across all of that provider's datasets.
    MARTS_DIR.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    providers_used = {cfg.provider for cfg in targets.values()}
    async with contextlib.AsyncExitStack() as stack:
        clients: dict[str, AnyClient] = {}
        if "istat" in providers_used:
            clients["istat"] = await stack.enter_async_context(IstatClient())
        if "inps" in providers_used:
            clients["inps"] = await stack.enter_async_context(InpsClient())
        if "ustat" in providers_used:
            clients["ustat"] = await stack.enter_async_context(USTATClient())
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
                failures.append(name)
                continue
            client = clients[cfg.provider]
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
    from ingestion.weather import ensure_weather_placeholder

    ensure_weather_placeholder(DATA_DIR)
    _write_provenance_marker("partial" if failures else "live", failures)
    if failures:
        logger.error("Refresh finished with failures: %s", ", ".join(failures))
        return 1
    logger.info("Refresh complete.")
    return 0


async def cmd_discover(keyword: str, provider: str = "istat") -> int:
    client_cm: AnyClient
    if provider == "inps":
        client_cm = InpsClient()
    elif provider == "ustat":
        client_cm = USTATClient()
    else:
        client_cm = IstatClient()
    async with client_cm as client:
        try:
            flows = await client.search_dataflows(keyword)
        except (SdmxError, InpsError) as exc:
            logger.error("Discovery failed: %s", exc)
            return 1
    if not flows:
        print(f"No dataflows matching {keyword!r}")
        return 0
    width = max(len(f.flow_id) for f in flows)
    for f in flows:
        print(f"{f.flow_id:<{width}}  v{f.version:<6} {f.name}")
    return 0


PROVENANCE_MARKER = DATA_DIR / ".provenance.json"


def _write_provenance_marker(
    mode: Literal["sample", "live", "partial"],
    failed_datasets: list[str] | None = None,
    data_dir: Path | None = None,
) -> None:
    """Record how the data/ snapshot now on disk was produced.

    `scripts/generate_provenance_manifest.py` reads this to report a
    synthetic-vs-real status instead of guessing from file contents. `sample`
    = synthetic dev data (`ingestion.fetch sample`); `live` = fetched from a
    real upstream provider (`ingestion.fetch refresh`). Written unconditionally
    on `refresh`, even a partial one (see `cmd_refresh`'s per-dataset failures):
    whatever DID land is genuinely live data, and the manifest's own row-count
    check is what catches a dataset that failed to update.

    Deliberately not written by `cmd_normalize` or `ingestion.weather`/`cds`
    run standalone: those are secondary paths reprocessing what `sample` or
    `refresh` already fetched, so they don't change which of the two modes
    produced the snapshot. A snapshot from before this marker existed simply
    has none — the manifest reports that honestly as "unknown" rather than
    assuming either mode.
    """
    target = data_dir or DATA_DIR
    target.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "mode": mode,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    if failed_datasets:
        payload["failed_datasets"] = failed_datasets
    (target / ".provenance.json").write_text(json.dumps(payload, indent=2) + "\n")


def ensure_placeholder_snapshots(registry: Registry) -> None:
    """Write an EMPTY normalized parquet for any registry dataset that has no
    snapshot yet, so dbt sources always resolve (models degrade to 0 rows
    instead of failing the whole build)."""
    con = duckdb.connect()
    try:
        # Missing snapshots stay missing. Empty files make failed refreshes look
        # successful and let downstream builds publish incomplete data.
        return
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
    failures: list[str] = []
    for name, cfg in targets.items():
        raw_path = RAW_DIR / f"{name}.csv"
        if not raw_path.exists():
            logger.info("[%s] no raw CSV at %s — skipped", name, raw_path)
            continue
        try:
            normalize_raw_csv(name, cfg, raw_path)
            done += 1
        except Exception as exc:
            failures.append(name)
            logger.error("[%s] FAILED: %s", name, exc)
    if failures:
        logger.error("Normalization finished with failures: %s", ", ".join(failures))
        return 1
    if done == 0:
        logger.error("Nothing to normalize — run `refresh` first.")
        return 1
    return 0


async def cmd_dims(dataset_or_flow: str, provider: str | None = None) -> int:
    """Print a dataflow's dimension order, for narrowing `key` in registry.yaml.

    For an `inps` dataflow this order is informational only (the hub has no
    server-side filter key); narrow with `filters` after download instead.
    """
    registry = load_registry()
    cfg = registry.datasets.get(dataset_or_flow)
    flow_id = cfg.dataflow_id if cfg is not None else dataset_or_flow
    resolved_provider = provider or (cfg.provider if cfg is not None else "istat")
    if resolved_provider == "ustat":
        logger.error("USTAT/CKAN datasets have no SDMX dimension order.")
        return 1
    client_cm: IstatClient | InpsClient = (
        InpsClient() if resolved_provider == "inps" else IstatClient()
    )
    async with client_cm as client:
        try:
            dims = await client.get_dimensions(flow_id)
        except (SdmxError, InpsError) as exc:
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


def cmd_sample(output_dir: str | Path | None = None) -> int:
    """Generate synthetic data outside production snapshot by default."""
    target = Path(output_dir) if output_dir is not None else DATA_DIR / "sample"
    if target.resolve() == (PROJECT_ROOT / "data").resolve():
        logger.error("Refusing to write synthetic data to production data/; choose isolated path")
        return 2

    from ingestion.sample_data import generate_all

    generate_all(target)
    (target / "marts").mkdir(parents=True, exist_ok=True)

    from ingestion.weather import ensure_weather_placeholder

    ensure_weather_placeholder(target)
    _write_provenance_marker("sample", data_dir=target)
    logger.info("Sample data generated at %s. NOTE: SYNTHETIC data for dev only.", target)
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 1:
        print(__doc__)
        return 2
    command, *rest = argv
    if command == "discover":
        if not rest:
            print("usage: python -m ingestion.fetch discover <keyword> [provider]")
            return 2
        return asyncio.run(cmd_discover(rest[0], *rest[1:2]))
    if command == "refresh":
        return asyncio.run(cmd_refresh(rest[0] if rest else None))
    if command == "normalize":
        return cmd_normalize(rest[0] if rest else None)
    if command == "dims":
        if not rest:
            print("usage: python -m ingestion.fetch dims <dataset-name-or-dataflow-id> [provider]")
            return 2
        return asyncio.run(cmd_dims(rest[0], rest[1] if len(rest) > 1 else None))
    if command == "sample":
        if len(rest) > 1:
            print("usage: python -m ingestion.fetch sample [isolated-data-dir]")
            return 2
        return cmd_sample(rest[0] if rest else None)
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
