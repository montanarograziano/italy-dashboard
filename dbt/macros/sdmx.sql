-- ISTAT SDMX-CSV (labels=both) packs "CODE: Label" into single cells.
-- These macros split them; a plain value passes through unchanged.

{% macro sdmx_code(col) %}
    case
        when strpos({{ col }}, ': ') > 0 then substr({{ col }}, 1, strpos({{ col }}, ': ') - 1)
        else {{ col }}
    end
{% endmacro %}

{% macro sdmx_label(col) %}
    case
        when strpos({{ col }}, ': ') > 0 then substr({{ col }}, strpos({{ col }}, ': ') + 2)
        else {{ col }}
    end
{% endmacro %}

-- Administrative level of a NUTS-style territory code, verified against the
-- real ISTAT codes: IT = country; IT + letter + digit = the 21 region-level
-- units (19 regions + Trento/Bolzano autonomous provinces); IT + letters
-- only = macro-area aggregates (ITC Nord-ovest, ITDA Trentino-Alto Adige,
-- ...) which duplicate the regions and must never be listed or summed with
-- them; everything longer (ITC11, ITC4A, IT108...) is a province.
{% macro territory_level(col) %}
    case
        when upper({{ col }}) in ('IT', 'ITTOT') then 'country'
        when regexp_matches({{ col }}, '^IT[A-Z][0-9]$') then 'region'
        when regexp_matches({{ col }}, '^IT[A-Z]+$') then 'area'
        else 'province'
    end
{% endmacro %}
