-- USTAT/MUR DSU university scholarship interventions. The raw USTAT CSV uses
-- ISTAT numeric region codes (01..20); sample data already uses NUTS-like
-- codes. Normalize both to a region-code shape the dashboard can filter.

with raw as (
    select * from {{ source('snapshots', 'education_university_scholarships_pq') }}
)

select
    case trim(territory)
        when '01' then 'ITC1'
        when '02' then 'ITC2'
        when '03' then 'ITC4'
        when '04' then 'ITH1'
        when '05' then 'ITD3'
        when '06' then 'ITD4'
        when '07' then 'ITC3'
        when '08' then 'ITD5'
        when '09' then 'ITE1'
        when '10' then 'ITE2'
        when '11' then 'ITE3'
        when '12' then 'ITE4'
        when '13' then 'ITF1'
        when '14' then 'ITF2'
        when '15' then 'ITF3'
        when '16' then 'ITF4'
        when '17' then 'ITF5'
        when '18' then 'ITF6'
        when '19' then 'ITG1'
        when '20' then 'ITG2'
        else trim(territory)
    end as territory,
    trim(territory_name) as territory_name,
    trim(category) as category,
    trim(category_name) as category_name,
    trim(period) as academic_year,
    coalesce(nullif(regexp_extract(trim(period), '[0-9]{4}'), ''), trim(period)) as period,
    cast(value as double) as value
from raw
where value is not null
