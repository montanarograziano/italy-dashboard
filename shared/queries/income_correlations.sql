-- Pearson r between regional income and offender rate, per citizenship, for
-- a single year.
--
-- Parameters (positional):
--   1. year (VARCHAR) - the year to slice, e.g. '2023'
--
-- Returns: code, r (Pearson correlation), n (row count)
SELECT citizenship_code AS code,
       ROUND(corr(income_per_capita, rate_per_1000), 2) AS r,
       COUNT(*) AS n
FROM mart_crime_income
WHERE year = ? AND income_per_capita IS NOT NULL AND rate_per_1000 IS NOT NULL
GROUP BY citizenship_code
