-- mart_naspi is a reshaped copy of normalized INPS input. Compare both row
-- counts and totals so joins/filters cannot silently change beneficiaries.
with source_rows as (
    select territory, category, period,
           count(*) as source_rows,
           sum(value) as source_value
    from {{ source('snapshots', 'labor_naspi_beneficiaries_pq') }}
    where value is not null
    group by territory, category, period
),
mart_rows as (
    select territory, category, period,
           count(*) as mart_rows,
           sum(value) as mart_value
    from {{ ref('mart_naspi') }}
    where value is not null
    group by territory, category, period
)
select
    coalesce(s.territory, m.territory) as territory,
    coalesce(s.category, m.category) as category,
    coalesce(s.period, m.period) as period,
    s.source_rows,
    m.mart_rows,
    s.source_value,
    m.mart_value
from source_rows s
full outer join mart_rows m using (territory, category, period)
where s.territory is null
   or m.territory is null
   or s.source_rows <> m.mart_rows
   or abs(s.source_value - m.mart_value) > 0.000001
