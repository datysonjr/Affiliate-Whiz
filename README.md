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

## Quick Start

```bash
# 1. Copy environment template
cp ops/env/example.env .env

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run bootstrap (macOS)
bash ops/scripts/bootstrap_mac_node.sh

# 4. Start the system
python src/main.py
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
