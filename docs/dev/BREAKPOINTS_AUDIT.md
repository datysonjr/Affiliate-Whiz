# BREAKPOINTS_AUDIT.md

This doc lists where the repo breaks when moving from stub agents to real production execution,
and tracks which breakpoints have been resolved.

## CURRENT STATE

`python -m src.cli run` supports two modes via `--real-agents`:

- **Stub mode (default)**: Local* agents in `src/main.py` — safe, no real API calls
- **Real mode (`--real-agents`)**: Real agent classes from `src/agents/*.py` with tool integrations

## BREAKPOINT 0 — Real agents not wired -> RESOLVED

File: `src/main.py`
Function: `_create_agents()`

**Fix applied**: Added `--real-agents` flag. When set, `_create_real_agents()` instantiates:
- ResearchAgent
- ContentGenerationAgent (with LLMTool)
- PublishingAgent (with CMSTool)
- AnalyticsAgent
- HealthMonitorAgent
- ErrorRecoveryAgent

Usage:
```bash
python -m src.cli run --dry-run --ticks 1 --real-agents
```

## BREAKPOINT 1 — Publishing does not publish -> RESOLVED

File: `src/agents/publishing_agent.py`
Function: `_push_to_cms()`

**Fix applied**: `_push_to_cms()` now uses CMSTool when `WP_STAGING_BASE_URL` and
`WP_STAGING_APP_PASSWORD` env vars are set. Falls back gracefully with a clear error
message when credentials are missing. Dry-run mode still returns a placeholder.

## BREAKPOINT 2 — Research has no SERP intel -> PARTIAL

File: `src/agents/research_agent.py`
Function: `_scan_serp()`
Live behavior: returns `[]`

**Status**: Keyword expansion and scoring work (heuristic-based). SERP scanning
requires a provider integration (SerpAPI / DataForSEO). This is P3 priority.

## BREAKPOINT 3 — Content drafts are placeholders -> RESOLVED

File: `src/agents/content_generation_agent.py`
Functions: `_generate_outline()`, `_generate_draft()`

**Fix applied**: Both methods now use LLMTool when:
1. Not in dry-run mode
2. `LLM_API_KEY` env var is set

LLM generates real outlines (JSON) and full article HTML with required OpenClaw
blocks: TLDR, comparison table, FAQ, verdict statements, FTC disclosure.
Falls back to template/placeholder when LLM is unavailable.

## BREAKPOINT 4 — Tool NotImplementedErrors -> MOSTLY RESOLVED

| Tool | Status | Notes |
|------|--------|-------|
| `llm_tool.py` | IMPLEMENTED | Anthropic + OpenAI with fallback |
| `cms_tool.py` | IMPLEMENTED | WordPress REST API (CRUD, media, categories, tags) |
| `analytics_tool.py` | STUB | Caching works; API queries return empty data |
| `seo_tool.py` | PARTIAL | keyword_density + schema_markup work; SERP is stub |
| `link_tool.py` | STUB | HTTP link validation not implemented |

## REMAINING WORK (by priority)

| Priority | Item | File | Fix needed |
|----------|------|------|------------|
| P1 | Analytics API integration | `analytics_tool.py` | GA4/GSC/affiliate pulls |
| P2 | SERP provider integration | `seo_tool.py` + `research_agent.py` | SerpAPI adapter |
| P2 | Link validator HTTP | `link_tool.py` | requests.head() check |
| P3 | Cluster mode Postgres | `data/db.py` | Postgres driver option |
