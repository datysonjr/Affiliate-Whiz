# RUNBOOK_AUTOMATION_HEALTH_SCORING.md

OpenClaw Affiliate Automation System

Purpose: Defines a single composite health score that determines whether the automation system is succeeding or failing.

This prevents emotional decisions based on isolated metrics.

---

## Why This Exists

Looking at:

- traffic alone
- revenue alone
- article count alone

is misleading.

We combine signals into one health score.

---

## Health Score Components

Each category scored 0–20.

### Indexing Health (0–20)

Check:

- % of pages indexed
- crawl frequency

Healthy:

```
>80% pages indexed → full score
```

### Impression Growth (0–20)

Check:

- impressions increasing weekly?

Flat or declining → low score.

### Ranking Movement (0–20)

Check:

- pages moving toward top 20?

Movement matters more than position.

### Affiliate Engagement (0–20)

Check:

- affiliate clicks recorded?
- session time strong?

No clicks → low score.

### System Stability (0–20)

Check:

- scheduler running reliably?
- publish failures minimal?
- queue processing normal?

---

## Total Score

```
TOTAL = sum of all components
MAX   = 100
```

---

## Score Interpretation

```
90–100 = aggressive scale allowed
75–89  = healthy growth
60–74  = caution zone
40–59  = investigate issues
0–39   = freeze automation immediately
```

---

## Weekly Health Review

Every week:

- calculate health score
- log score in tracking file
- compare vs last week

Never scale if:

```
score decreasing
```

---

## Final Rule

Automation success is measured by trend direction,

**not by any single number.**
