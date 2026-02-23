# IMPLEMENTATION_GAPS_AND_NEXT_STEPS.md

Purpose: Track what is stubbed vs implemented, and define the shortest path to a working system.

## Status Summary

The repo is architecturally complete, but several integrations were stubs. This document
tracks P0-P2 gaps and their resolution status.

## P0 — Required to run end-to-end (MVP)

### 1) LLMTool — IMPLEMENTED
Files:
- src/agents/tools/llm_tool.py

Completed:
- Anthropic primary provider (Messages API)
- OpenAI fallback provider (Chat Completions API)
- Lazy client initialization
- Retry with automatic fallback
- Token usage tracking
- generate(), generate_messages(), summarize(), classify(), extract()

Tests:
- tests/unit/test_tools.py (primary success, fallback on primary failure)

### 2) CMSTool (WordPress REST) — IMPLEMENTED
Files:
- src/agents/tools/cms_tool.py

Completed:
- Authenticated session (Basic Auth for WP, Bearer for others)
- _request() with retry + exponential backoff
- create_post(), update_post(), delete_post(), get_posts()
- upload_media() with Content-Type detection
- ensure_category(), ensure_tag() (get-or-create)
- Normalized response format

Tests:
- tests/unit/test_tools.py (mocked HTTP calls)

### 3) Publish Pipeline Wired — IMPLEMENTED
Files:
- src/pipelines/publishing/publish_post.py

Completed:
- _submit_to_cms() now uses CMSTool when credentials are configured
- Falls back to stub response for local dev / dry-run
- Validator -> Format -> CMSTool create_post() flow

### 4) SEO/keyword/SERP provider calls — STUB
Files:
- src/agents/tools/seo_tool.py

Missing:
- Provider integration (SerpAPI or similar)

MVP Output:
- keyword_density() is fully functional
- generate_schema_markup() is fully functional
- analyze_keywords() and check_serp() remain stubs

### 5) Analytics Tool — STUB
Files:
- src/agents/tools/analytics_tool.py

Missing:
- GA4/GSC/affiliate network revenue pull integrations

MVP Output:
- Caching and period parsing work
- API queries return empty data (safe for dry-run)

### 6) Rollback / Recovery — PLACEHOLDER
- error_recovery_agent.py mentions rollback "not yet implemented"
- Minimal safe revert: use CMSTool.update_post(status="draft") or delete_post()

## P1 — Makes it stable

- [x] GitHub Actions CI workflow (ruff, mypy, pytest)
- [ ] Cluster mode defaults to Postgres
- [ ] "Rollback Lite" for publishing mistakes (unpublish + revert edits)

## P2 — Makes it scale

- [ ] SERP snapshot caching (HTML + parsed)
- [ ] Cannibalization hard gate before drafting
- [ ] Per-site quotas enforced at DB level

## Definition of Done (MVP)

- `make bootstrap` runs locally
- `make dry-run` completes with no NotImplementedErrors
- `make staging` publishes a canary post to WP staging (when WP env vars set)
- Validator blocks bad drafts and reports failures
- CI passes on PRs
