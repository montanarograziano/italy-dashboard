-- One row per region (including the national 'IT' row) per year, or every
-- chart double counts.
select region_code, year, count(*) as n
from {{ ref('mart_climate_region') }}
group by region_code, year
having count(*) > 1
