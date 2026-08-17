-- 'IT' is reserved for the national row mart_climate_region adds on top of
-- the province-capitals aggregation. If a real region ever carried that code
-- upstream, the national aggregate would silently double count into it
-- instead of standing on its own.
select region_code
from {{ ref('mart_climate_daily') }}
where region_code = 'IT'
limit 1
