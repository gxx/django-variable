django-variable
===============

Allows use of template logic in a with-style template tag, for lazily saving the results of template logic that can be costly performance-wise.
Due to django template parsing {% %} must be replaced with {[ ]} inside variable logic.

Example usage:
```python
{% load variable %}
{% variable example="{[ if something ]}{{ somethingelse }}{[ else ]}{{ anotherthing }}{[ endif ]}" %}
  {% for item in items %}
    {{ example }}
  {% endfor %}
{% endvariable %}
```