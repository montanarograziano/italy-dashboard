-- Mean monthly year-over-year change (%), complete calendar years only.
--
-- The snapshot holds MEASURE 7 of the all-bases NIC dataflow, ISTAT's own
-- "percentage change on the same period of the previous year". This is a
-- descriptive mean of monthly YoY changes, not annual-average-index change.
-- Requiring 12 observed months excludes a partial endpoint year rather than
-- presenting YTD data as an annual result.
--
-- Parameters (positional): none
--
-- Returns: period (year, VARCHAR), value (mean monthly YoY % change)
SELECT substr(period, 1, 4) AS period, ROUND(AVG(value), 1) AS value
FROM economy_inflation
WHERE territory = 'IT' AND value IS NOT NULL
GROUP BY 1
HAVING COUNT(DISTINCT substr(period, 6, 2)) = 12
ORDER BY 1
