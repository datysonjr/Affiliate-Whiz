# OPENCLAW_FULL_AUTOMATION_ARCHITECTURE_MAP.md
OpenClaw Affiliate Automation (Friend Group)

Purpose: A single master map of the OpenClaw automation system:
- all subsystems
- all agents
- data flows
- schedules
- safety gates
- money loop

This is the "brain wiring diagram".

---

# 0) One-Sentence Summary

OpenClaw is a closed-loop system that:
**detects opportunities → publishes structured money content → builds internal authority → tracks signals → refreshes winners → scales sites**.

---

# 1) Money Loop Diagram (End-to-End)

```txt
   Trend Signals / Query Discovery
               |
               v
     Keyword + SERP Gap Scoring
               |
               v
   Topic Queue (Prioritized Backlog)
               |
               v
   Outline + Data Assembly + Proofing
               |
               v
   Article Generation (TLDR + Table + FAQ)
               |
               v
   Content Quality Filter (Reject/Approve)
               |
               v
   Publish to CMS + Sitemap + Index Pings
               |
               v
   Rankings + AI Citations + Clicks
               |
               v
   Affiliate Click → Conversion → Revenue
               |
               v
   Reinvest Budget (content/links/tools/hosting)
               |
               v
   Refresh Winners + Expand Clusters
               |
               v
     Scale Trigger → Add Pages/Sites
               |
               └────────────── back to Discovery
```

---

# 2) System Components (What Exists)

---

## 2.1 Core Engines (Subsystems)

1. Topic Discovery Engine
2. Competitor Weakness Scanner
3. Keyword Targeting Framework
4. Content & Site Engine (templates + CMS publishing)
5. Internal Linking Engine
6. AI Domination Protocol (extractable blocks)
7. SEO Signal Tracking Engine (GSC/BWT/rank)
8. Article Refresh Engine
9. Authority Snowball Model (10 pages → 500)
10. Portfolio Scaling System (scale triggers + saturation detector)
11. Budget Guardrails System
12. Kill Switch + Safe Mode System

---

# 3) Agent Architecture (Brain + Arms)

---

## 3.1 Brain Agents (Decision Makers)

* Master Scheduler Agent (orchestrator)
* Strategy/Scoring Agent (prioritizes what matters)
* Budget Guard Agent (prevents runaway spend)
* Safe Mode/Kill Switch Agent (stops catastrophe)

---

## 3.2 Arms Agents (Workers)

* Research Agent (facts, entities, offers)
* Competitor Scanner Agent (SERP gaps + weakness scoring)
* Content Generation Agent (articles + blocks)
* Internal Linking Agent (graph + insertion)
* Publishing Agent (CMS + metadata + schema)
* Analytics Agent (CTR, EPC, conversions)
* SEO Signal Agent (rankings, impressions, citations)
* Refresh Agent (updates winners)
* Health Monitor Agent (cluster + services)
* Error Recovery Agent (retries, rollbacks)

---

# 4) Data Stores (Source of Truth)

---

## 4.1 Config Sources

* config/sites/*.yaml
* config/schedules/*.yaml
* config/niches/*.yaml
* config/affiliates/*.yaml
* config/security/*.yaml

---

## 4.2 Runtime Stores

* DB: jobs, topics, page inventory, site inventory, link graph, metrics
* logs/: execution logs + validation failures
* runs/: snapshots of each daily run
* exports/: GSC/BWT/AI citation exports

---

# 5) Execution Schedule (Daily / Weekly / Monthly)

---

## 5.1 Daily Loop (Core money operations)

Every day OpenClaw runs this sequence:

1. Health Check (services, CMS auth, DNS)
2. Trend Scan + Query Capture
3. Competitor Weakness Scan (SERP snapshots)
4. Score + Prioritize topics
5. Generate outlines + data assembly
6. Generate drafts (TLDR + table + FAQ)
7. Run Content Quality Filter
8. Publish approved pages (staging or prod)
9. Update internal linking (new pages + existing)
10. Pull signals (GSC/BWT impressions, ranks, citations)
11. Trigger refresh queue for winners/decliners
12. Update "Health Score" and post summary report

---

## 5.2 Weekly Loop (Optimization)

Weekly OpenClaw performs:

* cluster integrity audit (internal links, orphan pages)
* title/meta CTR improvements for rising impressions
* refresh top pages (tiered)
* prune/merge duplicates into canonical pages
* cost audit (LLM usage, compute usage)
* affiliate conversion audit (EPC by page)

---

## 5.3 Monthly Loop (Scale decisions)

Monthly OpenClaw performs:

* portfolio performance review
* niche saturation review
* scale trigger evaluation
* site launch planning (if approved)
* vendor/tool spend optimization

---

# 6) Safety Gates (How We Don't Blow Up Sites)

---

## 6.1 Publishing Gates

OpenClaw must never mass publish without passing:

* TLDR present
* Comparison table present (if money page)
* FAQ present
* Internal links present (min threshold)
* Affiliate disclosure present
* No prohibited claims / unsafe content
* No duplicate/cannibalization collision
* Site daily publish quota not exceeded

Fail → route to Repair Queue.

---

## 6.2 Safe Mode Behavior

Safe Mode forces:

* no new publishing
* only health checks + metrics pulls
* only refresh drafts (not publish)
* alerts to owners

Kill switch overrides everything.

---

# 7) The "Authority Snowball" Wiring

Authority snowball means:

* Hub page exists per topic
* Supporting pages feed hub
* Hub feeds money pages
* Money pages feed conversion

OpenClaw must always maintain:

* Hub → Spokes → Money
* Spokes interlink laterally
* New pages auto-inserted into cluster graph

This is the secret compounding engine.

---

# 8) Output Reports (What Humans Review)

---

## 8.1 Daily Report

* pages drafted / pages published
* pages rejected and why
* ranking movers (top gainers/losers)
* impressions growth
* AI citations (if tracked)
* affiliate clicks + EPC snapshot
* health score

---

## 8.2 Weekly Report

* best clusters
* pages to refresh next
* content quality issues
* cost-per-published-page
* index coverage

---

## 8.3 Monthly Report

* ROI per site
* scale triggers hit or not
* saturation signals
* next-month publishing targets

---

# 9) Where Each Agent Reads/Writes

[Trend/Query Capture]
  reads: feeds, discussions, product lists
  writes: topic_candidates

[Competitor Weakness Scanner]
  reads: SERP results, competitor pages
  writes: topic_scores, gap_notes

[Content Generation]
  reads: topic_queue, prompts, templates, offers
  writes: drafts, structured blocks

[Quality Filter]
  reads: drafts
  writes: publish_approved or reject_reason

[Publishing Agent]
  reads: approved drafts
  writes: live pages, sitemap updates

[Internal Linking Agent]
  reads: page inventory + link graph
  writes: internal links inserted + graph updated

[SEO Signal Agent]
  reads: GSC/BWT/rank/AI citations
  writes: signals table + alerts

[Refresh Agent]
  reads: winners/decliners + freshness schedule
  writes: refresh drafts + publish updates

[Scaling System]
  reads: revenue + signals + saturation detector
  writes: scale recommendations / site launch proposals

---

# 10) "If This Breaks, What Happens?"

* Publishing breaks → Error Recovery Agent retries → if fail → Safe Mode
* Indexing tanks → Incident Runbook triggered → stop publishing → diagnose
* LLM spend spikes → Budget Guard halts generation → requires approval
* CMS auth fails → rotate keys → re-test staging before resuming

This is why Safe Mode exists.

---

# 11) Final Rule

OpenClaw is not a content machine.

OpenClaw is a CLOSED LOOP:

discover → publish → measure → improve → scale

If measurement stops, the system dies.

If safety gates fail, sites die.

If refresh stops, rankings die.

This architecture ensures none of those happen.
