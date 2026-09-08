-- stg_income must expose latest edition values, not an older publication or
-- an average across editions.
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
expected as (
    select region_code, year, value
    from src
    qualify row_number() over (
        partition by region_code, year order by edition_key desc
    ) = 1
),
actual as (
    select region_code, year, income_mln
    from {{ ref('stg_income') }}
)
select
    coalesce(e.region_code, a.region_code) as region_code,
    coalesce(e.year, a.year) as year,
    e.value as expected_value,
    a.income_mln as actual_value
from expected e
full outer join actual a using (region_code, year)
where e.region_code is null
   or a.region_code is null
   or abs(e.value - a.income_mln) > 0.000001
