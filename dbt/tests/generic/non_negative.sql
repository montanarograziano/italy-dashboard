-- Fails on any row whose column is negative. NULL passes: "unknown" is a
-- separate question, answered (or deliberately not) by not_null.
{% test non_negative(model, column_name) %}
select {{ column_name }}
from {{ model }}
where {{ column_name }} < 0
{% endtest %}
