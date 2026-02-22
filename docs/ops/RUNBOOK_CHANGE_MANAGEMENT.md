# RUNBOOK_CHANGE_MANAGEMENT.md

OpenClaw Affiliate Automation System

Purpose: Defines how configuration, infrastructure, and automation changes are proposed, reviewed, approved, deployed, and rolled back safely.

This prevents:

- accidental traffic loss
- broken publishing pipelines
- runaway spending
- SEO damage
- affiliate tracking failures

OpenClaw MUST NEVER deploy uncontrolled configuration changes.

---

## Core Principle

Automation systems fail NOT because of bugs...

They fail because of: **untracked config changes made too fast.**

Every production change must be:

```
Proposed → Reviewed → Tested → Approved → Deployed → Verified
```

No shortcuts.

---

## Change Types

All changes fall into one of these categories.

### LOW RISK CHANGES

Examples:

- adjusting article schedule
- adding internal links
- changing site metadata
- minor YAML config edits
- increasing job frequency slightly

Approval:

- 1 team member review required

### MEDIUM RISK CHANGES

Examples:

- new domain deployment
- changing WordPress plugin set
- modifying article template structure
- increasing publishing volume significantly
- adding new affiliate network
- changing queue worker counts

Approval:

- 2 team member signoff required

### HIGH RISK CHANGES

Examples:

- DNS migration
- hosting provider change
- database schema change
- switching SEO plugin
- changing LLM provider / model
- changing scheduler logic
- bulk content regeneration

Approval:

- FULL TEAM consensus required

---

## Change Request Process

Every change must follow:

### Step 1 — Create Change Proposal

Create file:

```
docs/changes/YYYY-MM-DD-change-name.md
```

Include:

- What is changing?
- Why?
- Expected impact?
- Rollback method?
- Risk level?

### Step 2 — Assign Risk Level

Mark:

```
LOW
MEDIUM
HIGH
```

### Step 3 — Test in SAFE_STAGING

MANDATORY:

- test config locally OR staging site
- confirm OpenClaw completes at least:
  - 1 research job
  - 1 generation job
  - 1 publish job (draft only)

If any fail → change rejected.

### Step 4 — Approval

```
LOW    → 1 approval
MEDIUM → 2 approvals
HIGH   → unanimous
```

### Step 5 — Production Deployment Window

Always deploy during:

```
LOW TRAFFIC PERIOD
```

Never deploy:

- during heavy publishing
- during indexing spikes
- during affiliate payout periods

### Step 6 — Post-Deployment Verification

After deployment check:

- scheduler running
- queue depth normal
- WordPress publishing OK
- sitemap updates
- affiliate links resolving

If ANY issue:

**ROLL BACK IMMEDIATELY.**

---

## Rollback Policy

Every change must have:

**ONE COMMAND ROLLBACK**

Example:

```bash
git revert <commit>
# restore previous config
# restart services
```

If rollback takes longer than 10 minutes → change was unsafe.

---

## Safe Change Frequency Rule

Never deploy:

- more than ONE medium/high change per day
- more than THREE config changes per week

Too many changes = impossible debugging.

---

## Config Versioning Rule

ALL config files must:

- live in GitHub
- be versioned
- never edited only on live server

**Direct server edits are forbidden.**

---

## Emergency Change Exception

Allowed only if:

- publishing pipeline fully stopped
- affiliate links broken
- hosting outage
- data corruption

Even then:

- commit change AFTER emergency fix
- document incident immediately

---

## Final Rule

Untracked changes are the #1 reason automation revenue collapses.

If a change is not documented...

**It did not happen.**
