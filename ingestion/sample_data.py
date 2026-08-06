"""Synthetic sample data for offline development.

Generates Parquet files with the SAME normalized schema the real pipeline
produces, so the dashboard is fully functional before the first real fetch.
Values are plausible-looking but FAKE — never present them as ISTAT data.
"""

from __future__ import annotations

import logging
import random
from pathlib import Path

import polars as pl

logger = logging.getLogger(__name__)

REGIONS: list[tuple[str, str]] = [
    ("ITC1", "Piemonte"),
    ("ITC3", "Liguria"),
    ("ITC4", "Lombardia"),
    ("ITH3", "Veneto"),
    ("ITH5", "Emilia-Romagna"),
    ("ITI1", "Toscana"),
    ("ITI4", "Lazio"),
    ("ITF1", "Abruzzo"),
    ("ITF3", "Campania"),
    ("ITF4", "Puglia"),
    ("ITG1", "Sicilia"),
    ("ITG2", "Sardegna"),
]

YEARS = list(range(2006, 2025))

CRIME_TYPES = [
    ("FURTO", "Furti"),
    ("RAPINA", "Rapine"),
    ("TRUFFA", "Truffe e frodi informatiche"),
    ("LESIONI", "Lesioni dolose"),
    ("STUPEF", "Stupefacenti"),
    ("OMICIDIO", "Omicidi volontari"),
]


def _rows_crime(rng: random.Random) -> list[dict]:
    base = {
        "FURTO": 90_000,
        "RAPINA": 3_500,
        "TRUFFA": 12_000,
        "LESIONI": 5_000,
        "STUPEF": 3_000,
        "OMICIDIO": 40,
    }
    rows = []
    for code, name in REGIONS:
        scale = rng.uniform(0.3, 1.6)
        for ccode, cname in CRIME_TYPES:
            level = base[ccode] * scale
            for year in YEARS:
                trend = 1.0 + (0.04 if ccode == "TRUFFA" else -0.015) * (year - 2006)
                rows.append(
                    {
                        "territory": code,
                        "territory_name": name,
                        "category": ccode,
                        "category_name": cname,
                        "period": str(year),
                        "value": round(max(level * trend * rng.uniform(0.92, 1.08), 0)),
                    }
                )
    return rows


def _rows_population(rng: random.Random, foreign: bool) -> list[dict]:
    rows = []
    national: dict[str, float] = {}
    for code, name in REGIONS:
        base = rng.uniform(1.2e6, 9.5e6)
        share0 = rng.uniform(0.03, 0.09) if foreign else 1.0
        for year in YEARS:
            growth = 1.0 + (0.035 if foreign else 0.001) * (year - 2006)
            value = round(base * share0 * growth * rng.uniform(0.995, 1.005))
            rows.append(
                {
                    "territory": code,
                    "territory_name": name,
                    "category": "TOT",
                    "category_name": "Totale",
                    "period": str(year),
                    "value": value,
                }
            )
            national[str(year)] = national.get(str(year), 0.0) + value
    rows.extend(
        {
            "territory": "IT",
            "territory_name": "Italy",
            "category": "TOT",
            "category_name": "Totale",
            "period": year,
            "value": int(total),
        }
        for year, total in national.items()
    )
    return rows


def _rows_unemployment(rng: random.Random) -> list[dict]:
    rows = []
    for code, name in REGIONS:
        south = code.startswith(("ITF", "ITG"))
        base = rng.uniform(11.0, 19.0) if south else rng.uniform(4.0, 8.0)
        for year in YEARS:
            crisis = 3.0 if 2012 <= year <= 2016 else 0.0
            rows.append(
                {
                    "territory": code,
                    "territory_name": name,
                    "category": "TOT",
                    "category_name": "Totale",
                    "period": str(year),
                    "value": round(max(base + crisis + rng.uniform(-0.8, 0.8), 1.0), 1),
                }
            )
    return rows


def _rows_inflation(rng: random.Random) -> list[dict]:
    """Monthly all-items index (like the real NIC dataflow, MEASURE=index)."""
    profile = {
        2008: 3.3,
        2009: 0.8,
        2012: 3.0,
        2015: 0.1,
        2016: -0.1,
        2021: 1.9,
        2022: 8.1,
        2023: 5.7,
        2024: 1.1,
    }
    rows = []
    index = 100.0
    for year in YEARS:
        yoy = profile.get(year, rng.uniform(0.5, 2.2))
        monthly_growth = (1.0 + yoy / 100.0) ** (1.0 / 12.0)
        for month in range(1, 13):
            index *= monthly_growth
            rows.append(
                {
                    "territory": "IT",
                    "territory_name": "Italy",
                    "category": "00",
                    "category_name": "all items",
                    "period": f"{year}-{month:02d}",
                    "value": round(index, 1),
                }
            )
    return rows


def generate_all(data_dir: Path, seed: int = 42) -> None:
    rng = random.Random(seed)
    datasets = {
        "crime_reported": _rows_crime(rng),
        "population_resident": _rows_population(rng, foreign=False),
        "population_foreign": _rows_population(rng, foreign=True),
        "labor_unemployment": _rows_unemployment(rng),
        "economy_inflation": _rows_inflation(rng),
        "income_regional": _rows_income(rng),
    }
    data_dir.mkdir(parents=True, exist_ok=True)
    generate_raw_crime_csv(data_dir / "raw", seed=seed)
    generate_raw_offenders_csv(data_dir / "raw", seed=seed)
    for name, rows in datasets.items():
        df = pl.DataFrame(rows).with_columns(pl.col("value").cast(pl.Float64))
        out = data_dir / f"{name}.parquet"
        df.write_parquet(out)
        logger.info("[sample] %s: %d rows -> %s", name, len(df), out.name)


# ------------------------------------------------------------------
# Raw SDMX-CSV sample (mirrors dataflow 73_58's real combined format)
# so the dbt models run offline before the first real fetch.

RAW_CRIME_HEADER = (
    '"DATAFLOW","FREQ: Frequency","REF_AREA: Territory","DATA_TYPE: Indicator",'
    '"TYPE_OFFENCE: Type of offence","NATURE_CRIME: Nature of the crime",'
    '"JUDICIAL_OFFICE: Judicial office",'
    '"TIME_CRIME_SENTENCE: Time interval between the committed crime date and the sentence date",'
    '"PRINCIPAL_SECURITY_MEASURES: Principal security measures",'
    '"PREVIOUS_CONVICTIONS_RELAPSE: Previous convictions and relapse",'
    '"DISTRICT_COURT_APPEAL: District Court of Appeal",'
    '"YEAR_CRIME: Year when the crime was committed",'
    '"AGE_CRIME_COMMITTED: Age when the crime was committed",'
    '"AGE_SERIOUS_CRIMECOMMIT: Age when the most serious crime was committed",'
    '"SEX: Sex","TIME_PERIOD: Time","OBS_VALUE"'
)

RAW_CRIME_OFFENCES = [
    ("THEFT", "theft"),
    ("ROBBERY", "robbery"),
    ("FRAUD", "fraud and cyber fraud"),
    ("INJURIES", "voluntary injuries"),
    ("DRUGS", "drug-related crimes"),
    ("MURDER", "voluntary manslaughter"),
]

RAW_CRIME_AGES = [
    ("TOTAL", "total"),
    ("Y18-24", "18-24 years"),
    ("Y25-34", "25-34 years"),
    ("Y35-54", "35-54 years"),
    ("Y_GE55", "55 years and over"),
]

RAW_CRIME_SEXES = [("1", "males"), ("2", "females"), ("9", "total")]


def generate_raw_crime_csv(raw_dir: Path, seed: int = 42) -> Path:
    """Synthetic raw CSV in the exact combined labels=both shape of 73_58."""
    rng = random.Random(seed)
    raw_dir.mkdir(parents=True, exist_ok=True)
    out = raw_dir / "crime_reported.csv"

    pinned = (
        '"ALL: all items","ALL: all items","TOTAL: total","ALL: all items",'
        '"ALL: all items","99: all districts","ALL: all items"'
    )
    territories = [("IT", "Italy"), *[(code, name) for code, name in REGIONS]]
    base_by_offence = {
        "THEFT": 9000,
        "ROBBERY": 1200,
        "FRAUD": 2500,
        "INJURIES": 1800,
        "DRUGS": 2200,
        "MURDER": 60,
    }

    lines = [RAW_CRIME_HEADER]
    for tcode, tname in territories:
        t_scale = 1.0 if tcode == "IT" else rng.uniform(0.03, 0.15)
        for ocode, oname in RAW_CRIME_OFFENCES:
            for acode, aname in RAW_CRIME_AGES:
                a_share = 1.0 if acode == "TOTAL" else rng.uniform(0.1, 0.35)
                for scode, sname in RAW_CRIME_SEXES:
                    s_share = 1.0 if scode == "9" else (0.8 if scode == "1" else 0.2)
                    for year in YEARS:
                        trend = 1.0 - 0.01 * (year - YEARS[0])
                        value = base_by_offence[ocode] * t_scale * a_share * s_share
                        value = max(round(value * trend * rng.uniform(0.9, 1.1)), 0)
                        lines.append(
                            f'"IT1:73_58(1.0)","A: annual","{tcode}: {tname}",'
                            f'"FELONYFJ: number of felonies committed by persons convicted by final judgement",'
                            f'"{ocode}: {oname}",{pinned},"{acode}: {aname}",'
                            f'"TOTAL: total","{scode}: {sname}",{year},{value}'
                        )
    out.write_text("\n".join(lines) + "\n")
    logger.info("[sample] raw crime CSV: %d rows -> %s", len(lines) - 1, out)
    return out


# ------------------------------------------------------------------
# Raw offenders CSV sample (dataflow family 73_230 DCCV_AUTVITTPS):
# alleged offenders by province/region, crime type, sex, age, citizenship.

RAW_OFFENDERS_HEADER = (
    '"DATAFLOW","FREQ: Frequency","REF_AREA: Territory","DATA_TYPE: Indicator",'
    '"TYPE_CRIME: Type of crime","SEX: Sex","AGE: Age","CITIZENSHIP: Citizenship",'
    '"COUNTRY_CITIZEN: Country of citizenship","TIME_PERIOD: Time","OBS_VALUE"'
)

OFFENDER_CRIMES = [
    ("THEFT", "theft"),
    ("ROBBERY", "robbery"),
    ("FRAUD", "fraud and cyber fraud"),
    ("INJURIES", "voluntary injuries"),
    ("DRUGS", "drug-related crimes"),
]

OFFENDER_AGES = [
    ("TOTAL", "total"),
    ("Y14-17", "14-17 years"),
    ("Y18-24", "18-24 years"),
    ("Y25-44", "25-44 years"),
    ("Y_GE45", "45 years and over"),
]

OFFENDER_CITIZENSHIP = [
    ("TOTAL", "total"),
    ("ITL", "italian"),
    ("FRG", "foreign"),
]


def generate_raw_offenders_csv(raw_dir: Path, seed: int = 42) -> Path:
    """Synthetic raw CSV mirroring the expected 73_230 offenders shape."""
    rng = random.Random(seed)
    raw_dir.mkdir(parents=True, exist_ok=True)
    out = raw_dir / "crime_offenders.csv"

    territories = [("IT", "Italy"), *[(code, name) for code, name in REGIONS]]
    base = {"THEFT": 5000, "ROBBERY": 900, "FRAUD": 1600, "INJURIES": 1300, "DRUGS": 1700}

    lines = [RAW_OFFENDERS_HEADER]
    for tcode, tname in territories:
        t_scale = 1.0 if tcode == "IT" else rng.uniform(0.03, 0.15)
        for ccode, cname in OFFENDER_CRIMES:
            for acode, aname in OFFENDER_AGES:
                a_share = 1.0 if acode == "TOTAL" else rng.uniform(0.1, 0.35)
                for scode, sname in RAW_CRIME_SEXES:
                    s_share = 1.0 if scode == "9" else (0.82 if scode == "1" else 0.18)
                    for zcode, zname in OFFENDER_CITIZENSHIP:
                        z_share = 1.0 if zcode == "TOTAL" else (0.68 if zcode == "ITL" else 0.32)
                        for year in YEARS:
                            trend = 1.0 - 0.008 * (year - YEARS[0])
                            value = base[ccode] * t_scale * a_share * s_share * z_share
                            value = max(round(value * trend * rng.uniform(0.9, 1.1)), 0)
                            lines.append(
                                f'"IT1:73_230_DF_DCCV_AUTVITTPS_7(1.0)","A: annual",'
                                f'"{tcode}: {tname}","AUTH: alleged offenders reported",'
                                f'"{ccode}: {cname}","{scode}: {sname}","{acode}: {aname}",'
                                f'"{zcode}: {zname}","TOTAL: total",{year},{value}'
                            )
    out.write_text("\n".join(lines) + "\n")
    logger.info("[sample] raw offenders CSV: %d rows -> %s", len(lines) - 1, out)
    return out


def _rows_income(rng: random.Random) -> list[dict]:
    """Per-capita disposable income (EUR) by region-year; north richer."""
    rows = []
    for code, name in REGIONS:
        south = code.startswith(("ITF", "ITG"))
        base = rng.uniform(13000.0, 16500.0) if south else rng.uniform(19000.0, 24500.0)
        for year in YEARS:
            growth = 1.0 + 0.012 * (year - YEARS[0])
            rows.append(
                {
                    "territory": code,
                    "territory_name": name,
                    "category": "INC",
                    "category_name": "disposable income per capita",
                    "period": str(year),
                    "value": round(base * growth * rng.uniform(0.99, 1.01)),
                }
            )
    return rows
