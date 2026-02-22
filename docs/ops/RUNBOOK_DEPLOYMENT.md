# RUNBOOK_DEPLOYMENT.md — Deploying Updates

## Pre-Deploy Checklist
- [ ] All tests passing locally
- [ ] Changes reviewed (PR or peer review)
- [ ] Backup taken before deploy
- [ ] DRY_RUN verified on staging

## Deploy Steps (Local Dev)
1) Pull latest from repo
2) Install/update dependencies: `pip install -r requirements.txt`
3) Run migrations: `python -m src.cli init`
4) Run DRY_RUN smoke test: `python -m src.cli run --dry-run --ticks 1`
5) Verify health: `python -m src.cli health`

## Deploy Steps (Cluster)
1) SSH into each node
2) Pull latest on each node
3) Restart services: `bash scripts/cluster/deploy_stack.sh`
4) Verify health on both nodes
5) Monitor logs for 15 minutes

## Rollback
1) Stop services
2) Revert to previous git tag/commit
3) Restore DB from backup if schema changed
4) Restart services in DRY_RUN
5) Validate before resuming production
