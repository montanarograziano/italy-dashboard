-- Scatter points for the income-versus-offending view: one row per region for
-- a single year, per citizenship group.
--
-- Parameters (positional):
--   1. year (VARCHAR) - the year to slice, e.g. '2023'
--
-- Returns: code, region, income, rate
SELECT citizenship_code AS code, region_name AS region,
       income_per_capita AS income, rate_per_1000 AS rate
FROM mart_crime_income
WHERE year = ? AND income_per_capita IS NOT NULL AND rate_per_1000 IS NOT NULL
-- income is a REGIONAL figure (see mart_crime_income.sql), so it repeats
-- across every citizenship group within one region: `income` alone is not a
-- total order. (region, code) is the rest of this mart's grain for a fixed
-- year, so appending both makes the key unique per row.
ORDER BY income, region, code
