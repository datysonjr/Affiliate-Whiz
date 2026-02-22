# POLICY_DATA_RETENTION.md

## Data Categories and Retention

| Data Type | Retention Period | Storage | Notes |
|-----------|-----------------|---------|-------|
| Agent run logs | 90 days | SQLite / logs/ | Rotate after period |
| Exported artifacts | 1 year | /data/exports | Archive to external storage |
| Database backups | 30 days | SSD / external | Keep last 30 daily snapshots |
| Analytics snapshots | 1 year | SQLite | Aggregate after 90 days |
| Audit logs | 1 year | logs/ | Required for compliance |
| Temporary files | 7 days | tmp/ | Auto-cleanup |

## Deletion Policy
- Data past retention period should be archived or deleted
- Deletion of production data requires team approval
- Backups of deleted data kept for 30 additional days

## Privacy
- No personal user data collected (we are the only users)
- External API keys rotated on schedule (see RUNBOOK_ACCOUNTS_KEYS.md)
