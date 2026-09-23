-- Precipitation normals and anomalies, shared by mart_climate_annual (per
-- capital) and mart_climate_region (per region and for the national row) so
-- the three scopes cannot drift apart. Both expect a per-year relation with
-- `year` (VARCHAR), `precip_mm` (annual total) and `days_observed`.

-- Mean annual total over the [lo, hi] window, from COMPLETE years only
-- (days_observed >= full_year, with a non-NULL total), and NULL unless at
-- least 25 of the window's 30 years qualify: the same 25-of-30 guard as the
-- temperature normals, applied to complete years because a short year's
-- total is short, not merely noisy. Use inside a GROUP BY aggregate.
{% macro precip_baseline(lo, hi, full_year) %}
    case when count(*) filter (
             where cast(year as integer) between {{ lo }} and {{ hi }}
               and days_observed >= {{ full_year }}
               and precip_mm is not null
         ) >= 25
         then avg(precip_mm) filter (
             where cast(year as integer) between {{ lo }} and {{ hi }}
               and days_observed >= {{ full_year }}
         )
    end
{% endmacro %}

-- Percent departure of a year's total from `base`, rounded to 0.1 %. NULL for
-- an incomplete year (its total is short by construction, and would read as
-- a drought), for a missing total, and for a missing or zero normal.
{% macro precip_anomaly_pct(alias, base, full_year) %}
    case when {{ alias }}.days_observed >= {{ full_year }} and {{ base }} > 0
         then round(100.0 * ({{ alias }}.precip_mm - {{ base }}) / {{ base }}, 1)
    end
{% endmacro %}
