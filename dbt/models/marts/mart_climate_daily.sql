-- Daily climate mart: staging plus the three conventional Italian threshold
-- flags. These read far more plainly to non-specialists than anomalies do.
--
-- Definitions: hot day = daily max >= 30 C; tropical night = daily min >= 20 C;
-- frost day = daily min <= 0 C.
--
-- Precipitation: `precip_mm` is the ERA5-Land grid-cell total for the day
-- (reanalysis, not a rain gauge; see stg_weather), rounded to 0.01 mm, which
-- is far below what the reanalysis resolves and keeps the Parquet small.
-- wet day = precip_mm >= 1 mm, the standard ETCCDI threshold (R1mm), below
-- which reanalysis "drizzle" is mostly model noise. It is evaluated on the
-- UNROUNDED value, so the 0.01 mm rounding cannot move a day across it. Both
-- stay NULL on a day with no precipitation value: NULL is not "dry".

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
    (t_min <= 0.0)  as is_frost_day,
    round(precip_mm, 2) as precip_mm,
    (precip_mm >= 1.0)  as is_wet_day
from {{ ref('stg_weather') }}
order by province_code, obs_date
