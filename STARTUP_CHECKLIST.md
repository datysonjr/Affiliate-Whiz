# STARTUP_CHECKLIST.md — OpenClaw Affiliate Bot (Cluster + Daily Start)

## A) Before You Power Anything On (Physical)
- [ ] Confirm UPS is connected and charged
- [ ] Confirm switch is powered (UPS-backed)
- [ ] Confirm router/modem is UPS-backed (recommended)
- [ ] Confirm both Mac minis are plugged into UPS battery outlets (not surge-only)
- [ ] Confirm SSD docks are connected and mounted
- [ ] Confirm ethernet cables connected (router -> switch -> nodes)
- [ ] Confirm ventilation is unobstructed

## B) Boot Order (Standard)
1) [ ] UPS on
2) [ ] Router/modem on (wait for internet)
3) [ ] Switch on
4) [ ] Mac mini Node A boot
5) [ ] Mac mini Node B boot

## C) Network + Node Checks
- [ ] Confirm Node A has expected IP (static/reserved)
- [ ] Confirm Node B has expected IP (static/reserved)
- [ ] Confirm both can ping router/gateway
- [ ] Confirm both can resolve DNS
- [ ] Confirm both can reach GitHub (or repo host)
- [ ] Confirm SSD mount paths are correct (e.g., /Volumes/OpenClawData or /data)

## D) Services Start (Local / Cluster)
- [ ] Pull latest repo changes on both nodes
- [ ] Load environment variables (never from git)
- [ ] Start in DRY_RUN mode first
- [ ] Verify logs are writing
- [ ] Verify DB is reachable
- [ ] Verify scheduler runs and enqueues jobs
- [ ] Verify at least one agent completes a job

## E) Daily Health Checks (10 min)
- [ ] Disk space OK on SSD
- [ ] Queue not stuck (depth not growing forever)
- [ ] Last successful run within last 24h
- [ ] No repeated failures on publishing (even staging)
- [ ] Backups exist and are recent

## F) Safe Shutdown
- [ ] Stop workers gracefully
- [ ] Confirm DB closed cleanly
- [ ] Run backup_now script (if needed)
- [ ] Shut down Node B
- [ ] Shut down Node A
- [ ] Switch off (optional)
- [ ] Router off (optional)
- [ ] UPS remains on if you want brownout protection; otherwise safe power down

## G) Emergency Recovery (Power Loss)
- [ ] Restore power
- [ ] Boot in standard order
- [ ] Run health check command
- [ ] Start only DRY_RUN
- [ ] Inspect logs for DB corruption or partial jobs
- [ ] Run restore_from_backup if DB is corrupted
- [ ] Resume pipelines
