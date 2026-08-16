-- Every region-level region_code in mart_offenders must exist in the
-- province_capitals seed's region_code vocabulary.
--
-- CATCHES: a NUTS-vocabulary mismatch between the offenders source and the
-- capitals seed (the original bug -- offenders on NUTS-2021 ITH3, the seed on
-- NUTS-2006 ITD3). ITH3 would not appear anywhere in the seed, so this test
-- fails regardless of how much weather data has been fetched, because the
-- seed is committed and complete: it lists all 21 regions today, backfill
-- state notwithstanding.
--
-- DOES NOT CATCH: a region missing from mart_crime_climate because its
-- weather backfill has not run yet. The seed only proves the region_code is
-- a *known* code; it says nothing about whether climate data exists for it.
-- That is assert_crime_climate_covers_available_climate.sql's job.
with offender_regions as (
    select distinct region_code
    from {{ ref('mart_offenders') }}
    where region_level = 'region'
),

seed_regions as (
    select distinct region_code
    from {{ ref('province_capitals') }}
)

select o.region_code
from offender_regions o
left join seed_regions s on o.region_code = s.region_code
where s.region_code is null
