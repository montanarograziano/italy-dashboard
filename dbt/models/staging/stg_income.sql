-- Regional income per capita from the normalized snapshot. One value per
-- region-year (the registry filters pin the headline indicator; AVG guards
-- against accidental duplicate slices).

select
    territory as region_code,
    any_value(territory_name) as region_name,
    period as year,
    avg(value) as income_per_capita
from {{ source('snapshots', 'income_regional_pq') }}
where value is not null
group by territory, period
