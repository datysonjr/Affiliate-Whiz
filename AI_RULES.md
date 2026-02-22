# AI_RULES.md — OpenClaw Affiliate Marketing Automation Bot (Friend Group)

## Purpose
This repository powers an OpenClaw-driven automation system that builds and maintains SEO-optimized niche content sites to earn affiliate revenue.

This project is owned/operated by a friend group:
- Corey
- DA / Don Anthony
- Fern
- David
- Jamie

## Non-Negotiables (Hard Rules)
1. **Project Scope**
   - This repo is ONLY for the affiliate marketing automation bot and its cluster.
   - Do not reference any other projects, brands, or businesses.

2. **Compliance & Ethics**
   - No cloaking, no misleading claims, no fake reviews, no scraped copyrighted content.
   - Always include proper affiliate disclosures.
   - Follow platform policies (affiliate networks, WordPress hosts, analytics tools).
   - Prefer white-hat SEO techniques: strong content, internal linking, topical authority, technical SEO.

3. **Security**
   - Secrets never committed to git.
   - All credentials stored in an approved secrets manager or environment variables.
   - Least-privilege access for all accounts.
   - Audit logging required for any actions affecting domains/sites/publishing.

4. **Operational Reliability**
   - DRY_RUN mode must exist and be the default.
   - Every pipeline step must be resumable (idempotent).
   - Fail safely: if uncertain, halt and alert.

5. **System Design**
   - Modular agents with clear interfaces.
   - Queue-based execution (even if local queue starts simple).
   - Observable: structured logs + metrics + health checks.
   - Replaceable components: queue, DB, CMS integration, analytics.

## Definitions
- **Cluster**: Two Mac minis connected via gigabit switch and UPS, on dedicated Spectrum router/internet.
- **Node**: A machine in the cluster (Mac mini A, Mac mini B).
- **Agent**: A discrete worker that performs a job (research, content, publishing, analytics, etc.).
- **Pipeline**: A series of jobs that produce an outcome (site creation, article publishing, link updates).

## Modes
- **DRY_RUN (default)**: Generates artifacts locally; never publishes externally.
- **SAFE_STAGING**: Can publish to a staging WordPress site only.
- **PRODUCTION**: Publishing enabled for production sites only when explicitly approved.

## Quality Bar
Content must be:
- Helpful and original
- Clear about sources and uncertainty
- Structured for readability (headings, bullets, tables)
- Not stuffed with keywords
- Not auto-generated fluff

## "Do Not Do"
- Do not use black-hat SEO tactics.
- Do not create deceptive landing pages.
- Do not impersonate brands or medical/legal professionals.
- Do not bypass affiliate network rules.
- Do not automate account creation in a way that violates Terms.

## Change Management
- Any config changes to domains/sites/credentials require:
  - a PR or review step (even if informal)
  - a changelog entry
  - a rollback plan
