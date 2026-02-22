# OPENCLAW_REPO_STRUCTURE_FINAL.md

OpenClaw Affiliate Automation System (Friend Group)

Purpose: Defines the final, pro-level repository structure for the OpenClaw affiliate automation bot.

Goals:

- clear separation of concerns (core app vs configs vs ops docs)
- safe deployment patterns (staging/prod separation)
- reproducible local + cluster runs
- auditability (logs, runs, incidents, changes)
- easy onboarding for new contributors

---

## 1) Final Repo Tree (Recommended)

```
openclaw-affiliate-bot/
├─ README.md
├─ LICENSE
├─ .gitignore
├─ .env.example
├─ Makefile
├─ docker/
│  ├─ docker-compose.yml
│  ├─ docker-compose.override.yml
│  ├─ Dockerfile
│  └─ healthchecks/
│     ├─ http_check.sh
│     └─ queue_check.sh
├─ scripts/
│  ├─ dev/
│  │  ├─ bootstrap_local.sh
│  │  ├─ run_dry.sh
│  │  ├─ run_staging.sh
│  │  ├─ run_prod_limited.sh
│  │  ├─ lint.sh
│  │  └─ test.sh
│  ├─ ops/
│  │  ├─ rotate_wp_app_password.md
│  │  ├─ backup_now.sh
│  │  ├─ restore_from_backup.sh
│  │  ├─ export_logs.sh
│  │  └─ emergency_safe_mode.sh
│  └─ data/
│     ├─ init_db.sql
│     └─ migrations/
├─ config/
│  ├─ README.md
│  ├─ nodes/
│  │  ├─ nodes.example.yaml
│  │  └─ roles.example.yaml
│  ├─ schedules/
│  │  ├─ schedules.example.yaml
│  │  └─ throttles.example.yaml
│  ├─ sites/
│  │  ├─ sites.example.yaml
│  │  ├─ wordpress.example.yaml
│  │  └─ seo.example.yaml
│  ├─ niches/
│  │  ├─ niche_seeds.example.yaml
│  │  └─ keyword_rules.example.yaml
│  ├─ affiliates/
│  │  ├─ networks.example.yaml
│  │  ├─ offers.example.yaml
│  │  └─ tracking.example.yaml
│  ├─ prompts/
│  │  ├─ system_prompts.example.yaml
│  │  ├─ article_blueprint.example.md
│  │  └─ style_guide.example.md
│  └─ security/
│     ├─ secrets_policy.example.yaml
│     ├─ access_control.example.yaml
│     └─ safe_mode.example.yaml
├─ src/
│  ├─ openclaw/
│  │  ├─ __init__.py
│  │  ├─ main.py
│  │  ├─ settings.py
│  │  ├─ modes.py
│  │  ├─ constants.py
│  │  ├─ utils/
│  │  │  ├─ logging.py
│  │  │  ├─ hashing.py
│  │  │  ├─ time.py
│  │  │  └─ retry.py
│  │  ├─ core/
│  │  │  ├─ orchestrator.py
│  │  │  ├─ scheduler.py
│  │  │  ├─ queue.py
│  │  │  ├─ state_store.py
│  │  │  └─ gates.py
│  │  ├─ agents/
│  │  │  ├─ master_scheduler_agent.py
│  │  │  ├─ research_agent.py
│  │  │  ├─ competitor_scanner_agent.py
│  │  │  ├─ content_generation_agent.py
│  │  │  ├─ internal_linking_agent.py
│  │  │  ├─ publishing_agent.py
│  │  │  ├─ seo_signal_agent.py
│  │  │  ├─ analytics_agent.py
│  │  │  ├─ refresh_agent.py
│  │  │  ├─ health_monitor_agent.py
│  │  │  └─ error_recovery_agent.py
│  │  ├─ integrations/
│  │  │  ├─ llm/
│  │  │  │  ├─ base.py
│  │  │  │  ├─ openai_provider.py
│  │  │  │  ├─ anthropic_provider.py
│  │  │  │  └─ local_provider.py
│  │  │  ├─ wordpress/
│  │  │  │  ├─ client.py
│  │  │  │  ├─ auth.py
│  │  │  │  └─ formatter.py
│  │  │  ├─ google/
│  │  │  │  ├─ search_console.py
│  │  │  │  └─ analytics_ga4.py
│  │  │  └─ affiliates/
│  │  │     ├─ link_builder.py
│  │  │     └─ network_clients/
│  │  │        ├─ base.py
│  │  │        └─ placeholder.md
│  │  ├─ seo/
│  │  │  ├─ keyword_targeting.py
│  │  │  ├─ serp_parser.py
│  │  │  ├─ weakness_scoring.py
│  │  │  ├─ internal_link_graph.py
│  │  │  └─ quality_filters.py
│  │  ├─ content/
│  │  │  ├─ templates/
│  │  │  │  ├─ article_blueprint.md
│  │  │  │  ├─ comparison_table.md
│  │  │  │  └─ faq_block.md
│  │  │  ├─ renderers/
│  │  │  │  ├─ markdown_to_wp_html.py
│  │  │  │  └─ sanitizer.py
│  │  │  └─ validators/
│  │  │     ├─ structure_validator.py
│  │  │     ├─ affiliate_density.py
│  │  │     └─ plagiarism_guard.py
│  │  ├─ db/
│  │  │  ├─ models.py
│  │  │  ├─ migrations/
│  │  │  └─ repository.py
│  │  └─ telemetry/
│  │     ├─ metrics.py
│  │     ├─ health_score.py
│  │     └─ alerts.py
│  └─ cli/
│     ├─ oc.py
│     └─ commands/
│        ├─ run.py
│        ├─ status.py
│        ├─ safe_mode.py
│        ├─ publish.py
│        └─ validate.py
├─ tests/
│  ├─ unit/
│  ├─ integration/
│  └─ fixtures/
├─ docs/
│  ├─ core/
│  │  ├─ OPENCLAW_MASTER_EXECUTION_LOOP.md
│  │  ├─ OPENCLAW_KILL_SWITCH_AND_SAFE_MODE.md
│  │  ├─ OPENCLAW_DEPLOYMENT_DAY_PLAYBOOK.md
│  │  ├─ OPENCLAW_90_DAY_RAMP_PLAN.md
│  │  ├─ OPENCLAW_REALISTIC_REVENUE_MODEL.md
│  │  └─ OPENCLAW_REPO_STRUCTURE_FINAL.md
│  ├─ stack/
│  │  ├─ STACK_OVERVIEW.md
│  │  ├─ SOFTWARE_CLUSTER_STACK.md
│  │  ├─ LLM_STACK.md
│  │  ├─ WORDPRESS_STACK.md
│  │  ├─ SEO_ANALYTICS_STACK.md
│  │  └─ TOOLS_MATRIX.md
│  ├─ ops/
│  │  ├─ RUNBOOK_VENDOR_SELECTION.md
│  │  ├─ RUNBOOK_BUDGET_GUARDRAILS.md
│  │  ├─ RUNBOOK_CHANGE_MANAGEMENT.md
│  │  ├─ RUNBOOK_INCIDENTS.md
│  │  ├─ RUNBOOK_SCALE_TRIGGER.md
│  │  └─ RUNBOOK_CONTENT_QUALITY_FILTER.md
│  ├─ seo/
│  │  ├─ KEYWORD_TARGETING_FRAMEWORK.md
│  │  ├─ INTERNAL_LINKING_ENGINE_SPEC.md
│  │  ├─ SITE_AUTHORITY_SNOWBALL_MODEL.md
│  │  ├─ TOPIC_DISCOVERY_ENGINE.md
│  │  ├─ MONEY_PAGE_PRIORITIZATION.md
│  │  ├─ COMPETITOR_WEAKNESS_SCANNER.md
│  │  ├─ ARTICLE_REFRESH_ENGINE.md
│  │  ├─ SERP_DOMINATION_PLAYBOOK.md
│  │  └─ RUNBOOK_SEO_SIGNAL_TRACKING.md
│  ├─ finance/
│  │  └─ COST_PROJECTIONS.md
│  ├─ integrations_backlog/
│  │  └─ INTEGRATIONS_BACKLOG.md
│  ├─ changes/
│  │  └─ (YYYY-MM-DD-change-name.md files go here)
│  └─ incidents/
│     └─ (YYYY-MM-DD-incident.md files go here)
├─ data/
│  ├─ README.md
│  ├─ db/
│  ├─ logs/
│  ├─ runs/
│  ├─ exports/
│  └─ backups/
└─ .github/
   ├─ workflows/
   │  ├─ ci.yml
   │  └─ lint.yml
   └─ CODEOWNERS
```

---

## 2) Why This Structure Works (The "Pro" Logic)

### Separation of Concerns

- `src/` = the automation engine
- `config/` = all operational settings (editable without code changes)
- `docs/` = manuals + runbooks + systems thinking
- `scripts/` = one-command operations
- `data/` = persistent runtime artifacts (excluded from git)

### Safe-by-default

- `.env.example` makes it clear what must be set
- `modes.py` + `core/gates.py` enforce DRY_RUN / SAFE_STAGING / LIMITED_PRODUCTION / FULL_PRODUCTION
- `scripts/ops/emergency_safe_mode.sh` forces safe stop

### Team Scale Readiness

- `docs/changes` + `docs/incidents` enforce real operational discipline
- `.github/CODEOWNERS` helps enforce approvals
- workflows keep config and code stable

---

## 3) Required Conventions (Non-Negotiable)

### Naming

- Node A: `oc-core-01`
- Node B: `oc-work-01`
- Repo name: `openclaw-affiliate-bot` (recommended)

### Config Rules

- All `.yaml` files in `config/` are source-of-truth
- Never hand-edit live server config without committing the change

### Data Rules

- `data/` is NOT committed
- Backups stored under `data/backups/` and mirrored off-node (recommended)

---

## 4) Minimum "MVP Files" to Boot Safely

Must exist before any run:

- `.env` (from `.env.example`)
- `config/nodes/nodes.yaml`
- `config/nodes/roles.yaml`
- `config/schedules/schedules.yaml`
- `config/sites/sites.yaml`
- `config/sites/wordpress.yaml`
- `config/security/safe_mode.yaml`

---

## 5) Suggested "First Repo Commit" Checklist

- repo initialized
- folder tree created
- `.env.example` created (no secrets)
- config templates added (`*.example.yaml`)
- docs inserted (core/stack/seo/ops)
- docker compose present
- scripts added
- CI added
- run DRY_RUN successfully

---

## 6) Optional (High-Value) Enhancements

- Add `docs/onboarding/TEAM_ONBOARDING.md`
- Add `docs/onboarding/ROLE_ASSIGNMENTS.md`
- Add `docs/security/THREAT_MODEL.md`
- Add `docs/ops/RUNBOOK_BACKUPS_AND_RESTORE.md`

---

## Final Rule

If it's not in this repo structure, it's not real.

**This repo is the "single source of truth" for the OpenClaw affiliate automation bot.**
