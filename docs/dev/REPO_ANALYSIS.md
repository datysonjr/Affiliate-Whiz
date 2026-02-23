# Affiliate-Whiz (OpenClaw) — Repository Analysis

## What It Is

**OpenClaw** is a queue-driven, agent-based automation system for building and
operating affiliate marketing niche websites.  It automates the full pipeline:
niche research, SEO-optimized content generation, WordPress publishing, analytics
tracking, and portfolio scaling.

Owned/operated by: Corey, DA/Don Anthony, Fern, David, Jamie.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11 |
| LLM Providers | Anthropic (primary), OpenAI (fallback) |
| CMS | WordPress REST API |
| Database | SQLite (local dev), Postgres (cluster upgrade path) |
| Queue | In-process (start), Redis/Celery (scale path) |
| Storage | Local disk + S3-compatible (boto3) |
| Deployment | Docker Compose, macOS launchd, Kubernetes (placeholder) |
| CI | GitHub Actions (ruff, mypy, pytest) |
| Observability | Structured JSON logs, Grafana dashboard template, alert rules YAML |
| Testing | pytest + pytest-cov + pytest-asyncio |

---

## Architecture

The system follows a **plan → execute → report** lifecycle for every agent, all
coordinated by a central `OrchestratorController` (`src/orchestrator/controller.py`).

### Core Flow

1. Scheduler selects work
2. Research agent generates briefs
3. Content pipeline generates articles (via LLM)
4. Publishing pipeline posts to WordPress (DRY_RUN by default)
5. Analytics captures performance signals
6. Health monitor ensures stability
7. Error recovery retries/alerts

### 8 Agents (`src/agents/`)

| Agent | Role |
|---|---|
| MasterSchedulerAgent | Builds daily/weekly plan |
| ResearchAgent | Niche/product research and brief creation |
| ContentGenerationAgent | Outlines + drafts + SEO metadata (uses LLMTool) |
| PublishingAgent | WordPress publishing (uses CMSTool) |
| AnalyticsAgent | Fetches traffic/revenue signals |
| HealthMonitorAgent | Disk/queue/DB/connectivity checks |
| ErrorRecoveryAgent | Retries, resumes, alerts |
| TrafficRoutingAgent | Placeholder for CDN/edge experiments |

### 7 Agent Tools (`src/agents/tools/`)

| Tool | Status |
|---|---|
| LLMTool | IMPLEMENTED — Anthropic/OpenAI with automatic fallback |
| CMSTool | IMPLEMENTED — WordPress REST with retry/backoff |
| SEOTool | Partial — keyword density + schema markup work; SERP analysis stubbed |
| AnalyticsTool | Stub — caching/parsing works; API queries return empty data |
| BrowserTool | Stub |
| ScraperTool | Stub |
| LinkTool | Stub |

### Two Execution Modes for Agents

- `--real-agents` flag uses actual LLM/CMS integrations
- Default uses lightweight stub agents that simulate the flow without API calls

---

## 3 Execution Modes

| Mode | Behavior |
|---|---|
| `DRY_RUN` (default) | Generates artifacts locally, never publishes externally |
| `SAFE_STAGING` | Can publish to a staging WordPress site only |
| `PRODUCTION` | Publishing enabled for production sites (explicit approval required) |

A **kill switch** (`python -m src.cli kill-switch --engage`) immediately halts all agents.

---

## Directory Structure

```
src/
  agents/          # 8 agents + 7 tools
  core/            # constants, errors, logger, queue, settings, utils
  data/            # SQLite DB, migrations, models (campaigns, experiments, offers, posts, sites)
  domains/         # Business logic: analytics, content, offers, publishing, SEO
  integrations/    # External: affiliates (Amazon, CJ, Impact, ShareASale), DNS, email, hosting, proxy, storage
  observability/   # Metrics, tracing, Grafana dashboard, alert rules
  ops/             # Canary publish utility
  orchestrator/    # Controller, scheduler, state machine, policies (AI rules, posting, risk)
  pipelines/       # 4 pipelines: content, offer_discovery, optimization, publishing
  security/        # Audit log, key rotation, permissions, vault
  web/             # Admin API + health endpoint

docs/              # 80+ documents across 15 categories
config/            # YAML configs: agents, cluster, niches, pipelines, providers, schedules, sites, thresholds
tests/             # Unit (14 files), integration, e2e, fixtures
scripts/           # Dev + cluster bootstrap, backup, deploy scripts
deployments/       # Docker, k8s (empty), launchd plist
ops/               # Infra notes, bootstrap scripts, secrets management
```

---

## Hardware Context

Designed for a 2-node physical cluster:

- 2× Mac minis (Node A: scheduler/orchestrator, Node B: content/research/analytics)
- 2× SSD docking stations
- Netgear 16-port PoE gigabit switch
- CyberPower UPS
- Dedicated Spectrum router + 1Gbps internet

---

## Current Implementation Status

### Implemented (P0)

- Full orchestrator with state machine, kill switch, cooldown, policy enforcement
- `BaseAgent` lifecycle (plan → execute → report) with timing, error handling, dry-run
- `LLMTool` — Anthropic primary + OpenAI fallback, retry, token tracking
- `CMSTool` — WordPress REST API, auth, retry, media upload, categories/tags
- Publish pipeline wired to CMSTool
- CLI with `init`, `run`, `status`, `health`, `kill-switch`, `publish-canary`
- SQLite database with migrations, agent run recording
- GitHub Actions CI (ruff + mypy + pytest)
- 14 unit test files + integration + e2e structure
- 30 complete article briefs for a "home office" niche launch set

### Stubbed (not yet implemented)

- SEO tool SERP/keyword analysis (provider integration needed)
- Analytics tool GA4/GSC/affiliate network pulls
- Browser, scraper, link tools
- Rollback/recovery for publishing mistakes
- Postgres for cluster mode
- Redis queue upgrade

---

## Phased Agenda (from PLAN.md)

| Phase | Goal | Status |
|---|---|---|
| **Phase 0** — Repo & Docs | Create structure, governing docs, runbooks, policies | Complete |
| **Phase 1** — Local DRY_RUN MVP | Orchestrator, agents, SQLite, CLI, smoke tests | Mostly complete |
| **Phase 2** — SAFE_STAGING Publishing | WordPress integration, staging gate, analytics snapshots | In progress |
| **Phase 3** — Cluster Deployment | Docker + compose, node bootstrap, health monitoring, backup/restore | Scaffolded |
| **Phase 4** — Production Launch | First production site from template, limited cadence, weekly review | Not started |
| **Phase 5** — Scale | Redis queue, Postgres, dashboards, alerting, multi-site expansion | Not started |

---

## Revenue Model & Timeline

The 90-day ramp plan and revenue model set realistic expectations:

| Stage | Timeline | Expected Revenue |
|---|---|---|
| Signal Phase | Months 0–3 | $0–$50/month |
| Early Monetization | Months 3–6 | $50–$500/month |
| Consistent Site | Months 6–12 | $500–$2,000/month per site |
| Authority Site | Months 12–24 | $2,000–$10,000/month per site |
| Portfolio Scale | 12+ months | $20k–$50k/month across 10+ sites |

---

## Key Takeaways

1. **Architecturally thorough** — 80+ docs, clear separation of concerns, well-defined
   agent model.  Design work is significantly ahead of implementation.

2. **MVP is close** — The core pipeline (research → content → publish) works end-to-end
   with `--real-agents` when LLM and WordPress credentials are configured.

3. **Primary gaps for live operation:** SEO tool provider integration (SerpAPI or similar),
   analytics API connections (GA4/GSC), publishing rollback capability.

4. **Safety-first design** — DRY_RUN default, kill switch, policy enforcement, audit
   logging, staging gates all built in.
