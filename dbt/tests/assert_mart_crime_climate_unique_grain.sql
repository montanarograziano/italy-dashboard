-- One row per region per year: the panel's whole design assumes it.
select region_code, year, count(*) as n
from {{ ref('mart_crime_climate') }}
group by region_code, year
having count(*) > 1
