-- Latest publication edition must resolve to exactly one value per region-year.
-- More than one row means normalized input retained a hidden source dimension.
with src as (
    select
        territory as region_code,
        period as year,
        value,
        coalesce(
            try_cast(split_part(category, 'M', 1) as int) * 100
                + try_cast(split_part(category, 'M', 2) as int),
            0
        ) as edition_key
    from {{ source('snapshots', 'income_regional_pq') }}
    where value is not null
),
latest as (
    select *
    from src
    qualify dense_rank() over (
        partition by region_code, year order by edition_key desc
    ) = 1
)
select region_code, year, count(*) as n
from latest
group by region_code, year
having count(*) <> 1
