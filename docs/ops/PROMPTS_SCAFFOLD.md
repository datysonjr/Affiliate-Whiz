# PROMPTS_SCAFFOLD.md — Claude Code Prompts to Build OpenClaw

These are the exact prompts to paste into Claude Code (in order) to turn
this repository into a working OpenClaw system.

---

## Prompt 1 — Generate the working repo

```
This repository is for an OpenClaw affiliate marketing automation bot.

The system must run locally first before cluster deployment.

Use the markdown documents in this repo as requirements:
- PRD.md
- PLAN.md
- ARCHITECTURE.md
- AI_RULES.md

Create a runnable Python scaffold that:

1) Starts a scheduler loop
2) Creates a job queue
3) Executes agents in sequence:
   research → content → publishing → analytics
4) Supports DRY_RUN mode that never posts publicly
5) Logs everything to /data/logs
6) Stores state in SQLite
7) Provides CLI commands:
    oc run --dry-run
    oc run --staging
    oc status

Add:

- Dockerfile
- docker-compose.yml
- pyproject.toml
- minimal tests

Ensure:

python -m src.main

runs without errors in DRY_RUN mode.
```

---

## Prompt 2 — Improve orchestrator

```
Improve the orchestrator so that:

- all agents inherit from BaseAgent
- all jobs are logged
- retries are handled automatically
- failures move jobs into quarantine

Add structured logging and audit logging.
```

---

## Prompt 3 — WordPress publishing integration

```
Implement the WordPress publishing integration.

Requirements:

- use WP REST API
- authenticate via application password
- create draft posts
- attach metadata
- attach affiliate disclosure block
- never publish immediately

Include DRY_RUN stub behavior.
```

---

## Prompt 4 — Health monitoring and stabilization

```
Add health monitoring:

- disk usage checks
- queue depth monitoring
- scheduler heartbeat
- alert logs when limits exceeded

Ensure system can run continuously.
```
