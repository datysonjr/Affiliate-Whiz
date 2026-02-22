# SOFTWARE_CLUSTER_STACK.md — What runs where (Mac minis / cluster)

## Purpose
This document maps:
- which software is required
- what runs on Node A vs Node B
- why each piece exists

---

## Base System Requirements (Both Nodes)
### macOS
- Keep OS updated
- Disable sleep for always-on operation (or set safe sleep policy)
- Configure auto-restart after power loss if available

### Package/Runtime
- Python 3.11+
- Git
- Docker Desktop (or alternative container runtime on macOS)
- Optional: Homebrew (for convenience)

### Repo Runtime
- OpenClaw app (Python)
- `.env` per node (never commit)
- `/data` mounted to SSD (recommended)

---

## Node A — Control Plane (oc-core-01)
Runs:
- OpenClaw Orchestrator (controller/router)
- Scheduler (cron-like job trigger)
- DB host (SQLite v1; Postgres recommended later)
- Audit logging and backups
- Health checks

Required software:
- Docker + Compose
- Backup scripts
- Optional: UPS USB monitoring software (if using USB shutdown integration)

Why:
- Centralized control prevents "agents running wild"
- Node A becomes the "truth" source for runs/jobs and state

---

## Node B — Work Plane (oc-work-01)
Runs:
- Worker pool (content generation pipelines)
- Publishing worker (gated; staging/prod)
- Analytics ingestion worker
- Optional: lightweight local cache for LLM outputs

Required software:
- Docker + Compose
- Same repo version
- Same config templates

Why:
- Keep heavy work separate from control plane
- Publishing isolated reduces risk (gated mode)

---

## Storage (Both Nodes)
SSD dock recommended mount:
- `/Volumes/OpenClawData` (macOS default style)

Inside containers mount:
- `./data:/data`

Required:
- Enough free space for:
  - DB snapshots
  - exported content artifacts
  - logs
  - media assets (if uploading images)

---

## Optional: Redis + Postgres (Recommended as you scale)
### Redis (Queue / message broker)
- Benefits: reliable job queue, retries, distributed workers
- Programmatic: standard Redis protocols; many Python libs

### Postgres (DB)
- Benefits: concurrency-safe, robust migrations, multi-node friendly
- Programmatic: psycopg, SQLAlchemy, async libs

Suggested timeline:
- Start SQLite for local DRY_RUN
- Move to Postgres when you begin multi-node PRODUCTION publishing
