# OpenClaw Affiliate Marketing Automation Bot

Owned by: Corey, DA/Don Anthony, Fern, David, Jamie.

## What this is
A cluster-ready automation system that:
- researches niches/products
- generates SEO-structured content
- publishes and maintains niche sites (DRY_RUN default)
- tracks performance and revenue signals
- runs reliably with runbooks and policies

## What this is NOT
- Not related to any other project
- Not black-hat SEO automation
- Not an ad arbitrage bot

## Quick Start (Local Dev)

```bash
# 1. Clone and enter repo
git clone <repo-url> && cd Affiliate-Whiz

# 2. Create virtual environment
python3.11 -m venv .venv && source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Initialize (creates DB, dirs, .env)
python -m src.cli init

# 5. Run in DRY_RUN mode
python -m src.cli run --dry-run --ticks 2

# 6. Check status
python -m src.cli status

# 7. Run tests
python -m pytest tests/ -v
```

## Quick Start (Scripts)
1) Copy `.env.example` to `.env` and fill placeholders.
2) Bootstrap local environment:
   - `bash scripts/dev/bootstrap_local.sh`
3) Run DRY_RUN:
   - `bash scripts/dev/run_local_dry.sh`
4) Check status:
   - `python -m src.cli status`

## Docker (Local)
```bash
docker compose -f deployments/docker/docker-compose.yml up openclaw-dev
```

## Cluster Hardware Context (Current)
- 2× Mac minis (Node A, Node B)
- 2× SSD docking stations
- Netgear 16-port PoE gigabit switch
- CyberPower CP1500AVRLCD3 UPS
- Dedicated Spectrum router + dedicated 1Gbps internet

## Documentation
Start here:
- PRD.md
- ARCHITECTURE.md
- PLAN.md
- AI_RULES.md
- STARTUP_CHECKLIST.md

Operations:
- docs/ops/RUNBOOK_CLUSTER.md
- docs/ops/RUNBOOK_SECURITY.md
- docs/ops/RUNBOOK_BACKUP_DR.md
- docs/ops/RUNBOOK_SITE_FACTORY.md
- docs/ops/RUNBOOK_CONTENT_ENGINE.md
