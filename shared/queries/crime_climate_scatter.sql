-- Both scatters in one query: the naive cross-section (raw) and the two-way
-- demeaned panel. The raw pair uses summer_tmax (absolute temperature), not
-- the anomaly, because the anomaly is already within-region and would erase
-- the cross-sectional confound this chart exists to show.
--
-- Parameters (positional): none
--
-- Returns: region_name, year, summer_tmax, ln_offenders, summer_anomaly_dm,
-- ln_offenders_dm
SELECT region_name, year,
       summer_tmax, ln_offenders,
       summer_anomaly_dm, ln_offenders_dm
FROM mart_crime_climate
WHERE summer_anomaly IS NOT NULL AND ln_offenders IS NOT NULL
ORDER BY region_name, year
