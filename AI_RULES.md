# AI Rules

## Core Constraints

1. **No agent runs unsupervised** - All actions route through the orchestrator controller
2. **Dry-run by default** - New pipelines and agents start in dry-run mode until validated
3. **Rate limits are mandatory** - Every agent has configurable rate limits in `config/agents.yaml`
4. **Kill switch always available** - Controller can halt any agent or the entire system instantly
5. **Audit everything** - All decisions, actions, and outcomes are logged

## Content Rules

1. **No false claims** - Content must be fact-checkable; no fabricated reviews or testimonials
2. **FTC compliance** - All affiliate content must include proper disclosures
3. **No black-hat SEO** - No keyword stuffing, cloaking, hidden text, or link schemes
4. **Quality floor** - Content below quality threshold is blocked from publishing
5. **Duplicate check** - No publishing substantially duplicate content across sites

## Publishing Rules

1. **Cadence limits** - Respect per-site posting frequency limits in `config/sites.yaml`
2. **Domain reputation** - New domains start with conservative posting cadence
3. **No spam patterns** - Posting patterns must appear natural
4. **Image compliance** - Only use properly licensed or generated images
5. **Link validation** - All affiliate links must be verified before publishing

## Risk Management

1. **Blacklist enforcement** - Never promote blacklisted products, niches, or merchants
2. **Claim filtering** - Health, financial, and legal claims require extra review
3. **Revenue anomaly detection** - Alert on sudden revenue drops or spikes
4. **Network TOS compliance** - Respect each affiliate network's terms of service
5. **Rollback capability** - Any published content can be unpublished within minutes

## LLM Usage Rules

1. **Provider agnostic** - LLM calls go through `agents/tools/llm_tool.py` abstraction
2. **Cost tracking** - All LLM API calls are logged with token counts and costs
3. **Fallback chain** - If primary LLM fails, fall back to secondary provider
4. **Output validation** - All LLM outputs are validated before use
5. **No PII in prompts** - Never send personally identifiable information to LLM APIs

## Operational Rules

1. **Secrets in vault only** - No credentials in code, config files, or logs
2. **Key rotation schedule** - Rotate all API keys on a defined schedule
3. **Backup before destructive ops** - Always backup before delete/update operations
4. **Alerting required** - No pipeline runs without alerting configured
5. **Incident response** - Follow `docs/runbooks/incident_response.md` for all incidents
