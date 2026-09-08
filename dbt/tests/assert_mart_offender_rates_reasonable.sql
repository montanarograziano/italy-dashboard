-- Sanity gate for denominators and rates. 1,000 per 1,000 is a conservative
-- upper bound for annual per-crime alleged-offender rates.
select year, region_code, crime_code, citizenship_code,
       offenders, population, rate_per_1000
from {{ ref('mart_offender_rates') }}
where offenders < 0
   or (rate_per_1000 is not null and (rate_per_1000 < 0 or rate_per_1000 > 1000))
   or (rate_per_1000 is not null and (population is null or population <= 0))
   or (rate_per_1000 is not null and rate_per_1000 != round(1000.0 * offenders / population, 3))
