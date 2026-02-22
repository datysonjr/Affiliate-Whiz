# RUNBOOK_BUDGET_GUARDRAILS.md — Prevent runaway LLM spend

## Purpose
LLM usage can balloon costs fast if you don't enforce caps.

This runbook defines:
- hard limits
- alerts
- safe operating defaults
so OpenClaw remains profitable and predictable.

---

## Golden Rule
We never scale content volume until:
- we see indexing signals
- we see impressions/clicks
- we validate conversion potential

Automation without limits = expensive noise.

---

## 1) Hard Caps (Recommended Defaults)

### Daily caps
- MAX_TOTAL_POSTS_PER_DAY = 10 (start at 3 in production week 1)
- MAX_SITES_TOUCHED_PER_DAY = 2 (start at 1 in production week 1)
- MAX_JOBS_PER_HOUR = 30

### Per-site caps
- MAX_POSTS_PER_SITE_PER_DAY = 3 (start at 1 early)

### Retry limits
- JOB_RETRY_LIMIT = 2
- Backoff seconds = 10,60
Why: Retries can explode token usage.

---

## 2) Token / Prompt Hygiene (How to reduce cost)
- Use structured JSON outputs where possible (less back-and-forth)
- Cache results:
  - prompt hash → output stored
  - avoid regenerating the same outline/draft multiple times
- Prefer "edit and improve" over re-generating from scratch
- Put strict word-count bounds on drafts

Suggested v1 bounds:
- min 900 words
- max 1800 words

---

## 3) Budget Targets (Set this before you run production)
Pick a monthly LLM budget cap:
- Starter: $200–$500/mo
- Growth: $500–$1,500/mo
- Scale:  $1,500–$5,000/mo

Then enforce:
- daily budget limit = monthly / 30

Example: $600/mo → $20/day cap

---

## 4) Alerting Rules (Must)
If any condition triggers, OpenClaw should:
- stop non-critical jobs
- switch to DRY_RUN
- notify the team

Alerts:
- daily LLM spend exceeds daily cap
- article count exceeds daily cap
- repeated failures trigger retries > threshold
- queue depth grows without completion

---

## 5) Safe Modes & Kill Switches
### DRY_RUN (default)
- allowed always

### SAFE_STAGING
- requires ALLOW_PUBLISHING=true
- posts are draft-only

### PRODUCTION
- requires explicit switch
- best to keep "draft-only by default" and promote intentionally

Kill switches:
- ALLOW_PUBLISHING=false → disables publishing agent
- OPENCLAW_MODE=DRY_RUN → disables external posting

---

## 6) Spend Governance Workflow
Weekly (Monday):
- review total spend
- review outputs produced
- review performance signals
- decide: increase, hold, or reduce volume

Rule: If no signal (impressions/clicks) after consistent publishing:
- do NOT increase volume blindly
- adjust topic selection + internal linking first

---

## 7) Cost Projection Model (simple)
Daily token spend roughly scales with:
- #articles/day × average tokens/article

So to control spend:
- reduce article volume
- reduce tokens/article
- reduce rewrites
- increase caching

---

## 8) Implementation Notes (Engineering)
OpenClaw should store per-run counters:
- tokens in
- tokens out
- estimated $ cost (provider-specific)
- article count
- rewrite count

Then enforce:
- a daily cap check before starting new content batches
- a per-job cap check before generation
