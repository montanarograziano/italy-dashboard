-- Every one of the 21 region-level units must have foreign residents in the
-- latest foreign-population year. ISTAT answers a key naming codes it does not
-- use (e.g. NUTS 2021 ITH*/ITI* instead of this flow's ITD*/ITE*) with a
-- smaller result and no error, which silently dropped nine regions' foreign
-- shares and per-citizenship offender rates once already.
--
-- Warns on every build; set REQUIRE_COMPLETE_FOREIGN_POPULATION=true when
-- sealing a release so a partial panel fails instead (synthetic fixtures
-- cover 12 regions by design, so the default cannot be an error).
{{ config(
    severity='error' if env_var('REQUIRE_COMPLETE_FOREIGN_POPULATION', 'false') | lower == 'true' else 'warn'
) }}
with regions as (
    select distinct region_code, region_name from {{ ref('province_capitals') }}
),

latest as (
    select max(year) as year from {{ ref('stg_population') }} where pop_foreign is not null
)

select r.region_code, r.region_name, l.year
from regions r
cross join latest l
left join {{ ref('stg_population') }} p
    on p.region_code = r.region_code and p.year = l.year and p.pop_foreign is not null
where p.region_code is null
