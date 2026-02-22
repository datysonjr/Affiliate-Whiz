# OpenClaw - Affiliate Marketing Automation Bot

OpenClaw is a multi-agent affiliate marketing automation system designed for scalable, safe, and observable content publishing operations.

## Architecture Overview

- **orchestrator/** - The "brain" that decides what happens and when
- **agents/** - The "hands" that execute specific tasks
- **pipelines/** - Reusable assembly lines for repeatable workflows
- **domains/** - Business logic models (offers, posts, campaigns, SEO)
- **integrations/** - External service connectors (affiliate networks, CMS, DNS, proxies)
- **ops/** + **config/** + **docs/** - Operational tooling for team use

## Key Design Principles

1. **Separation of concerns** - Agents decide, pipelines execute, integrations connect, domains model
2. **Single controller** - All agent actions route through `orchestrator/controller.py` for rate-limiting, logging, kill switches, and dry-run mode
3. **Policy enforcement** - Runtime constraints via policy files (posting, risk, AI rules)
4. **Config-driven** - Change behavior via YAML config without code changes

## Team / Node Roles

| Node | Role | Responsibilities |
|------|------|-----------------|
| oc-core-01 | Control + Writing | Orchestrator, research, content generation, queue + DB |
| oc-pub-01 | Publishing + Monitoring | Publishing pipeline, CMS/DNS/hosting, monitoring, backups |

## Quick Start (Local Dev - Run on Your Laptop in <5 Minutes)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Initialize the system (creates DB, directories, .env)
python -m src.cli init

# 3. Run the full pipeline in DRY_RUN mode (safe - no real API calls)
python -m src.cli run --dry-run

# 4. Check system status (shows recent runs, DB state, config)
python -m src.cli status

# 5. Run with more ticks and see it loop
python -m src.cli run --dry-run --ticks 3 --interval 5

# 6. Run only the content pipeline
python -m src.cli run --dry-run --pipeline content

# 7. Run the main entry point directly
python -m src.main --node-role core --dry-run --max-ticks 1
```

### What You'll See

The dry-run pipeline proves the full flow end-to-end:
- **Scheduler** starts and ticks on an interval
- **Research agent** plans keyword research, logs what it would do
- **Content agent** plans article drafts, logs what it would generate
- **Publishing agent** checks the queue, skips actual CMS publishing
- **Analytics agent** plans metrics collection, logs what it would query
- All runs are **recorded to SQLite** (`data/openclaw.db`)
- All actions are **logged** to `logs/openclaw.log`

### Docker (Alternative)

```bash
# Local dev mode (single container)
docker compose -f deployments/docker/docker-compose.yml up openclaw-dev

# Cluster mode (two containers simulating Mac Mini nodes)
docker compose -f deployments/docker/docker-compose.yml up openclaw-core openclaw-pub
```

### Run Tests

```bash
pip install pytest
python -m pytest tests/unit/ -v
```

## Branch Strategy

- `main` - stable production
- `dev` - integration branch
- `feat/*` - feature branches (e.g., `feat/offer-scoring-v2`)

## Documentation

- [PRD](PRD.md) - Product Requirements Document
- [PLAN](PLAN.md) - Implementation Plan
- [ARCHITECTURE](ARCHITECTURE.md) - System Architecture
- [AI_RULES](AI_RULES.md) - AI Agent Constraints and Rules
- [STARTUP_CHECKLIST](STARTUP_CHECKLIST.md) - Launch Checklist
- [Runbooks](docs/runbooks/) - Operational runbooks
- [Playbooks](docs/playbooks/) - Strategy playbooks
