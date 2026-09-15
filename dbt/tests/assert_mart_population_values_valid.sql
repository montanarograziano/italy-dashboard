-- Population sanity: never negative, foreign residents cannot exceed the
-- resident total, and Italy/NUTS2 rows cannot be zero. A ZERO total at
-- municipality grain is genuine ISTAT output (abolished/merged comuni in
-- transition years, e.g. five 2023 rows in the real 22_289 extract), so
-- zero is rejected only where it is impossible. Rows with a missing
-- counterpart remain allowed because source refreshes land independently.
select region_code, year, pop_total, pop_foreign, pop_italian
from {{ ref('mart_population') }}
where (pop_total is not null and pop_total < 0)
   or (pop_foreign is not null and pop_foreign < 0)
   or (pop_total is not null and pop_total = 0
       and (region_code = 'IT' or regexp_matches(region_code, '^IT[A-Z][0-9]$')))
   or (pop_total is not null and pop_foreign is not null
       and pop_foreign > pop_total)
   or (pop_italian is not null and pop_italian < 0)
