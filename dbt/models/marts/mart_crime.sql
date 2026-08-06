-- Dimensional crime mart the dashboard slices: year × region × offence ×
-- sex × age. `is_total` flags per dimension let the query layer either pick
-- the pre-computed total row or aggregate the detail rows, without guessing.

{{ config(
    materialized='external',
    location=env_var('ITALY_DATA_DIR', 'data') ~ '/marts/mart_crime.parquet',
    format='parquet',
) }}

select
    year,
    region_code,
    region_name,
    {{ territory_level('region_code') }} as region_level,
    offence_code,
    offence_name,
    sex_code,
    sex_name,
    age_code,
    age_name,
    (upper(region_code) in ('IT', 'ITTOT'))                    as region_is_total,
    (upper(offence_code) in ('ALL', 'TOTAL', '_T', 'TOT')
        or lower(offence_name) in ('total', 'totale'))         as offence_is_total,
    (upper(sex_code) in ('9', 'T', '_T', 'TOTAL', 'TOT')
        or lower(sex_name) in ('total', 'totale'))             as sex_is_total,
    (upper(age_code) in ('TOTAL', '_T', 'ALL', 'TOT')
        or lower(age_name) in ('total', 'totale'))             as age_is_total,
    value
from {{ ref('stg_crime') }}
