-- Annual precipitation for one region, or for Italia: climate_precip_annual's
-- region/Italia counterpart, with the same output shape and the same rules
-- (see that file's header).
--
-- 'IT'/'Italia' is just another region_name in mart_climate_region, so one
-- equality filter serves a real region and the national scope alike. Values
-- there are UNWEIGHTED means of the member capitals' annual totals.
--
-- mart_climate_region carries no days_observed of its own, so completeness
-- comes from mart_climate_annual: the MINIMUM days_observed across the
-- region's capitals (across ALL capitals for 'IT'), so one still-partial
-- capital marks the year partial instead of being diluted away. This is
-- queries._region_completeness_cte, inlined because shared SQL is static.
--
-- Parameters (positional):
--   1. region   (VARCHAR) - region_name to filter to ('Italia' for national)
--   2. min_days (INTEGER) - days a year needs before it counts as complete
--
-- Returns: period (year), precip_mm (mean annual total across capitals),
-- wet_days (mean wet-day count), anomaly_pct (percent vs the scope's own
-- 1981-2010 normal), precip_rolling (mm), ordered by year.
WITH days AS (
    SELECT region_code, year, MIN(days_observed) AS days_observed
    FROM mart_climate_annual GROUP BY region_code, year
    UNION ALL
    SELECT 'IT' AS region_code, year, MIN(days_observed) AS days_observed
    FROM mart_climate_annual GROUP BY year
),
base AS (
    SELECT r.year AS period, r.precip_mm, r.wet_days,
           r.precip_anomaly_pct_1981_2010 AS anomaly_pct
    FROM mart_climate_region r
    JOIN days d ON d.region_code = r.region_code AND d.year = r.year
    WHERE r.region_name = ? AND d.days_observed >= ? AND r.precip_mm IS NOT NULL
),
windowed AS (
    SELECT *,
        COUNT(*) OVER w AS n,
        MAX(CAST(period AS INTEGER)) OVER w
            - MIN(CAST(period AS INTEGER)) OVER w AS span,
        AVG(precip_mm) OVER w AS rolling
    FROM base
    WINDOW w AS (
        ORDER BY CAST(period AS INTEGER)
        ROWS BETWEEN 4 PRECEDING AND 5 FOLLOWING
    )
)
SELECT period, precip_mm, wet_days, anomaly_pct,
       CASE WHEN n = 10 AND span = 9 THEN ROUND(rolling, 1) END AS precip_rolling
FROM windowed
ORDER BY CAST(period AS INTEGER)
