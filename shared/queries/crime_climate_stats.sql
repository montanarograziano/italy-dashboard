-- Slope and Pearson r for both the raw and demeaned-panel views, plus n.
-- The raw pair is computed on summer_tmax, matching the raw scatter; the row
-- filter stays on summer_anomaly so both views describe the same rows and
-- share one n.
--
-- Parameters (positional): none
--
-- Returns: n, raw_slope, raw_r, dm_slope, dm_r
SELECT COUNT(*) AS n,
       ROUND(regr_slope(ln_offenders, summer_tmax), 4) AS raw_slope,
       ROUND(corr(ln_offenders, summer_tmax), 3) AS raw_r,
       ROUND(regr_slope(ln_offenders_dm, summer_anomaly_dm), 4) AS dm_slope,
       ROUND(corr(ln_offenders_dm, summer_anomaly_dm), 3) AS dm_r
FROM mart_crime_climate
WHERE summer_anomaly IS NOT NULL AND ln_offenders IS NOT NULL
