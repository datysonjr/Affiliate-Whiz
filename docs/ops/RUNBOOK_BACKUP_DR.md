# RUNBOOK_BACKUP_DR.md — Backups & Disaster Recovery

## What to Back Up
- Database (jobs, artifacts, site configs, metrics)
- Exported artifacts (/data/exports)
- Config files (excluding secrets)
- Logs (rotated)

## Backup Frequency
- Daily automated backup
- Before any production publish batch
- Before any migration

## Storage Targets
- Local SSD (primary)
- Secondary external or cloud storage (recommended)
- Ensure backups are encrypted at rest

## Restore Procedure (High Level)
1) Stop services/workers
2) Restore DB from latest clean snapshot
3) Restore /data/exports if needed
4) Start DRY_RUN and validate
5) Resume SAFE_STAGING then PRODUCTION (if approved)

## Testing DR
- Monthly: test restore on a fresh environment
- Verify integrity: run smoke tests + one pipeline run DRY_RUN
