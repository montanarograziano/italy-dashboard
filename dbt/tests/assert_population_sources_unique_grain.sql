-- Normalized population snapshots must contain one observation per territory-year.
-- Aggregating duplicates would hide a broken source filter and inflate totals.
with resident as (
    select 'resident' as dataset, territory, period, count(*) as n
    from {{ source('snapshots', 'population_resident_pq') }}
    where value is not null
    group by territory, period
    having count(*) > 1
),
foreign_pop as (
    select 'foreign' as dataset, territory, period, count(*) as n
    from {{ source('snapshots', 'population_foreign_pq') }}
    where value is not null
    group by territory, period
    having count(*) > 1
)
select * from resident
union all
select * from foreign_pop
