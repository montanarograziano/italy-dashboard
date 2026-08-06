-- Population denominators by region and year, from the normalized snapshots
-- (both files already hold sex/age totals only, thanks to registry filters).
-- italian = resident total - foreign residents.

with resident as (
    select territory as region_code,
           any_value(territory_name) as region_name,
           period as year,
           sum(value) as pop_total
    from {{ source('snapshots', 'population_resident_pq') }}
    where value is not null
    group by territory, period
),

foreign_pop as (
    select territory as region_code,
           period as year,
           sum(value) as pop_foreign
    from {{ source('snapshots', 'population_foreign_pq') }}
    where value is not null
    group by territory, period
)

select
    coalesce(r.region_code, f.region_code)  as region_code,
    r.region_name                           as region_name,
    coalesce(r.year, f.year)                as year,
    r.pop_total                             as pop_total,
    f.pop_foreign                           as pop_foreign,
    case
        when r.pop_total is not null and f.pop_foreign is not null
        then r.pop_total - f.pop_foreign
    end                                     as pop_italian
from resident r
full outer join foreign_pop f
    on r.region_code = f.region_code and r.year = f.year
