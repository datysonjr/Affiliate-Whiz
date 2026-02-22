# OPENCLAW_DEPLOYMENT_DAY_PLAYBOOK.md

OpenClaw Affiliate Automation System

Purpose: Defines the exact step-by-step procedure for the FIRST production deployment of OpenClaw.

This playbook prevents:

- accidental mass publishing
- broken CMS connections
- indexing damage
- invalid affiliate links
- runaway schedulers
- unsafe environment activation

This document MUST be followed sequentially.

Do not skip steps.

---

## Deployment Philosophy

Production launch is NOT: turning the system on.

Production launch is: **progressively allowing the system to prove stability.**

OpenClaw must earn production privileges in stages.

---

## STAGE 0 — HARDWARE & NETWORK CONFIRMATION

Before touching software:

Confirm:

- all nodes powered and stable
- switch connections verified
- router stable and internet confirmed
- UPS functioning and connected
- system clocks synchronized

If hardware unstable: **STOP.**

Never deploy on unstable infrastructure.

---

## STAGE 1 — REPO & CONFIG VALIDATION

Clone repo onto primary node.

Confirm:

- config directory present
- `.env` variables defined
- secrets stored securely
- site configs correct
- schedule configs reasonable

Verify:

```
OPENCLAW_MODE=DRY_RUN
```

Must be DRY_RUN at this stage.

**Never deploy directly in production mode.**

---

## STAGE 2 — LOCAL PIPELINE TEST

Run system locally in DRY_RUN.

Verify:

- topic discovery executes
- content generation completes
- internal linking logic executes
- queue processing stable
- logs recording correctly

No CMS calls allowed yet.

If any job fails: **FIX BEFORE CONTINUING.**

---

## STAGE 3 — CMS CONNECTION TEST (SAFE_STAGING)

Switch:

```
OPENCLAW_MODE=SAFE_STAGING
```

Now test CMS connection.

Required tests:

1. create test draft post
2. upload test image
3. assign category
4. confirm metadata stored

**DO NOT publish publicly.**

If CMS rejects requests: **FIX BEFORE CONTINUING.**

---

## STAGE 4 — FIRST REAL CONTENT GENERATION

Generate ONE real article.

Do NOT auto-publish yet.

Manually inspect:

- structure correct
- affiliate links valid
- internal links reasonable
- FAQ present
- comparison table present

If quality issues: fix template before proceeding.

---

## STAGE 5 — FIRST SAFE DRAFT PUBLISH

Publish ONE article as draft only.

Verify:

- draft visible in CMS
- formatting intact
- links functional
- images render correctly

If anything broken: **STOP and repair pipeline.**

---

## STAGE 6 — INDEXING PREPARATION

Before publishing public content:

Confirm:

- sitemap exists and accessible
- robots.txt correct
- site loads fast
- SSL valid
- domain resolves globally

If sitemap missing: **DO NOT publish.**

---

## STAGE 7 — LIMITED_PRODUCTION ACTIVATION

Switch:

```
OPENCLAW_MODE=LIMITED_PRODUCTION
```

Set:

```
MAX_POSTS_PER_DAY=1
```

Yes — ONE.

The first week is about stability, not volume.

---

## STAGE 8 — FIRST LIVE ARTICLE

Publish exactly ONE live article.

Then: **WAIT 24 HOURS.**

Do nothing else.

Observe:

- site uptime
- CMS stability
- indexing activity
- search console signals

**Never publish multiple articles on first day.**

---

## STAGE 9 — WEEK 1 STABILITY MODE

For first 7 days:

- max 1 article/day
- refresh engine disabled
- topic discovery limited
- monitoring active daily

Goal: **prove system stability.** Not traffic.

---

## STAGE 10 — WEEK 2 CONTROLLED EXPANSION

If week 1 stable:

Increase to:

```
2–3 articles per week
```

Still conservative.

Continue observing:

- crawl frequency
- indexing speed
- impression signals

---

## STAGE 11 — FIRST SCALE CHECKPOINT

After 30 days:

Evaluate:

- indexed page %
- impressions trend
- ranking movement
- affiliate click signals

Consult:

```
RUNBOOK_SCALE_TRIGGER.md
```

Only scale if signals positive.

---

## NEVER DO THESE ON DEPLOYMENT DAY

Never:

- publish 10+ articles immediately
- deploy multiple sites simultaneously
- enable full automation immediately
- skip staging mode
- ignore early failures

**These destroy new sites.**

---

## Deployment Success Checklist

Deployment considered successful only if:

- CMS publishing stable
- queue stable
- logs stable
- sitemap functioning
- indexing observed
- no scheduler runaway behavior

If any fail: **deployment incomplete.**

---

## Final Law of OpenClaw Deployment

The system should feel:

```
slow → controlled → boring → stable
```

If launch feels fast or chaotic, **you are doing it wrong.**

Slow launches build permanent authority.
