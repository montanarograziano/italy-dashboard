-- Annual inflation (%): average of ISTAT's monthly year-over-year changes.
--
-- The snapshot holds MEASURE 7 of the all-bases NIC dataflow, ISTAT's own
-- "percentage change on the same period of the previous year". Unlike raw
-- index levels, this series is continuous across index rebasings, so no
-- base chaining is needed. The last point may average a partial year.
--
-- Parameters (positional): none
--
-- Returns: period (year, VARCHAR), value (annual average % change)
SELECT substr(period, 1, 4) AS period, ROUND(AVG(value), 1) AS value
FROM economy_inflation
WHERE territory = 'IT'
GROUP BY 1
ORDER BY 1
