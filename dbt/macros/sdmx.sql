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
