# STACK_OVERVIEW.md — OpenClaw Affiliate Bot (Friend Group)

## Goal
Define the full tech/software stack required to run OpenClaw as a compliant, scalable, automated affiliate content system:
- research → content → publish → index → rank → click → convert → optimize → scale

This document is ONLY for the friend group OpenClaw affiliate automation bot.

---

## Hardware Context (Current)
Cluster:
- 2× Mac minis (Node A, Node B)
- 2× SSD docking stations (external storage)
- Netgear 16-port PoE gigabit switch
- CyberPower CP1500AVRLCD3 UPS
- Spectrum router + dedicated 1Gbps internet (cluster-only)

---

## Execution Philosophy
We build this system in 3 operating tiers:

### Tier 1 — Local Dev (Laptop or single Mac mini)
- DRY_RUN only
- SQLite DB
- in-process queue

### Tier 2 — Cluster MVP (2 Mac minis)
- Docker Compose cluster
- SQLite on shared/replicated volume OR Postgres (recommended once stable)
- optional Redis for queue reliability

### Tier 3 — Production-Grade
- Postgres + Redis
- real monitoring/alerting
- backups + restore drills

---

## Stack Categories (What we need)
1) Runtime & Orchestration
2) Data & State
3) Content Generation (LLMs)
4) Publishing Layer (WordPress + plugins)
5) SEO / Indexing / Analytics
6) Observability & Alerts
7) Security & Secrets
8) Domains/DNS/CDN (optional but useful)
9) Backups & Storage
10) Payments/Affiliate Networks (accounts)

---

## Default Recommendation (Fastest to ship)
- WordPress (managed host) + REST API publishing
- Rank Math or Yoast SEO plugin
- Cloudflare DNS (optional)
- Google Search Console + GA4
- Postgres + Redis once cluster is stable
- OpenClaw runs in Docker on both Mac minis

---

## Node Role Mapping (Suggested)
### Node A (oc-core-01)
Runs:
- orchestrator + scheduler
- DB (initially)
- monitoring and backups
- light workers

### Node B (oc-work-01)
Runs:
- heavy workers (content generation batches)
- publishing worker (gated)
- analytics worker

Both nodes should be able to run a worker role in failover.

---

## "Must Have" vs "Nice Later"
### Must Have (v1)
- Python runtime + CLI
- Docker + compose
- WordPress site (staging at least)
- Basic SEO plugin + sitemap
- Logging + backups
- DRY_RUN and SAFE_STAGING modes

### Nice Later (v2+)
- Redis queue
- Postgres DB
- Monitoring dashboard + alerting
- Cloudflare caching rules
- automated internal link graph optimization
