# OPENCLAW_MASTER_EXECUTION_LOOP.md

OpenClaw Affiliate Automation System

Purpose: Defines the perpetual operational cycle OpenClaw follows.

This is the MASTER ALGORITHM governing all automation behavior.

All agents, schedulers, and pipelines must ultimately conform to this loop.

OpenClaw is not a content generator.
It is a continuous revenue optimization engine.

---

## The OpenClaw Brain Cycle

The system operates in repeating phases:

```
DISCOVER → VALIDATE → BUILD → LINK → OBSERVE → ADAPT → SCALE → REPEAT
```

No step is optional.

Skipping steps breaks long-term growth.

---

## PHASE 1 — DISCOVER (Topic Engine)

Goal: Find viable new buyer-intent topics.

Run:

- Topic discovery engine
- Question expansion
- Cluster identification

Output:

```
candidate_topic_clusters[]
```

Each cluster must include:

- main buyer guide
- support articles
- scenario pages

Reject:

- isolated topics
- non-purchasable niches
- non-expandable subjects

---

## PHASE 2 — VALIDATE (Competitor Scan)

For each candidate cluster:

Run:

- competitor weakness scanner
- SERP structure analysis
- monetization viability check

If:

```
SERP dominated by strong brands → Reject cluster.
```

If:

```
SERP contains thin/outdated/weak pages → Approve cluster.
```

Output:

```
validated_clusters[]
```

---

## PHASE 3 — BUILD (Content Creation)

For approved clusters:

OpenClaw must:

1. generate MAIN article first
2. generate top support pages next
3. follow ARTICLE_BLUEPRINT_TEMPLATE strictly

Never publish support pages before main guide.

Each article must pass:

- content quality filter
- structure validation
- internal link requirement

If failing: rewrite once, else store for review.

---

## PHASE 4 — LINK (Authority Wiring)

Immediately after publishing:

OpenClaw must:

- insert parent links
- insert sibling links
- insert child links
- update sitemap

No article is allowed to exist as an orphan.

Cluster connectivity must be established within the same execution cycle.

---

## PHASE 5 — OBSERVE (SEO Signal Tracking)

Daily:

OpenClaw must monitor:

- crawl activity
- indexing rate
- impression growth
- ranking movement
- affiliate click events

Signals must be stored historically.

Never judge performance based on one day.

**Trend direction is the only valid signal.**

---

## PHASE 6 — ADAPT (Refresh Engine)

OpenClaw must continuously evaluate:

- articles older than refresh threshold
- ranking plateaus
- low CTR pages
- outdated product references

When triggered:

Run refresh engine.

Refresh must:

- expand sections
- update product info
- add new internal links
- update timestamp

Never mass-rewrite entire site.

Selective maintenance only.

---

## PHASE 7 — SCALE (Growth Decisions)

OpenClaw must consult:

```
RUNBOOK_SCALE_TRIGGER.md
```

Only scale when:

- indexing stable
- impressions rising
- ranking movement visible

Scaling actions include:

- increase publishing frequency
- expand cluster depth
- deploy additional niche sites

**Never scale blindly.**

---

## PHASE 8 — HEALTH CHECK (System Stability)

Weekly:

Compute automation health score.

```
score >= 90  → Aggressive scaling allowed.
score 60–89  → Maintain steady growth.
score < 60   → Freeze expansion immediately.
```

---

## Daily Execution Order

OpenClaw must run in this order:

```
1 → check system health
2 → process refresh queue
3 → publish scheduled articles
4 → update internal links
5 → track SEO signals
6 → evaluate scale conditions
7 → update logs
```

Never publish before refresh checks.

**Maintenance always precedes expansion.**

---

## Failure Safety Rules

If any condition occurs:

- publishing errors spike
- indexing collapse detected
- queue overload detected
- affiliate tracking broken

System must:

```
switch to SAFE_MODE
pause publishing
continue monitoring
```

Never continue publishing during instability.

---

## OpenClaw Philosophy

OpenClaw is not designed to:

- publish as much as possible
- generate content endlessly
- chase trends

OpenClaw is designed to:

```
identify weak opportunities
deploy structured clusters
reinforce authority loops
maintain winning pages
scale only when signals confirm success
```

---

## Final Master Rule

Revenue is not created by content volume.

Revenue is created by:

```
correct topic selection
+ cluster authority
+ internal linking strength
+ continuous maintenance
+ controlled scaling
```

If the loop is followed correctly,

**growth becomes inevitable.**
