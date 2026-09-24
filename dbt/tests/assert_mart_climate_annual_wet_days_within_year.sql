-- A capital cannot have more wet days (>= 1 mm) than days observed that year,
-- and a percent anomaly below -100 % would mean less than no rain. Either
-- points at a broken aggregation (a double-counted join, a wrong baseline).
select province_code, year, wet_days, days_observed,
       precip_anomaly_pct_1971_2000, precip_anomaly_pct_1981_2010
from {{ ref('mart_climate_annual') }}
where wet_days > days_observed
   or precip_anomaly_pct_1971_2000 < -100
   or precip_anomaly_pct_1981_2010 < -100
