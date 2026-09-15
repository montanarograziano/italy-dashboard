-- Release-only completeness gate. Development fixtures intentionally contain
-- only a subset of violent codes; set REQUIRE_COMPLETE_VIOLENT_PANEL=true for
-- publishing so a partial six-code panel cannot pass as complete.
{% if env_var('REQUIRE_COMPLETE_VIOLENT_PANEL', 'false') | lower == 'true' %}
with expected as (
    select count(*) as n from {{ ref('violent_crime_codes') }}
),
region_years as (
    select region_code, year
    from {{ ref('mart_offenders') }}
    where region_level = 'region'
      and sex_is_total
      and age_is_total
      and not citizenship_is_total
      and not crime_is_total
    group by region_code, year
),
observed as (
    select o.region_code, o.year,
           count(distinct o.crime_code) as violent_codes
    from {{ ref('mart_offenders') }} o
    join {{ ref('violent_crime_codes') }} v on o.crime_code = v.crime_code
    where o.region_level = 'region'
      and o.sex_is_total
      and o.age_is_total
      and not o.citizenship_is_total
      and not o.crime_is_total
    group by o.region_code, o.year
)
select r.region_code, r.year,
       coalesce(o.violent_codes, 0) as violent_codes,
       e.n as expected_codes
from region_years r
cross join expected e
left join observed o using (region_code, year)
where coalesce(o.violent_codes, 0) <> e.n
{% else %}
select cast(null as varchar) as region_code
where false
{% endif %}
