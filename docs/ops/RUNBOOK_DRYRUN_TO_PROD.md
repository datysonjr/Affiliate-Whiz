# RUNBOOK_DRYRUN_TO_PROD.md — From DRY_RUN to Live Money-Making

## Why DRY_RUN exists
DRY_RUN is a safety mode where OpenClaw:
- runs the full pipeline (research → content → publishing steps)
- **never posts publicly**
- writes all outputs to local storage
- logs every decision and action
- allows repeatable testing without damaging domains, accounts, or reputation

DRY_RUN prevents:
- accidental spam/policy violations
- content quality disasters
- broken publishing loops
- irreversible site changes
- wasted time debugging in production

---

## What DRY_RUN should produce (minimum)
Each run should output artifacts to `/data/exports/<timestamp>/`:

1) `niche_brief.json`
   - niche description
   - keyword clusters
   - intent categories
   - competitor scan notes
   - risks + compliance notes

2) `content_brief.json`
   - target keyword
   - article type (review/comparison/roundup/how-to)
   - outline
   - internal link targets

3) `draft.md`
   - full article draft
   - headings, bullets, tables if relevant
   - affiliate disclosure block placeholder

4) `seo_meta.json`
   - title
   - meta description
   - slug
   - tags/categories suggestions
   - schema suggestions (Article/FAQ if appropriate)

5) `publish_plan.json`
   - which site (staging/prod target)
   - status target (draft)
   - publish date/time suggestion

DRY_RUN is "done" when artifacts are consistent, readable, and repeatable.

---

## Stages of going live (the safe ladder)

### Stage 0 — Local DRY_RUN only
**Goal:** pipeline works on a laptop with no external dependencies.
- No WordPress required
- No domains required
- No affiliate accounts required
- Outputs must be stable

✅ Exit criteria:
- 3 consecutive DRY_RUN executions complete with no errors
- artifacts look human-usable and non-spammy
- logs + DB state look correct

---

### Stage 1 — SAFE_STAGING (Publishing to a staging site)
**Goal:** prove your publishing integration works safely.
- You must have a *staging* WordPress site
- Posts must publish as **DRAFT** by default
- No indexing required
- You're testing connectivity + formatting

✅ Required gates:
- `OPENCLAW_MODE=SAFE_STAGING`
- `ALLOW_PUBLISHING=true`
- staging credentials only
- max 1–2 posts/day during testing

✅ Exit criteria:
- WordPress posting works repeatedly
- media uploads (optional) work
- categories/tags assigned correctly
- drafts render cleanly on site
- internal links don't break layout

---

### Stage 2 — Controlled Production (1 site, low volume)
**Goal:** launch the first real site with strict limits.
- 1 domain
- 1 site
- 1 niche
- 2–3 posts/week max initially
- all posts still start as draft unless explicitly "promoted"

✅ Required gates:
- affiliate disclosure page live
- privacy/contact/about pages live
- sitemap enabled
- caching/optimization enabled
- no policy-sensitive claims

✅ Exit criteria (2–4 weeks):
- indexing confirmed
- no Search Console errors that matter
- content cadence stable
- early clicks/impressions appear

---

### Stage 3 — Expand topic clusters (topical authority)
**Goal:** build depth in the niche instead of spraying new sites.
- add supporting articles around the same cluster
- improve internal linking
- update older posts ("last updated")
- add comparison and roundup "money pages"

✅ Exit criteria:
- 1+ pages begin ranking meaningfully
- internal linking improves crawl + time on site
- affiliate clicks appear

---

### Stage 4 — Scale to multiple sites (only after winners)
**Goal:** repeat what works.
- only clone proven structures
- avoid launching multiple niches at once
- add a new site only when the first has signal

✅ Exit criteria:
- predictable weekly output
- reliable backup/restore
- stable publishing + health monitoring

---

## How "live money-making" actually happens
This system makes money when:
- content ranks for buyer-intent terms
- content earns clicks to affiliate offers
- offers convert

So "going live" is not flipping a switch. It's building a repeatable engine:
- quality content
- stable publishing
- authority building
- continuous improvements

---

## The three biggest failure modes (avoid these)
1) **Publishing too much too fast**
   - gets you ignored, deindexed, or flagged
2) **Low-quality or duplicate content**
   - won't rank; wastes time and domain trust
3) **No measurement loop**
   - you won't know what to scale or kill

---

## Production Controls (recommended defaults)
- Post as draft first, promote intentionally
- Max posts/day across all sites: 10
- Max new sites/week: 1–2
- Backups nightly + before major changes
- Weekly review every Monday:
  - top pages
  - indexing errors
  - performance trends
  - next-week content plan

---

## "Go Live" Checklist (minimum)
Before PRODUCTION:
- [ ] disclosures in place
- [ ] staging tested successfully
- [ ] backups confirmed and restore tested
- [ ] audit logging enabled
- [ ] publishing caps configured
- [ ] 3 successful SAFE_STAGING runs
- [ ] 1 controlled production batch (draft-only) successful

Only then:
- set `OPENCLAW_MODE=PRODUCTION`
- set `ALLOW_PUBLISHING=true`
- set `STAGING_ONLY=false`
