import { runSql } from "../db";

// Matches italy_dashboard.queries.dsu_ranking: latest USTAT/MUR DSU
// scholarships granted (category 3), summed by region.
export async function dsuRanking(limit = 20) {
  return runSql(
    `WITH latest AS (
       SELECT max(period) AS period
       FROM mart_dsu
       WHERE category = '3' AND value IS NOT NULL
     )
     SELECT territory_name AS name, ROUND(SUM(value), 0) AS value
     FROM mart_dsu, latest
     WHERE category = '3'
       AND value IS NOT NULL
       AND mart_dsu.period = latest.period
     GROUP BY territory_name
     ORDER BY value DESC
     LIMIT ?`,
    [limit],
  );
}
