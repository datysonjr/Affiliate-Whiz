# RUNBOOK_STARTUP.md — Startup Procedure (Operator-Friendly)

## 1) Power + Network
- UPS on
- Router online
- Switch online
- Nodes booted in order

## 2) Validate Nodes
- Check IPs match reservation plan
- Confirm SSD mounts
- Confirm internet + DNS resolution

## 3) Start Services (Safe)
- Start DRY_RUN first
- Confirm logs writing and DB ok

## 4) Confirm Pipeline
- Run one sample job:
  - research -> content -> export artifacts
- Confirm outputs in /data/exports

## 5) Optional Staging Publish
- Only when staging credentials present and STAGING=true
- Publish 1 post to confirm connectivity
- Verify post renders correctly
