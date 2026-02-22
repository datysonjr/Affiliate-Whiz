# RUNBOOK_INCIDENTS.md

OpenClaw Affiliate Automation System

Purpose: Defines how to detect, classify, diagnose, and resolve operational incidents.

Incidents include:

- publishing failures
- WordPress API errors
- indexing collapse
- affiliate revenue drops
- traffic disappearance
- job queue failures
- database errors

Goal:

- FAST diagnosis
- SAFE recovery
- NO panic decisions

---

## Incident Response Philosophy

Rule:

**Stop automation first. Diagnose second.**

Never try to "fix live chaos."

---

## Incident Severity Levels

### LEVEL 1 — MINOR

Examples:

- single post failed
- temporary API timeout
- one site slow

Action:

Log + monitor only.

### LEVEL 2 — MODERATE

Examples:

- multiple publish failures
- scheduler stuck
- queue backlog rising
- WordPress authentication failing

Action:

Pause publishing. Diagnose within 1 hour.

### LEVEL 3 — CRITICAL

Examples:

- ALL publishing failing
- indexing collapse across sites
- traffic suddenly drops 70%+
- affiliate links broken
- database corruption
- automation running infinite loops

Action:

**IMMEDIATE FULL STOP.**

Switch:

```
OPENCLAW_MODE=DRY_RUN
```

---

## Incident Response Workflow

### STEP 1 — FREEZE AUTOMATION

Immediately:

```
disable publishing agent
disable scheduler
leave monitoring active
```

Never diagnose while jobs are still running.

### STEP 2 — IDENTIFY FAILURE DOMAIN

Determine if issue is:

```
CONTENT
PUBLISHING
HOSTING
INDEXING
AFFILIATE TRACKING
NETWORK
DATABASE
```

### STEP 3 — CHECK LOGS IN THIS ORDER

1. Scheduler logs
2. Queue logs
3. Publishing logs
4. WordPress response logs
5. DB logs

Always check in this order.

### STEP 4 — APPLY DOMAIN-SPECIFIC FIX

See common incident playbooks below.

---

## Common Incident Playbooks

### Publishing Fails

Check:

- WordPress credentials
- REST API reachable
- hosting disk full?
- plugin conflict?
- SSL expired?

Fix:

- regenerate WP app password
- retry single post manually

### Indexing Collapse

Check:

- sitemap still accessible
- robots.txt blocking?
- recent plugin change?
- sudden massive post spike?

Fix:

- slow publishing rate immediately
- verify sitemap URL manually
- submit sitemap again

**Never mass-delete pages.**

### Traffic Sudden Drop

Check:

- hosting downtime?
- domain expired?
- analytics tracking removed?
- page accidentally noindexed?

Fix:

- verify domain DNS
- verify analytics code present
- check search console messages

### Affiliate Revenue Drop

Check:

- affiliate links still redirect?
- tracking parameters stripped?
- program account still active?

Fix:

- manually click test links
- verify conversion tracking

### Infinite Job Loop

Symptoms:

- queue growing endlessly
- CPU high
- repeated generation logs

Fix:

Immediately:

```
kill worker processes
switch to DRY_RUN
inspect retry logic
```

### Agent Crash Loop

- Check logs for stack trace
- Disable agent: `python -m src.cli kill-switch on`
- Fix root cause
- Re-enable and test in DRY_RUN

### Database Corruption

- Stop all services
- Restore from latest backup
- Run integrity check: `python -m src.cli health`
- Resume in DRY_RUN

### Disk Full

- Check disk usage on SSD mounts
- Rotate/delete old logs: `bash scripts/cluster/rotate_logs.sh`
- Archive old exports
- Resume services

### Network Outage

- Verify ISP connectivity
- Check router/switch status
- Confirm DNS resolution
- Services should auto-resume when network returns

---

## Post-Incident Rules

After recovery, create:

```
docs/incidents/YYYY-MM-DD-incident.md
```

Include:

- what happened
- root cause
- fix applied
- prevention step

Use `docs/templates/POSTMORTEM_TEMPLATE.md` for all Level 2/3 incidents.

---

## Golden Incident Rule

If you cannot explain the root cause...

**DO NOT restart full automation.**

You will recreate the same failure.
