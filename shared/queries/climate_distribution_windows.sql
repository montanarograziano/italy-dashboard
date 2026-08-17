-- Distribution-chart windows: one city's record split in half.
--
-- The distribution card contrasts two year windows. They are DERIVED here
-- rather than written down as constants, for two reasons: a literal end year
-- silently lags the data by a year every January with no test to catch it, and
-- both frontends must agree on the split, which they only do if it is computed
-- in one place.
--
-- Rules:
--   * Every complete year lands in exactly one window: no gap between them,
--     no overlap. A gap reads to a viewer as missing data, and an unequal
--     split (say 38 years against 45) makes the longer window a blend of two
--     climate states, which widens the late curve instead of translating it —
--     the shift the card exists to show.
--   * Partial years are excluded from the BOUNDS (min_days, in practice
--     MIN_DAYS_FOR_A_FULL_YEAR from queries.py). A year contributing only its
--     summer would skew its window warm. Note this shapes the bounds only:
--     climate_distribution.sql then counts every day inside them, so a
--     partial year in the MIDDLE of a record would still contribute. With
--     ERA5-Land the only partial year is the running one, at the late edge,
--     which these bounds exclude.
--   * The split is the first year of the second half (`rn * 2 > n`). With an
--     odd number of years the extra one goes to the late window. Written as a
--     multiplication rather than a division so it stays integer arithmetic and
--     cannot land on the first year, which would leave an empty early window.
--
-- Parameters (positional):
--   1. city     (VARCHAR) - capital_city to filter to
--   2. min_days (INTEGER) - days a year needs before it counts as complete
--
-- Returns exactly ONE row: early_lo, early_hi, late_lo, late_hi. Returns ZERO
-- rows when the city has fewer than two complete years, which the caller must
-- handle: there is no honest two-window comparison to draw, and inventing a
-- window would plot a confident-looking contrast of nothing.
WITH complete_years AS (
    SELECT CAST(year AS INTEGER) AS y
    FROM mart_climate_daily
    WHERE capital_city = ? AND t_max IS NOT NULL
    GROUP BY year
    HAVING COUNT(*) >= ?
),
ranked AS (
    SELECT y,
           ROW_NUMBER() OVER (ORDER BY y) AS rn,
           COUNT(*)     OVER ()           AS n
    FROM complete_years
)
-- early_hi is late_lo - 1, not the last year actually present below the split,
-- so the two windows stay adjacent even if the record has a hole in it.
SELECT MIN(y)                               AS early_lo,
       MIN(y) FILTER (WHERE rn * 2 > n) - 1 AS early_hi,
       MIN(y) FILTER (WHERE rn * 2 > n)     AS late_lo,
       MAX(y)                               AS late_hi
FROM ranked
HAVING COUNT(*) >= 2
