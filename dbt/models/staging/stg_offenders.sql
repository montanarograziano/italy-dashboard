-- Staging: alleged offenders reported by the police (73_230 family), one row
-- per (year, region, indicator, crime, sex, age, citizenship).
-- COUNTRY_CITIZEN is pinned to its total: country detail lives in the _2
-- dataflow and would double count here.

with raw as (
    select * from {{ source('raw', 'offenders_raw') }}
)

select
    {{ sdmx_code('"TIME_PERIOD: Time"') }}                   as year,
    {{ sdmx_code('"REF_AREA: Territory"') }}                 as region_code,
    {{ sdmx_label('"REF_AREA: Territory"') }}                as region_name,
    {{ sdmx_code('"DATA_TYPE: Indicator"') }}                as indicator_code,
    {{ sdmx_label('"DATA_TYPE: Indicator"') }}               as indicator_name,
    {{ sdmx_code('"TYPE_CRIME: Type of crime"') }}           as crime_code,
    {{ sdmx_label('"TYPE_CRIME: Type of crime"') }}          as crime_name,
    {{ sdmx_code('"SEX: Sex"') }}                            as sex_code,
    {{ sdmx_label('"SEX: Sex"') }}                           as sex_name,
    {{ sdmx_code('"AGE: Age"') }}                            as age_code,
    {{ sdmx_label('"AGE: Age"') }}                           as age_name,
    {{ sdmx_code('"CITIZENSHIP: Citizenship"') }}            as citizenship_code,
    {{ sdmx_label('"CITIZENSHIP: Citizenship"') }}           as citizenship_name,
    try_cast("OBS_VALUE" as double)                          as value
from raw
where try_cast("OBS_VALUE" as double) is not null
  and {{ sdmx_code('"FREQ: Frequency"') }} = 'A'
  and upper({{ sdmx_code('"COUNTRY_CITIZEN: Country of citizenship"') }})
      in ('TOTAL', '_T', 'ALL', 'WORLD', '999')
