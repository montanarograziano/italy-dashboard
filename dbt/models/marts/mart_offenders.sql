-- Dimensional offenders mart: year × region × indicator × crime × sex × age ×
-- citizenship, with per-dimension total flags (same contract as mart_crime).

{{ config(
    materialized='external',
    location=env_var('ITALY_DATA_DIR', 'data') ~ '/marts/mart_offenders.parquet',
    format='parquet',
) }}

select
    year,
    region_code,
    region_name,
    {{ territory_level('region_code') }} as region_level,
    indicator_code,
    indicator_name,
    crime_code,
    crime_name,
    sex_code,
    sex_name,
    age_code,
    age_name,
    citizenship_code,
    citizenship_name,
    -- Totals are flagged by CODE and by NAME: ISTAT hides totals under
    -- unexpected codes (a crime coded 'TOT' named 'total' doubled every
    -- pre-2023 sum until caught).
    (upper(region_code) in ('IT', 'ITTOT'))                   as region_is_total,
    false                                                     as indicator_is_total,
    (upper(crime_code) in ('ALL', 'TOTAL', '_T', 'TOT')
        or lower(crime_name) in ('total', 'totale'))          as crime_is_total,
    (upper(sex_code) in ('9', 'T', '_T', 'TOTAL', 'TOT')
        or lower(sex_name) in ('total', 'totale'))            as sex_is_total,
    (upper(age_code) in ('TOTAL', '_T', 'ALL', 'TOT')
        or lower(age_name) in ('total', 'totale'))            as age_is_total,
    (upper(citizenship_code) in ('TOTAL', '_T', 'ALL', '999', 'TOT')
        or lower(citizenship_name) in ('total', 'totale'))    as citizenship_is_total,
    value
from {{ ref('stg_offenders') }}
