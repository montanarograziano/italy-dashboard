-- Italian capitals sit between sea level and ~1,000 m (Enna, 931 m), and no
-- ERA5-Land cell over Italy tops ~3,000 m (coastal cells dip slightly below 0). A value outside either range is a
-- wrong geocoder match or a cell sampled off the grid, and would shift that
-- city's whole temperature series by degrees through stg_weather.
select province_code, capital_city, elevation_m, cell_elevation_m
from {{ ref('province_capitals') }}
where elevation_m not between -5 and 1200
   or cell_elevation_m not between -50 and 3000
