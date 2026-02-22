# OPENCLAW_KILL_SWITCH_AND_SAFE_MODE.md

OpenClaw Affiliate Automation System

Purpose: Defines emergency controls for instantly halting automation, preventing catastrophic publishing events, and safely recovering system stability.

This file protects:

- site reputation
- SEO authority
- affiliate tracking integrity
- hosting stability
- database consistency

Every team member must understand this document.

---

## Core Principle

Automation is powerful.

But uncontrolled automation is dangerous.

The system must always default to:

```
SAFE BY DEFAULT
```

Publishing is a privilege, not a baseline.

---

## The Global Kill Switch

### Definition

A single configuration flag that immediately halts all external actions.

### Required Environment Variable

```
OPENCLAW_MODE=SAFE
```

When SAFE:

- publishing agent disabled
- scheduler stops new content jobs
- refresh engine paused
- topic discovery paused
- queue accepts NO new tasks

Monitoring remains active.

---

## Safe Mode States

OpenClaw must support these modes:

### DRY_RUN (Default)

Behavior:

- content generation allowed
- publishing disabled
- affiliate links simulated
- logs recorded

This is the safest operating mode.

Used for:

- development
- staging tests
- debugging pipelines

### SAFE_STAGING

Behavior:

- publishing allowed ONLY as drafts
- sitemap NOT updated
- indexing signals suppressed

Used for:

- pipeline testing
- CMS validation
- content QA

### LIMITED_PRODUCTION

Behavior:

- publishing allowed with strict caps
- daily article limits enforced
- refresh engine restricted

Used for:

- early site launch
- cautious scaling phase

### FULL_PRODUCTION

Behavior:

- normal automation active
- publishing unrestricted (within configured caps)

Only allowed once system proven stable.

---

## Emergency Stop Conditions

If ANY occur:

**System must auto-switch to SAFE immediately.**

### Trigger 1 — Publish Failure Spike

If:

```
>5 publish failures in 10 minutes
```

Switch SAFE.

### Trigger 2 — Infinite Retry Loop

If:

- same job retried repeatedly
- queue depth increasing rapidly

Switch SAFE.

### Trigger 3 — Credential Failure

If:

- CMS authentication fails repeatedly
- API tokens rejected continuously

Switch SAFE.

### Trigger 4 — Abnormal Publishing Burst

If:

- articles published faster than allowed schedule
- scheduler misfires repeatedly

Switch SAFE.

### Trigger 5 — Database Write Errors

If:

- repeated DB write failures
- corrupted queue state

Switch SAFE.

---

## Manual Emergency Stop

Any operator must be able to stop system in <10 seconds.

Required command:

```bash
export OPENCLAW_MODE=SAFE
```

Restart workers afterward.

---

## Mass-Publish Prevention System

OpenClaw must enforce:

### Hard Daily Publish Cap

Example:

```
MAX_POSTS_PER_DAY=5
```

Even if scheduler bugged, system MUST NOT exceed this.

### Job Cooldown Timer

Between publishes:

```
minimum delay required
```

Prevents rapid bursts.

### Queue Sanity Check

Before publishing:

System must verify:

- job count reasonable
- timestamps valid
- content validated

If anomaly: **reject job.**

---

## Safe Recovery Procedure

If SAFE triggered:

### Step 1 — Freeze External Actions

Confirm:

- publishing disabled
- scheduler paused

### Step 2 — Identify Root Cause

Check:

1. scheduler logs
2. publishing logs
3. CMS responses
4. DB state

Never restart blindly.

### Step 3 — Fix Issue

Common fixes:

- rotate credentials
- clear stuck queue
- restore config file
- restart container

### Step 4 — Resume in SAFE_STAGING

Never jump straight back to production.

Test:

- create one draft post
- verify CMS accepts it
- verify logs stable

### Step 5 — Resume LIMITED_PRODUCTION

Only after staging passes.

---

## Config Lockdown Rule

Critical config files must NEVER change live.

Required:

- Git version control
- change review process
- rollback capability

If config modified manually on server:

**system integrity compromised.**

---

## Human Error Prevention Rules

The biggest risks are not technical.

They are:

- wrong environment variable
- wrong site credentials
- scheduler misconfigured
- accidentally enabling production

Therefore:

Production mode must require:

```
CONFIRM_PRODUCTION=true
```

Without this flag: **production cannot activate.**

---

## Final Safety Law

If something looks wrong:

**STOP AUTOMATION FIRST.**

Diagnose second.

Automation can destroy months of SEO trust in minutes.

Stopping early always saves more than continuing blindly.
