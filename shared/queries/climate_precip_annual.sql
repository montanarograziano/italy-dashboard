-- Annual precipitation for one province capital: total, wet days, percent
-- anomaly against 1981-2010, and a 10-year centred rolling mean of the total.
--
-- ERA5-Land reanalysis grid-cell precipitation (see stg_weather), not
-- rain-gauge data. Totals are what the card plots, so the rules differ from
-- the temperature series in one respect only: an incomplete year is not
-- merely noisy but SHORT, which makes the partial-year filter below a
-- correctness guard rather than a cosmetic one (the running year would plot
-- as a record drought).
--
-- Rules, the same as queries._annual_windowed for temperature:
--   * Partial years are dropped (min_days, in practice
--     MIN_DAYS_FOR_A_FULL_YEAR from queries.py), and so are years with no
--     precipitation value at all (NULL is "no data", never a dry year).
--   * precip_rolling is the mean of the 4 years before, the year itself and
--     the 5 after, and NULL unless that window holds exactly 10 rows spanning
--     exactly 9 years. ROWS BETWEEN counts rows, not years, so the span check
--     is what stops it averaging across a hole left by a dropped year.
--
-- Parameters (positional):
--   1. city     (VARCHAR) - capital_city to filter to
--   2. min_days (INTEGER) - days a year needs before it counts as complete
--
-- Returns: period (year), precip_mm (annual total), wet_days (days >= 1 mm),
-- anomaly_pct (percent vs the 1981-2010 normal, NULL where the normal is not
-- covered), precip_rolling (mm), ordered by year.
WITH base AS (
    SELECT year AS period, precip_mm, wet_days,
           precip_anomaly_pct_1981_2010 AS anomaly_pct
    FROM mart_climate_annual
    WHERE capital_city = ? AND days_observed >= ? AND precip_mm IS NOT NULL
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
