-- Distinct years for which the income-versus-offending mart has both an
-- income figure and an offender rate, newest first.
--
-- Parameters (positional): none
--
-- Returns: year
SELECT DISTINCT year FROM mart_crime_income
WHERE income_per_capita IS NOT NULL AND rate_per_1000 IS NOT NULL
ORDER BY year DESC
