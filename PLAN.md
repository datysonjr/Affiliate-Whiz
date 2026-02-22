# PLAN.md — Implementation Plan (Local → Cluster)

## Phase 0 — Repo & Docs
- Create repo structure
- Write governing docs (PRD, Architecture, AI Rules, Plan, Startup Checklist)
- Add runbooks and policies

## Phase 1 — Local DRY_RUN MVP
- Implement orchestrator/scheduler/queue
- Implement agents with stub integrations
- Implement SQLite storage and artifact exporting
- Add CLI commands: init/run/status
- Add smoke tests

## Phase 2 — SAFE_STAGING Publishing
- Implement WordPress integration
- Staging mode publishing gate (explicit env flag)
- Publishing checklists + rollback guidance
- Add analytics snapshots (Search Console / GA / basic rank checks if used)

## Phase 3 — Cluster Deployment
- Add Docker + compose (local and cluster)
- Add node bootstrap scripts
- Define roles and networking templates
- Implement health monitor checks for both nodes
- Add backup/restore automation

## Phase 4 — Production Launch
- Create first production site from template
- Run limited publishing cadence
- Weekly review + tune content quality
- Expand to additional sites

## Phase 5 — Scale
- Add new nodes procedure
- Improve queue (Redis) + DB (Postgres)
- Add dashboards and alerting
- Enhance internal linking and topical authority mapping
