# Offer Scoring Playbook

## Scoring Algorithm

Each offer is scored on a 0-100 scale based on weighted factors:

### Factors

| Factor | Weight | Measurement |
|--------|--------|-------------|
| Commission Rate | 25% | % of sale or fixed amount |
| Average Order Value | 20% | Average purchase price |
| Cookie Duration | 15% | Days until cookie expires |
| Conversion Rate | 20% | Network-reported or estimated |
| Brand Recognition | 10% | Known brand vs unknown |
| Program Stability | 10% | How long has program existed |

### Score Calculation

```
score = (commission_score * 0.25) +
        (aov_score * 0.20) +
        (cookie_score * 0.15) +
        (conversion_score * 0.20) +
        (brand_score * 0.10) +
        (stability_score * 0.10)
```

### Tier Assignment

| Score Range | Tier | Action |
|-------------|------|--------|
| 80-100 | A | Prioritize - create dedicated content immediately |
| 60-79 | B | Include in roundups and comparisons |
| 40-59 | C | Monitor - include only if relevant |
| 0-39 | D | Skip - not worth content investment |

## Data Sources

- Affiliate network APIs (commission, cookie, conversion data)
- SERP analysis (competitor coverage of this offer)
- Historical performance data (our own click/conversion data)

## Re-scoring Schedule

- New offers: Score on ingestion
- Existing offers: Re-score weekly
- Tier changes: Alert if offer moves more than one tier
