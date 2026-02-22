# Router & Switch Notes

## Network Topology

```
[ISP Modem] → [Router] → [Switch] → [Mac Mini #1: oc-core-01]
                                   → [Mac Mini #2: oc-pub-01]
```

## Router Configuration

- **Router Model**: (fill in)
- **Admin URL**: http://192.168.1.1
- **DHCP Range**: 192.168.1.100 - 192.168.1.254
- **DNS**: Cloudflare (1.1.1.1, 1.0.0.1)

## Static IP Assignments

See `static_ip_plan.md` for IP assignments.

## Port Forwarding

| Port | Protocol | Destination | Purpose |
|------|----------|-------------|---------|
| (configure as needed) | | | |

## Notes

- Keep router firmware updated
- Change default admin password
- Disable UPnP for security
- Enable SPI firewall
