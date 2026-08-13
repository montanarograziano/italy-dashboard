-- One row per province per year, or every chart double counts.
select province_code, year, count(*) as n
from {{ ref('mart_climate_annual') }}
group by province_code, year
having count(*) > 1
