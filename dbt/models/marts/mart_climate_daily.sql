-- Daily climate mart: staging plus the three conventional Italian threshold
-- flags. These read far more plainly to non-specialists than anomalies do.
--
-- Definitions: hot day = daily max >= 30 C; tropical night = daily min >= 20 C;
-- frost day = daily min <= 0 C.

{{ config(
    materialized='external',
    location=env_var('ITALY_DATA_DIR', 'data') ~ '/marts/mart_climate_daily.parquet',
    format='parquet',
    options={'compression': 'zstd'},
) }}

select
    province_code,
    province_name,
    capital_city,
    region_code,
    region_name,
    obs_date,
    year,
    month,
    t_min,
    t_mean,
    t_max,
    (t_max >= 30.0) as is_hot_day,
    (t_min >= 20.0) as is_tropical_night,
    (t_min <= 0.0)  as is_frost_day
from {{ ref('stg_weather') }}
order by province_code, obs_date
