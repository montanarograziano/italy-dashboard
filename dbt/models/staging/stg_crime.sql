-- Staging: one clean row per (year, region, offence, sex, age) for the
-- headline slice of dataflow 73_58. Column names are the exact combined
-- headers ISTAT ships; codes/labels are split via the sdmx_* macros.
--
-- Dimensions kept OPEN (they become mart dimensions): REF_AREA, TYPE_OFFENCE,
-- SEX, AGE_CRIME_COMMITTED. Every other breakdown is pinned to its
-- all-items/total code so sums never double count.

with raw as (
    select * from {{ source('raw', 'crime_raw') }}
)

select
    {{ sdmx_code('"TIME_PERIOD: Time"') }}                          as year,
    {{ sdmx_code('"REF_AREA: Territory"') }}                        as region_code,
    {{ sdmx_label('"REF_AREA: Territory"') }}                       as region_name,
    {{ sdmx_code('"TYPE_OFFENCE: Type of offence"') }}              as offence_code,
    {{ sdmx_label('"TYPE_OFFENCE: Type of offence"') }}             as offence_name,
    {{ sdmx_code('"SEX: Sex"') }}                                   as sex_code,
    {{ sdmx_label('"SEX: Sex"') }}                                  as sex_name,
    {{ sdmx_code('"AGE_CRIME_COMMITTED: Age when the crime was committed"') }}  as age_code,
    {{ sdmx_label('"AGE_CRIME_COMMITTED: Age when the crime was committed"') }} as age_name,
    try_cast("OBS_VALUE" as double)                                 as value
from raw
where try_cast("OBS_VALUE" as double) is not null
  and {{ sdmx_code('"FREQ: Frequency"') }} = 'A'
  and {{ sdmx_code('"DATA_TYPE: Indicator"') }} = 'FELONYFJ'
  and {{ sdmx_code('"NATURE_CRIME: Nature of the crime"') }} in ('ALL', 'TOTAL')
  and {{ sdmx_code('"JUDICIAL_OFFICE: Judicial office"') }} in ('ALL', 'TOTAL')
  and {{ sdmx_code('"TIME_CRIME_SENTENCE: Time interval between the committed crime date and the sentence date"') }} in ('TOTAL', 'ALL')
  and {{ sdmx_code('"PRINCIPAL_SECURITY_MEASURES: Principal security measures"') }} in ('ALL', 'TOTAL')
  and {{ sdmx_code('"PREVIOUS_CONVICTIONS_RELAPSE: Previous convictions and relapse"') }} in ('ALL', 'TOTAL')
  and {{ sdmx_code('"DISTRICT_COURT_APPEAL: District Court of Appeal"') }} in ('99', 'ALL', 'TOTAL')
  and {{ sdmx_code('"YEAR_CRIME: Year when the crime was committed"') }} in ('ALL', 'TOTAL')
  and {{ sdmx_code('"AGE_SERIOUS_CRIMECOMMIT: Age when the most serious crime was committed"') }} in ('TOTAL', 'ALL')
