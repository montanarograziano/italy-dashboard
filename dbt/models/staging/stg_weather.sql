-- Staging: daily temperatures joined to the province-capitals seed, one row
-- per (province, date). The join is an INNER join on purpose: a snapshot row
-- whose province code is not in the seed is a bug, not data to carry forward.
--
-- `year` is VARCHAR to match every ISTAT-derived mart, so joins need no cast.

with raw as (
    select * from {{ source('snapshots', 'weather_daily_pq') }}
),

capitals as (
    select * from {{ ref('province_capitals') }}
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
    cast(r.t_min as double)                    as t_min,
    cast(r.t_mean as double)                   as t_mean,
    cast(r.t_max as double)                    as t_max
from raw r
join capitals c on r.province_code = c.province_code
where r.t_mean is not null
