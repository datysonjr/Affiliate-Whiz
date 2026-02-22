# RUNBOOK_GO_LIVE.md — OpenClaw Production Launch Procedure

This document defines the EXACT procedure for switching OpenClaw from SAFE_STAGING → PRODUCTION.

Never skip steps.

---

## Rule Zero

Production launch must ONLY happen after:

- multiple DRY_RUN successes
- multiple SAFE_STAGING publishes verified
- backups confirmed working
- staging posts visually verified

If any of those are false → do not launch.

---

## Step 1 — Verify cluster health

Confirm:

- both nodes reachable
- scheduler running
- database accessible
- disk free space > 20GB
- logs rotating correctly

If any check fails → stop.

---

## Step 2 — Backup everything

Run:

```
make backup
```

Confirm:

- DB copied
- config copied
- exports copied

If backup fails → stop.

---

## Step 3 — Verify production WordPress credentials

Confirm:

- WP_PROD_BASE_URL correct
- WP_PROD_USER correct
- WP_PROD_APP_PASSWORD valid
- test API auth manually

Do NOT assume staging credentials work.

---

## Step 4 — Production safety limits

Before flipping the switch:

Set:

```
OPENCLAW_MODE=PRODUCTION
ALLOW_PUBLISHING=true
STAGING_ONLY=false
```

BUT ALSO set:

```
MAX_TOTAL_POSTS_PER_DAY=3
MAX_SITES_TOUCHED_PER_DAY=1
```

Start extremely conservative.

---

## Step 5 — First production run

Run:

```
scripts/dev/run_local_staging.sh
```

BUT with PRODUCTION mode.

Observe:

- job queue activity
- publishing logs
- CMS responses

---

## Step 6 — Immediate verification

Within 5 minutes:

- open the site manually
- confirm post exists
- confirm formatting clean
- confirm disclosure block present
- confirm affiliate links present

---

## Step 7 — Search Console submission

After post verified:

- update sitemap
- request indexing

---

## Step 8 — Monitor first 24 hours

Watch:

- publishing logs
- CMS errors
- analytics ingestion
- affiliate link tracking

Do not increase volume for at least 72 hours.

---

## Golden rule

Production is not a moment.

Production is a slow ramp.

The system wins by consistency, not speed.
