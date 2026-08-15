-- Every region-level territory in mart_offenders must survive into the panel.
--
-- The panel joins offenders to region-level summer temperature on region_code.
-- A code-vocabulary mismatch between the two sides (NUTS-2006 ITD3 against
-- NUTS-2021 ITH3, say) or a region with no province capital in the weather
-- seed drops regions silently: the panel simply gets smaller, no error, no
-- failing test. This makes that shrinkage fail the build.
with offender_regions as (
    select distinct region_code
    from {{ ref('mart_offenders') }}
    where region_level = 'region'
),

panel_regions as (
    select distinct region_code
    from {{ ref('mart_crime_climate') }}
)

select o.region_code
from offender_regions o
left join panel_regions p on o.region_code = p.region_code
where p.region_code is null
