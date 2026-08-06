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
    (upper(region_code) in ('IT', 'ITTOT'))                   as region_is_total,
    false                                                     as indicator_is_total,
    (upper(crime_code) in ('ALL', 'TOTAL', '_T'))             as crime_is_total,
    (upper(sex_code) in ('9', 'T', '_T', 'TOTAL'))            as sex_is_total,
    (upper(age_code) in ('TOTAL', '_T', 'ALL'))               as age_is_total,
    (upper(citizenship_code) in ('TOTAL', '_T', 'ALL', '999')) as citizenship_is_total,
    value
from {{ ref('stg_offenders') }}
