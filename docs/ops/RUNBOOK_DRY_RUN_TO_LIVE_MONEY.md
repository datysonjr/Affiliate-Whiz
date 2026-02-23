# RUNBOOK_DRY_RUN_TO_LIVE_MONEY.md

Purpose: Define DRY_RUN vs STAGING vs LIVE and how to transition safely.

## Modes

### DRY_RUN
- Generates content
- Runs validator
- Does NOT publish
- Writes artifacts to tmp/ + logs/

### STAGING
- Publishes to staging WP site
- Status: draft/private
- Canary publish only
- Validates render + schema

### LIVE
- Publishes to live WP site
- Status: publish
- Must obey rate limits + kill switch thresholds

## Promotion Criteria (DRY_RUN → STAGING)

- No NotImplementedErrors
- 10 successful dry cycles
- Validator pass rate >= 80%
- Publishing pipeline passes unit tests

## Promotion Criteria (STAGING → LIVE)

- 10 successful staging publishes
- No schema failures
- No broken internal links on canary
- Manual review confirms disclosures + no risky claims

## Go-Live Safety Gates

- Canary first (1 post)
- Wait 60–120 minutes
- If clean, publish remaining daily quota
- If not, Safe Mode triggers

## Kill Switch

If any:
- publishing fails 3x consecutive
- API cost exceeds cap
- indexing stalls 48h (after initial ramp)

→ Safe Mode ON, publishing OFF, alert owners
