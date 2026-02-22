# ARCHITECTURE.md — OpenClaw Affiliate Bot

## 1. System Overview
A queue-driven, agent-based automation system.

High-level flow:
1) Scheduler selects work
2) Research generates briefs
3) Content pipeline generates articles
4) Publishing pipeline posts content (DRY_RUN by default)
5) Analytics captures signals
6) Health monitor ensures system stability
7) Recovery agent retries/alerts

## 2. Key Architectural Principles
- Agents are modular and independently testable
- Everything is observable (logs, metrics, audit events)
- Job execution is idempotent (safe to retry)
- Local-first development; cluster is deployment target, not dev requirement

## 3. Components
### 3.1 Orchestrator
Coordinates agent execution and state transitions.

### 3.2 Scheduler
Creates daily work plan and enqueues jobs.

### 3.3 Queue
Interface-based queue:
- start: in-process queue
- later: Redis/RQ, Celery, etc.

### 3.4 Storage
- default: SQLite for local development
- upgrade path: Postgres for cluster

### 3.5 Integrations (stubs first)
- WordPress (REST API)
- DNS/CDN providers (as needed)
- Hosting provider API (as needed)
- Analytics platforms
- Affiliate networks

## 4. Data Model (minimum)
- Runs (timestamped executions)
- Jobs (queued tasks)
- Artifacts (outputs: briefs, drafts, metadata)
- Sites (site configs)
- Posts (post status, slug, publish state)
- Metrics snapshots (traffic, ranking, conversions when available)

## 5. Execution Modes
- DRY_RUN: write artifacts only
- SAFE_STAGING: publish to staging only
- PRODUCTION: publish to production sites

## 6. Cluster Topology (2-node)
- Node A: Scheduler + Orchestrator primary + publishing (optional)
- Node B: content generation + research + analytics (optional)
Roles are configurable; both nodes can run workers.

## 7. Observability
- Structured logs (JSON recommended)
- Audit log for site/domain affecting actions
- Health endpoint + periodic health checks
- Optional dashboard for status

## 8. Failure Handling
- Retries with backoff
- Dead-letter queue (future)
- Recovery agent to re-enqueue safe tasks
- Hard stop on suspicious actions (e.g., repeated publishing failures)
