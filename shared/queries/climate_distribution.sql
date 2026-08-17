-- Daily max-temperature histogram, early window against late window.
--
-- Counts are normalized to percentages so the two curves are comparable in
-- height rather than reflecting how many days each window happens to hold.
-- climate_distribution_windows.sql now hands over near-equal windows, so this
-- guards against an odd year and a leap day instead of a 15-year difference in
-- span, but dropping it would still make one curve taller for purely
-- arithmetic reasons.
--
-- The two windows are adjacent and cover the whole record; see
-- climate_distribution_windows.sql, which is the only place the split lives.
--
-- Parameters (positional): the early/late year-window bounds repeat because
-- the same two windows are used in two different FILTER clauses (once to
-- size each window's denominator, once to size each bucket's numerator).
--   1. city     (VARCHAR) - capital_city to filter to
--   2. early_lo (INTEGER) - early window start year, denominator FILTER
--   3. early_hi (INTEGER) - early window end year, denominator FILTER
--   4. late_lo  (INTEGER) - late window start year, denominator FILTER
--   5. late_hi  (INTEGER) - late window end year, denominator FILTER
--   6. early_lo (INTEGER) - early window start year, numerator FILTER
--   7. early_hi (INTEGER) - early window end year, numerator FILTER
--   8. late_lo  (INTEGER) - late window start year, numerator FILTER
--   9. late_hi  (INTEGER) - late window end year, numerator FILTER
--
-- Returns: period (2-degree bucket), early (% of early-window days), late
-- (% of late-window days)
WITH d AS (
    SELECT CAST(year AS INTEGER) AS y,
           CAST(FLOOR(t_max / 2.0) * 2 AS INTEGER) AS bucket
    FROM mart_climate_daily
    WHERE capital_city = ? AND t_max IS NOT NULL
),
tot AS (
    SELECT
        COUNT(*) FILTER (WHERE y BETWEEN ? AND ?) AS n_early,
        COUNT(*) FILTER (WHERE y BETWEEN ? AND ?) AS n_late
    FROM d
)
SELECT d.bucket AS period,
       ROUND(100.0 * COUNT(*) FILTER (WHERE y BETWEEN ? AND ?)
             / NULLIF(ANY_VALUE(tot.n_early), 0), 3) AS early,
       ROUND(100.0 * COUNT(*) FILTER (WHERE y BETWEEN ? AND ?)
             / NULLIF(ANY_VALUE(tot.n_late), 0), 3) AS late
FROM d, tot
GROUP BY d.bucket
HAVING ANY_VALUE(tot.n_early) > 0 AND ANY_VALUE(tot.n_late) > 0
ORDER BY period
