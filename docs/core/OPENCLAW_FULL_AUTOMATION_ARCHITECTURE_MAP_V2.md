# OPENCLAW_FULL_AUTOMATION_ARCHITECTURE_MAP_V2.md
OpenClaw Affiliate Automation (Friend Group)

Purpose: Provide the operational "wiring diagram" WITH:
- schedules
- queue priorities
- rate limits
- database schema
- job lifecycle
- safety controls

This is the implementation-grade map.

---

# 1) System Overview (One Diagram)

```txt
 [Signals] → [Topic Candidates] → [Scoring] → [Topic Queue]
                                         |
                                         v
         [SERP Scanner] → [Gap Notes] → [Scoring Boost]
                                         |
                                         v
                    [Outline + Evidence Assembly]
                                         |
                                         v
 [Draft Generator] → [Quality Filter] → [Staging Publish]
                                         |
                                         v
                        [Canary → Full Publish]
                                         |
                                         v
                  [Internal Link Graph Update]
                                         |
                                         v
        [Index/Discovery Pings] → [Metrics Pull]
                                         |
                                         v
      [Winners/Losers Detection] → [Refresh Queue]
                                         |
                                         v
                   [Scale Trigger Engine]
                                         |
                                         └────→ [Launch New Site Proposal]
```

---

# 2) Schedules (Cron + Cadence)

All times below assume local time for the cluster.

---

## 2.1 Core Daily Cron Schedule

---

### 02:00 — NIGHTLY HEALTH + DEPENDENCY CHECK

* Validate network up
* Validate CMS auth
* Validate registrar/DNS reachable
* Validate DB + queue healthy
* Validate disk space, CPU/RAM
Output: health report + health score

---

### 02:15 — TREND + QUERY CAPTURE

* Pull trend feeds (product release lists, discussions, etc.)
* Generate candidate topics
Output: topic_candidates

---

### 02:45 — COMPETITOR WEAKNESS SCAN (SERP SNAPSHOTS)

* For each top candidate, sample SERP
* Extract competitor structure signals
Output: serp_snapshots + gap_notes

---

### 03:30 — SCORING + TOPIC QUEUE BUILD

* Score candidates
* Apply boosts (low supply / high intent / weak competitors)
Output: topic_queue

---

### 04:00 — OUTLINE + EVIDENCE ASSEMBLY

* Build outline
* Build entity list
* Build "facts to verify"
Output: outlines + evidence_tasks

---

### 05:00 — DRAFT GENERATION (STAGING)

* Generate drafts with required blocks:
TLDR + Table + Verdict sentences + FAQ + Disclosure + Internal Links plan
Output: drafts (status = STAGING_READY)

---

### 06:00 — CONTENT QUALITY FILTER (HARD GATES)

* Validate structure + extractability
* Duplicate/cannibalization check
* Compliance check (no banned claims)
Output: publish_decisions (APPROVE / REJECT)

---

### 06:30 — STAGING PUBLISH

* Publish approved drafts to staging
* Build preview links
Output: staging_urls

---

### 07:00 — CANARY LIVE PUBLISH (5–10% OF TODAY'S BATCH)

* Publish a small subset to live
* Confirm:

   * page loads
   * metadata correct
   * schema valid
   * internal links present
Output: canary_results

---

### 08:00 — FULL LIVE PUBLISH (IF CANARY PASSES)

* Publish remaining approved pages
Output: live_urls + publish log

---

### 08:30 — INTERNAL LINK GRAPH UPDATE

* Insert new links into existing pages
* Update hub/spoke relationships
Output: link_graph updates + patched pages

---

### 09:00 — INDEX + DISCOVERY PINGS

* Sitemap update
* Optional IndexNow ping (where supported)
Output: index_ping log

---

### 12:00 — MIDDAY METRICS PULL

* Pull rank samples
* Pull GSC/BWT impressions/clicks deltas (where available)
Output: metrics snapshot

---

### 18:00 — EVENING METRICS PULL + ALERTS

* Pull conversions (affiliate clicks if tracked)
* Detect anomalies
Output: alerts + daily summary

---

## 2.2 Weekly Schedule

---

### Sunday 03:00 — WEEKLY CLUSTER AUDIT

* Orphan page detection
* Broken links scan
* Hub completeness score
* Thin page detection

---

### Sunday 04:00 — WEEKLY REFRESH PLANNING

* Select refresh targets based on:

   * impressions rising but CTR low
   * ranks 8–20 ("push zone")
   * money pages declining

* Build refresh_queue

---

### Sunday 05:00 — COST + BUDGET AUDIT

* LLM spend per page
* per-site cost
* "runaway prevention" checks

---

## 2.3 Monthly Schedule

---

### 1st of month 04:00 — PORTFOLIO REVIEW

* ROI per site
* saturation signals
* scale triggers

---

### 1st of month 05:00 — SITE LAUNCH PROPOSALS

* If triggers met, create plan:

   * new domain
   * niche
   * initial 20 pages
   * budget caps

---

# 3) Queue Priorities (What Gets Done First)

OpenClaw uses multiple queues with strict priority order:

1. INCIDENT_QUEUE (highest)
2. SAFE_MODE_QUEUE (kill-switch tasks)
3. PUBLISH_REPAIR_QUEUE
4. REFRESH_QUEUE (money pages first)
5. INTERNAL_LINK_QUEUE
6. MONEY_PAGE_QUEUE
7. SUPPORT_PAGE_QUEUE
8. EXPERIMENT_QUEUE (lowest)

---

# 4) Rate Limits (Avoid Overpublishing / Crawl Issues)

---

## 4.1 Publishing Caps (per site)

* New site (0–30 days): 2–4 pages/day max
* Growing site (30–180 days): 4–8 pages/day max
* Established site (180+ days): 8–15 pages/day max

---

## 4.2 Canary Rules

* Always canary 5–10% of batch
* If any failures → stop full publish and go to SAFE MODE

---

## 4.3 Refresh vs New Content Allocation

* 60% refresh/optimization
* 30% expansion
* 10% experiments

---

# 5) Data Schema (Implementation Grade)

This schema is designed to support:

* automation
* reporting
* safety
* replayability

Use Postgres (recommended), but tables can map to other DBs.

---

## 5.1 `sites`

Stores site registry.

Fields:

* id (uuid)
* domain (text, unique)
* niche (text)
* cms_type (text)  # wordpress, headless, etc.
* hosting_provider (text)
* status (text)  # active, paused, staging_only
* created_at (timestamp)
* last_publish_at (timestamp)
* daily_publish_cap (int)
* notes (text)

---

## 5.2 `affiliate_programs`

Affiliate account registry.

Fields:

* id (uuid)
* name (text)
* network (text)  # impact, cj, partnerstack, etc.
* payout_type (text)  # revshare, cpa, recurring
* avg_payout (numeric)
* cookie_window_days (int)
* deep_link_supported (bool)
* api_available (bool)
* status (text)
* notes (text)

---

## 5.3 `offers`

Offer catalog.

Fields:

* id (uuid)
* affiliate_program_id (uuid fk)
* brand_name (text)
* product_name (text)
* category (text)
* price_range (text)
* target_intents (text[])  # best, vs, worth it, alternatives
* landing_url (text)
* tracking_template (text)
* last_verified_at (timestamp)

---

## 5.4 `topic_candidates`

Raw ideas from discovery engine.

Fields:

* id (uuid)
* site_id (uuid fk)
* seed_source (text)  # trend, reddit, autocomplete, etc.
* query (text)
* intent (text)  # best/vs/review/alternatives/howto
* stage (text)   # awareness/consideration/decision
* created_at (timestamp)
* notes (text)

---

## 5.5 `serp_snapshots`

SERP sample data for candidates.

Fields:

* id (uuid)
* topic_candidate_id (uuid fk)
* captured_at (timestamp)
* engine (text)  # google/bing
* top_urls (jsonb)
* paa_questions (jsonb)
* snippet_patterns (jsonb)
* competitor_weakness_score (numeric)
* notes (text)

---

## 5.6 `topic_scores`

Computed scoring results.

Fields:

* id (uuid)
* topic_candidate_id (uuid fk)
* score_total (numeric)
* score_intent (numeric)
* score_competition (numeric)
* score_supply_gap (numeric)
* score_payout (numeric)
* score_ai_citable (numeric)
* recommended_page_type (text) # money/comparison/support
* recommended_cluster (text)
* created_at (timestamp)

---

## 5.7 `topic_queue`

Prioritized publish backlog.

Fields:

* id (uuid)
* site_id (uuid fk)
* topic_candidate_id (uuid fk)
* priority (int) # 1..100 (1 highest)
* status (text)  # queued, outlining, drafting, approved, rejected, published
* assigned_agent (text)
* scheduled_for (timestamp)
* created_at (timestamp)
* updated_at (timestamp)

---

## 5.8 `outlines`

Outlines + evidence requirements.

Fields:

* id (uuid)
* topic_queue_id (uuid fk)
* outline_md (text)
* entity_list (jsonb)
* required_facts (jsonb)  # items needing verification
* created_at (timestamp)

---

## 5.9 `drafts`

Generated content drafts.

Fields:

* id (uuid)
* topic_queue_id (uuid fk)
* version (int)
* status (text) # staging_ready, approved, rejected, published
* content_md (text)
* tldr_block (text)
* comparison_table (text)
* faq_block (text)
* disclosure_present (bool)
* created_at (timestamp)

---

## 5.10 `quality_checks`

Validation results for each draft.

Fields:

* id (uuid)
* draft_id (uuid fk)
* passed (bool)
* fail_reasons (jsonb)  # missing TLDR, no table, too thin, etc.
* duplicate_risk (numeric)
* cannibalization_risk (numeric)
* schema_valid (bool)
* internal_link_count (int)
* verdict_sentence_count (int)
* created_at (timestamp)

---

## 5.11 `pages`

Inventory of published pages.

Fields:

* id (uuid)
* site_id (uuid fk)
* url (text, unique)
* slug (text)
* page_type (text) # hub, money, comparison, support, review
* topic (text)
* status (text) # live, staging, archived
* canonical_url (text)
* published_at (timestamp)
* last_updated_at (timestamp)
* cluster_id (uuid fk nullable)

---

## 5.12 `clusters`

Topic cluster registry.

Fields:

* id (uuid)
* site_id (uuid fk)
* cluster_name (text)
* hub_page_id (uuid fk)
* created_at (timestamp)
* notes (text)

---

## 5.13 `internal_links`

Link graph.

Fields:

* id (uuid)
* site_id (uuid fk)
* from_page_id (uuid fk)
* to_page_id (uuid fk)
* anchor_text (text)
* link_type (text) # hub, sibling, money, nav
* inserted_at (timestamp)

---

## 5.14 `metrics_daily`

Daily metrics snapshot.

Fields:

* id (uuid)
* site_id (uuid fk)
* date (date)
* impressions (int)
* clicks (int)
* ctr (numeric)
* avg_position (numeric)
* ai_citations (int nullable)
* affiliate_clicks (int nullable)
* est_revenue (numeric nullable)
* notes (text)

---

## 5.15 `incidents`

Incident tracking.

Fields:

* id (uuid)
* site_id (uuid fk nullable)
* severity (text) # sev1..sev4
* title (text)
* description (text)
* status (text) # open, mitigated, resolved
* started_at (timestamp)
* resolved_at (timestamp nullable)
* actions_taken (jsonb)

---

## 5.16 `budgets`

Budget caps + guardrails.

Fields:

* id (uuid)
* scope (text) # global, site, agent
* scope_id (uuid nullable)
* monthly_cap_usd (numeric)
* daily_cap_usd (numeric)
* alert_threshold_pct (numeric) # e.g. 0.8
* current_month_spend (numeric)
* updated_at (timestamp)

---

# 6) Job Lifecycle (State Machine)

Each topic_queue item moves through:

```
queued
→ outlining
→ drafting
→ quality_check
→ staging_published
→ canary_published
→ published
→ monitored
→ refreshed (loop)
```

Any failure routes to:

```
rejected
→ repair_queue
→ drafting (again)
```

---

# 7) Safe Mode / Kill Switch Rules

---

## 7.1 Auto-Trigger Safe Mode if ANY:

* publish errors > 2 in a row
* schema validation fails on canary
* CMS auth failure
* indexing anomalies detected (sharp drop)
* LLM spend exceeds daily cap

Safe Mode actions:

* stop all publishing
* allow health checks + metrics pulls only
* route everything to incident queue
* notify owners

Kill Switch:

* immediate stop of all tasks
* requires manual reset token

---

# 8) Human Approval Points (Minimal but Real)

Even in automation, humans approve:

* new niche creation
* new site launch
* budget cap increases
* major template changes
* vendor/tool additions

Everything else can be automated.

---

# 9) "What Runs Where" (Node Mapping)

Mac mini node A (orchestrator):

* scheduler
* DB
* queue
* monitoring
* publishing agent

Mac mini node B (worker):

* content generation
* serp scan parsing
* internal link insertion
* refresh engine

(Adjust later as your cluster grows.)

---

# 10) Final Operating Rule

Scale is not "more content".

Scale is:

* better topic selection
* higher conversion page types
* internal linking compounding
* refresh winners
* controlled portfolio expansion
* strict safety gates

OpenClaw is a money loop, not a blog bot.
