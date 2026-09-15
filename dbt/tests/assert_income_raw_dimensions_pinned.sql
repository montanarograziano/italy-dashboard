-- Release-only source guard. Normalized snapshots discard SDMX dimensions, so
-- publishing must first prove the raw income slice the pipeline consumes
-- (B6G_B_W0 x S14) does not mix another industry breakdown, non-financial
-- asset split, valuation, price concept, adjustment, or measure unit.
-- Column headers verified against the real 93_1095 extract
-- ("DATA_TYPE_AGGR: Aggregate", unit attributes blank on some rows).
{% if env_var('REQUIRE_INCOME_RAW_DIMENSIONS', 'false') | lower == 'true' %}
with raw as (

    select *
    from read_csv_auto(
        '{{ env_var('ITALY_DATA_DIR', 'data') }}/raw/income_regional.csv',
        header = true,
        all_varchar = true
    )

),

selected as (

    select
        split_part("BRKDW_INDUSTRY_NACE_REV2: Breakdown by industry (NACE Rev.2)", ': ', 1) as industry,
        split_part("NONFIN_ASSETS: Non financial assets", ': ', 1) as nonfin_assets,
        split_part("VALUATION: Valuation", ': ', 1) as valuation,
        split_part("PRICE: Price", ': ', 1) as price,
        split_part("ADJUSTMENT: Adjustment", ': ', 1) as adjustment,
        coalesce(split_part("UNIT_MEAS: Measure unit", ': ', 1), '') as unit_meas,
        coalesce(split_part("UNIT_MULT: Multiplication unit", ': ', 1), '') as unit_mult
    from raw
    where split_part("DATA_TYPE_AGGR: Aggregate", ': ', 1) = 'B6G_B_W0'
      and split_part("INSTITUTIONAL_SECTOR: Institutional sector", ': ', 1) = 'S14'

),

violations as (

    select
        'unexpected raw income dimension: industry=' || industry
        || ' nonfin=' || nonfin_assets || ' valuation=' || valuation
        || ' price=' || price || ' adjustment=' || adjustment
        || ' unit=' || unit_meas || ' mult=' || unit_mult as error
    from selected
    where industry <> 'Z'
       or nonfin_assets <> 'Z'
       or valuation <> 'V'
       or price <> 'S'
       or adjustment <> 'N'
       -- Unit attributes are blank on some genuine rows; when present they
       -- must be euro at the millions multiplier.
       or (unit_meas <> '' and unit_meas <> 'EURO')
       or (unit_mult <> '' and unit_mult <> '6')
    limit 10

)

select error from violations
union all
select 'income raw slice B6G_B_W0 x S14 is empty' as error
where not exists (select 1 from selected)
{% else %}
select cast(null as varchar) as error
where false
{% endif %}
