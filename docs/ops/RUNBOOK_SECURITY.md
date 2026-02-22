# RUNBOOK_SECURITY.md — Security & Credential Protocol

## Principles
- Least privilege
- Secrets never committed to git
- Audit trail for sensitive actions
- DRY_RUN is default

## Credential Storage
Approved:
- Environment variables injected at runtime
- Team password manager / secrets manager
- Local secrets file ignored by git

Not approved:
- plaintext in repo
- screenshots of keys in chat
- emailing secrets

## Access Structure
- Shared accounts only when necessary
- Per-person logins preferred
- Separate staging vs production credentials

## Audit Logging
Log events for:
- publishing actions
- domain/DNS changes
- new site creation
- credential rotation
Events must never print secrets.

## Key Rotation
- Rotate keys on suspicion
- Rotate on team changes
- Rotate on schedule (quarterly recommended)

## Incident Response
If suspected compromise:
1) Stop publishing workers
2) Rotate keys
3) Review audit log
4) Restore from known good backups
5) Document postmortem
