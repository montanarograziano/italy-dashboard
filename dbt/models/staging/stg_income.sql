-- Household gross disposable income (B6G, sector S14) by region and year,
-- in MILLIONS of euro. The registry pins indicator and sector at normalize
-- time; the snapshot's `category` carries the EDITION code (e.g. "2025M12")
-- because the dataflow stacks several editions of the same years. Only the
-- latest edition per region × year survives here.
--
-- Edition codes sort as year*100 + month ("2025M12" > "2025M6", which plain
-- string ordering gets WRONG). Non-edition categories (e.g. sample data)
-- rank as 0 and pass through when they are the only slice.

with src as (

    select
        territory as region_code,
        territory_name as region_name,
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

select
    region_code,
    any_value(region_name) as region_name,
    year,
    avg(value) as income_mln
from latest
group by region_code, year
