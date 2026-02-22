# RUNBOOK_INCIDENTS.md — Incident Response

## Severity Levels
| Level | Description | Response Time |
|-------|-------------|---------------|
| P1 | System down, data loss risk | Immediate |
| P2 | Publishing failures, agent crashes | Within 1 hour |
| P3 | Performance degradation, warnings | Within 24 hours |
| P4 | Minor issues, cosmetic | Next maintenance window |

## Incident Response Steps
1) **Detect**: Health monitor alert or manual observation
2) **Assess**: Determine severity level
3) **Contain**: Stop affected services if needed
4) **Investigate**: Check logs, DB state, queue depth
5) **Fix**: Apply fix or rollback
6) **Verify**: Run health checks, confirm resolution
7) **Document**: Fill out postmortem template

## Common Incidents

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

## Postmortem
Use docs/templates/POSTMORTEM_TEMPLATE.md for all P1/P2 incidents.
