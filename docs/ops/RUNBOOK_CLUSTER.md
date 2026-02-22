# RUNBOOK_CLUSTER.md — Two-Node Mac Mini Cluster

## Purpose
Standardize how we operate the OpenClaw affiliate bot on a dedicated 2-node cluster.

## Hardware
- Node A: Mac mini
- Node B: Mac mini
- SSD docks attached to each node
- Netgear 16-port gigabit switch (PoE)
- CyberPower CP1500AVRLCD3 UPS
- Spectrum router + dedicated 1Gbps internet

## Network Standards
- Prefer reserved DHCP or static IP for each node.
- Maintain a written map:
  - Node A: hostname, IP, role(s)
  - Node B: hostname, IP, role(s)
- Disable random MAC randomization for nodes if it affects reservations.

## Roles (Configurable)
Default:
- Node A: Scheduler + Orchestrator primary + publishing worker (staging/prod gate)
- Node B: Research + Content + Analytics workers

## Boot Order
Use STARTUP_CHECKLIST.md.

## Deploy (Cluster Mode)
1) Update repo on both nodes.
2) Load env vars securely.
3) Run compose:
   - `bash scripts/cluster/deploy_stack.sh`
4) Verify:
   - health checks pass
   - scheduler running
   - workers running on both nodes

## Health Verification
Minimum:
- Disk space > 20% free
- DB reachable
- Queue not stuck
- Logs writing
- Last successful job < 24h

## Scaling (Later)
To add a node:
- follow docs/ops/RUNBOOK_SCALE_NEW_NODE.md
- update config/cluster/nodes.yaml
- re-balance roles
