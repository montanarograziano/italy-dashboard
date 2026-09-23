{{ config(
    materialized='external',
    location=env_var('ITALY_DATA_DIR', 'data') ~ '/marts/mart_population.parquet',
    format='parquet',
) }}

-- One table, several geographic grains (ISTAT publishes them side by side):
-- any sum over region_code must filter territory_level first, or it counts
-- Italy several times over (~343M residents a year). 'region' is the project's
-- 21 NUTS2 units, where Bolzano (ITD1) and Trento (ITD2) stand in for
-- Trentino-Alto Adige; the combined ITDA row is 'region_group' so region
-- totals do not count it twice. Macro areas overlap too (Nord = ITC + ITD).
select
    *,
    case
        when region_code = 'IT' then 'national'
        when regexp_full_match(region_code, 'IT[A-Z]') or region_code in ('ITCD', 'ITFG')
            then 'macro_area'
        when region_code = 'ITDA' then 'region_group'
        when regexp_full_match(region_code, 'IT[A-Z][0-9]') then 'region'
        when regexp_full_match(region_code, 'IT[A-Z][0-9][0-9A-Z]|IT1[0-9]{2}')
            then 'province'
        when regexp_full_match(region_code, '[0-9]{6}') then 'municipality'
    end as territory_level
from {{ ref('stg_population') }}
