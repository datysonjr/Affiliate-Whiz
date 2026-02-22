# ADR 0001: Technology Stack

## Status
Accepted

## Context
We need to choose a technology stack for the OpenClaw affiliate marketing automation system. The system must support multi-agent orchestration, content generation, web publishing, and analytics across a small cluster of Mac Mini nodes.

## Decision

### Language: Python 3.11+
- Rich ecosystem for web scraping, ML/AI, and automation
- Strong async support for concurrent agent execution
- Team familiarity

### Database: SQLite (initial) → PostgreSQL (scale)
- SQLite for single-node simplicity during development
- Migration path to PostgreSQL when multi-node DB access is needed

### Queue: File-based (initial) → Redis (scale)
- Start simple with file-based queues
- Migrate to Redis when inter-node communication is needed

### LLM: Provider-agnostic via abstraction layer
- `agents/tools/llm_tool.py` wraps all LLM calls
- Support multiple providers without code changes
- Configure primary and fallback providers in `config/providers.yaml`

### CMS: WordPress (primary), Headless (future)
- WordPress has the largest ecosystem for affiliate sites
- Headless CMS option for performance-focused sites

### Hosting: Cloudflare Pages / Vercel
- Edge deployment for fast page loads
- Free tier covers initial scale

## Consequences
- Python performance is adequate for our workload (I/O bound, not compute bound)
- SQLite limits us to single-writer but simplifies deployment
- WordPress requires PHP hosting but provides rich plugin ecosystem
