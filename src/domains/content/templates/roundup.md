# {{ title }}

*Last updated: {{ last_updated }}*

{{ intro }}

---

## Our Top Picks at a Glance

{% for pick in top_picks %}
{{ loop.index }}. **[{{ pick.name }}]({{ pick.affiliate_link }})** - {{ pick.tagline }}
{% endfor %}

---

{% for product in products %}
## {{ loop.index }}. {{ product.name }}

{{ product.summary }}

### Key Features
{% for feature in product.features %}
- {{ feature }}
{% endfor %}

### Pros
{% for pro in product.pros %}
- {{ pro }}
{% endfor %}

### Cons
{% for con in product.cons %}
- {{ con }}
{% endfor %}

**Price:** {{ product.price }}
**Rating:** {{ product.rating }}/5
**Best For:** {{ product.best_for }}

[Check Latest Price]({{ product.affiliate_link }})

---

{% endfor %}

## How We Tested

{{ methodology }}

## Buying Guide: What to Look For

{% for factor in buying_factors %}
### {{ factor.name }}

{{ factor.description }}

{% endfor %}

## Frequently Asked Questions

{% for faq in faqs %}
### {{ faq.question }}

{{ faq.answer }}

{% endfor %}

## Final Thoughts

{{ conclusion }}

---

*{{ disclosure }}*
