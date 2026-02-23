# RUN_PATHS.md

How to run OpenClaw in each mode, from safest to most real.

## 1. Local smoke test (stubs — default)

```bash
python -m src.cli init
python -m src.cli run --dry-run --ticks 2
```

Uses Local* stub agents. No real API calls. Proves the scheduler/orchestrator loop works.

## 2. Real agents in dry-run (validates agent wiring)

```bash
python -m src.cli run --dry-run --ticks 1 --real-agents
```

Uses real agent classes (ResearchAgent, ContentGenerationAgent, PublishingAgent, etc.)
but in dry-run mode. Agents skip all side-effects. Proves real agents instantiate and
run the plan/execute/report lifecycle without errors.

## 3. Real agents with LLM (generates real content, no publishing)

```bash
export LLM_API_KEY=sk-ant-...
python -m src.cli run --dry-run --ticks 1 --real-agents --pipeline content
```

ContentGenerationAgent calls LLMTool to generate real outlines and article drafts.
Publishing is skipped because `--dry-run` is set. Use this to validate LLM output quality.

## 4. Staging publish (WordPress draft)

```bash
export LLM_API_KEY=sk-ant-...
export WP_STAGING_BASE_URL=https://staging.yoursite.com/wp-json/wp/v2
export WP_STAGING_USER=openclaw-publisher
export WP_STAGING_APP_PASSWORD=xxxx xxxx xxxx xxxx
python -m src.cli run --ticks 1 --real-agents
```

Full pipeline: research -> content generation (LLM) -> SEO validation -> publish to WP as draft.
Posts appear in WP Admin -> Posts -> Drafts.

## 5. Live publish (guarded — future)

```bash
export OPENCLAW_MODE=PRODUCTION
export WP_PROD_BASE_URL=...
export WP_PROD_USER=...
export WP_PROD_APP_PASSWORD=...
python -m src.cli run --real-agents
```

Requires promotion criteria from `docs/ops/RUNBOOK_DRY_RUN_TO_LIVE_MONEY.md`:
- 10 successful staging publishes
- No schema failures
- Manual review confirms disclosures
- Kill switch thresholds configured

## Quick reference

| Command | Agents | LLM | CMS | Safe? |
|---------|--------|-----|-----|-------|
| `run --dry-run` | stub | no | no | yes |
| `run --dry-run --real-agents` | real | no | no | yes |
| `run --dry-run --real-agents` + LLM_API_KEY | real | yes | no | yes |
| `run --real-agents` + WP env vars | real | yes | draft | mostly |
| `run --real-agents` (production) | real | yes | publish | guarded |
