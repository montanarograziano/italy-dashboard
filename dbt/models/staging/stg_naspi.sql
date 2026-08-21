-- NASPI beneficiaries (INPS), normalized to the same territory/category
-- shape every other snapshot already uses, so queries.py's generic
-- region-picker helpers (_region_filter, region_names) work unchanged
-- against this view. Two things the raw snapshot cannot provide itself
-- (INPS's CSV has no embedded labels, unlike ISTAT's labels=both):
--
--   * territory_name: joined from the existing province_capitals seed's
--     region_code/region_name (already used by stg_weather; independently
--     verified to match INPS's own PartialCodelists response for these
--     exact NUTS2 codes). LEFT JOIN, not INNER: an INPS region code this
--     seed doesn't recognize should degrade to showing its raw code, not
--     silently vanish from national totals.
--   * category_name: SESSO has only two codes, confirmed live against
--     INPS's PartialCodelists (1=Maschi, 2=Femmine, no total code) --
--     stable enough to decode inline rather than round-trip the hub again
--     at every dbt run.

with raw as (
    select * from {{ source('snapshots', 'labor_naspi_beneficiaries_pq') }}
),

regions as (
    select distinct region_code, region_name from {{ ref('province_capitals') }}
)

select
    raw.territory,
    coalesce(r.region_name, raw.territory) as territory_name,
    raw.category,
    case raw.category
        when '1' then 'Maschi'
        when '2' then 'Femmine'
        else raw.category
    end as category_name,
    raw.period,
    raw.value
from raw
left join regions r on raw.territory = r.region_code
