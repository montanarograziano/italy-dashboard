-- One row per province per day, or every regional mean is weighted wrong.
--
-- The fetch splits each city into decade chunks. An overlap of a single day
-- between two chunks would duplicate that day, double that province's weight
-- inside every regional mean, and change no chart visibly. This makes it fail
-- the build instead.
select province_code, obs_date, count(*) as n
from {{ ref('stg_weather') }}
group by province_code, obs_date
having count(*) > 1
