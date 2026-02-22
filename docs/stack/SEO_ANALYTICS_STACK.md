# SEO_ANALYTICS_STACK.md — Indexing, ranking signals, and measurement

## Purpose
OpenClaw needs a measurement loop. Without measurement you cannot scale.

---

## Core Tools (Recommended)
### Google Search Console (GSC)
Why:
- impressions, clicks, queries, indexing issues
Programmatic:
- API available (requires setup)
Use case:
- track which pages gain visibility
- detect indexing issues

### Google Analytics (GA4)
Why:
- sessions, engagement, referrals
Programmatic:
- Measurement Protocol / APIs vary; start manual, automate later
Use case:
- understand behavior and conversions funnel-ish signals

### Affiliate dashboards
Why:
- real conversion + revenue
Programmatic:
- depends on network (some have APIs, some don't)
Use case:
- measure EPC, best offers, best pages

---

## Rank tracking (Optional early)
Tools exist, but can be costly. Instead:
- use GSC query data as your "real" ranking proxy
- supplement with lightweight SERP checks sparingly

---

## "Money Metrics"
Track at minimum:
- page impressions
- page clicks
- affiliate outbound clicks (if trackable)
- conversions / commission
- EPC (earnings per click) where possible

---

## Hardware notes
Analytics ingestion is light.
- Node B can run analytics agent
- Node A stores snapshots in DB
