{{ config(
    materialized='external',
    location=env_var('ITALY_DATA_DIR', 'data') ~ '/marts/mart_population.parquet',
    format='parquet',
) }}

select * from {{ ref('stg_population') }}
