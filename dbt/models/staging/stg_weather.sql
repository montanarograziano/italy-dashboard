-- Staging: daily temperatures joined to the province-capitals seed, one row
-- per (province, date). The join is an INNER join on purpose: a snapshot row
-- whose province code is not in the seed is a bug, not data to carry forward.
--
-- `year` is VARCHAR to match every ISTAT-derived mart, so joins need no cast.
--
-- Elevation correction: the snapshot holds raw ERA5-Land grid-cell values,
-- i.e. the temperature at the cell's mean orography, which around the Alps
-- sits over a kilometre above the city (Aosta: city 583 m, cell 1,795 m, so
-- the raw series reads ~7.9 C too cold and records no hot days at all). Every
-- value is shifted to the city's own height with the standard-atmosphere lapse
-- rate, the same downscaling Open-Meteo applies by default. It is a constant
-- offset per city: trends and anomalies are unchanged, absolute levels and
-- threshold counts (hot days, frost days, tropical nights) are what it fixes.
-- A constant lapse rate cannot model winter valley inversions, so alpine
-- valley minima can still be off by a degree or two.
{% set lapse_rate_c_per_m = 0.0065 %}

with raw as (
    select * from {{ source('snapshots', 'weather_daily_pq') }}
),

capitals as (
    select
        *,
        {{ lapse_rate_c_per_m }} * (cell_elevation_m - elevation_m) as lapse_offset
    from {{ ref('province_capitals') }}
)

select
    r.province_code,
    c.province_name,
    c.capital_city,
    c.region_code,
    c.region_name,
    cast(r.date as date)                       as obs_date,
    cast(year(cast(r.date as date)) as varchar) as year,
    month(cast(r.date as date))                as month,
    cast(r.t_min as double) + c.lapse_offset   as t_min,
    cast(r.t_mean as double) + c.lapse_offset  as t_mean,
    cast(r.t_max as double) + c.lapse_offset   as t_max
from raw r
join capitals c on r.province_code = c.province_code
where r.t_mean is not null
