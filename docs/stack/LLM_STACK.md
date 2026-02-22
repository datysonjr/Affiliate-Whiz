# LLM_STACK.md — Models & LLM integration options (OpenClaw)

## Purpose
OpenClaw needs language models for:
- niche/keyword analysis summaries (research)
- article outlines + drafts + SEO metadata
- rewrite/refresh of existing posts
- generation of structured JSON artifacts

We keep LLM access behind an interface so we can switch providers later.

---

## Recommended Approach
Use a "provider abstraction" with:
- `LLM_PROVIDER` env var (openai | anthropic | local)
- `LLM_MODEL_DEFAULT` and optional per-task overrides

---

## Provider Options

### Option A: Cloud LLM (fastest, best quality early)
Pros:
- higher quality content
- better reasoning for niche mapping and intent
- easy to scale

Cons:
- monthly cost can grow with volume
- requires good governance (caps and budgets)

Programmatic features:
- standard REST APIs
- streaming responses
- rate limits, usage tracking

When to use:
- v1/v2 for quality and speed

---

### Option B: Local LLM (cost control later)
Pros:
- predictable costs
- no per-token billing
- can run offline

Cons:
- quality may be lower depending on model
- heavier compute requirements

Programmatic features:
- local HTTP server (varies by runtime)
- can be swapped behind same LLM interface

When to use:
- once you have stable pipelines and want to reduce costs

---

## Model Role Mapping (Recommended)
Use different "roles" even if same model:
- `research`: niche briefs, keyword clustering rationale
- `writer`: longform drafts + structure
- `seo_editor`: titles/meta/slug, internal linking suggestions
- `rewriter`: refresh + improve underperformers

---

## Cost Control Rules (Must)
- enforce max articles/day
- enforce max tokens/article
- DRY_RUN default
- store cached outputs keyed by prompt hash (avoid re-paying)

---

## Hardware Notes
LLM usage affects Node B more (content-heavy).
- Node B does most generation
- Node A keeps orchestration stable

If you go local LLM later:
- local inference should run on Node B
- keep Node A as control plane
