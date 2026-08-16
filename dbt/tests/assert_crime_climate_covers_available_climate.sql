-- Every region that has BOTH offender data AND climate data must appear in
-- the mart_crime_climate panel.
--
-- CATCHES: a join break between mart_offenders and mart_climate_daily that
-- drops a region even though both sides genuinely have data for it -- e.g. a
-- wrong join column, a stray filter, a whitespace/casing divergence in
-- region_code that the vocabulary test above would not necessarily surface
-- (that test only checks offender codes against the seed, not against
-- climate coverage).
--
-- DOES NOT CATCH, AND MUST NOT CATCH: a region with offenders but no climate
-- data yet. The weather backfill is incomplete by design during rollout, and
-- mart_crime_climate additionally requires 25 of 30 baseline years before it
-- will emit a summer_anomaly, so a region can have some raw weather rows and
-- still legitimately have zero panel rows. Both are expected operational
-- states, not bugs -- do not tighten this to "climate data" meaning "enough
-- climate data for a baseline," or every partial backfill will fail the
-- build again.
with offender_regions as (
    select distinct region_code
    from {{ ref('mart_offenders') }}
    where region_level = 'region'
),

climate_regions as (
    select distinct region_code
    from {{ ref('mart_climate_daily') }}
),

covered_regions as (
    select region_code from offender_regions
    intersect
    select region_code from climate_regions
),

panel_regions as (
    select distinct region_code
    from {{ ref('mart_crime_climate') }}
)

select c.region_code
from covered_regions c
left join panel_regions p on c.region_code = p.region_code
where p.region_code is null
