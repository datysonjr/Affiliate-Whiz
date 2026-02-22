# UPS Recovery Plan

## UPS Configuration

- **UPS Model**: (fill in)
- **Capacity**: (fill in)
- **Estimated Runtime**: (fill in for both Mac Minis)
- **Connected Devices**: oc-core-01, oc-pub-01, router, switch

## Power Failure Procedure

### Automatic (if UPS supports USB/network management)

1. UPS signals power failure to connected Macs
2. macOS initiates graceful shutdown after configured delay
3. On power restore, Macs auto-boot (if configured in System Preferences > Energy Saver)
4. OpenClaw services start via launchd agents

### Manual Recovery

1. Wait for stable power
2. Power on router and switch first
3. Wait 60 seconds for network to stabilize
4. Power on oc-core-01 (controller first)
5. Power on oc-pub-01
6. Verify services are running: `python src/cli.py health --all`
7. Check for any interrupted operations: `python src/cli.py check-integrity`

## macOS Auto-Start Configuration

Enable auto-restart after power failure:
```bash
sudo systemsetup -setrestartpowerfailure on
```

## launchd Service Recovery

Services managed by launchd will auto-start on boot.
See `deployments/launchd/mac_mini_node_agent.plist` for configuration.

## Post-Recovery Checklist

- [ ] Both nodes online and accessible via SSH
- [ ] Database integrity check passed
- [ ] All agents reporting healthy
- [ ] Queue processing resumed
- [ ] No stuck/partial operations
- [ ] Backup schedule on track
