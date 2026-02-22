# Static IP Plan

## Internal Network

| IP Address | Hostname | Role | Notes |
|-----------|----------|------|-------|
| 192.168.1.10 | oc-core-01 | Controller + Content | Mac Mini #1 |
| 192.168.1.11 | oc-pub-01 | Publishing + Monitoring | Mac Mini #2 |
| 192.168.1.1 | router | Network gateway | |
| 192.168.1.2 | switch | Network switch | (if managed) |

## DNS Records (Internal)

Add to `/etc/hosts` on each node:

```
192.168.1.10  oc-core-01
192.168.1.11  oc-pub-01
```

## Network Configuration

### oc-core-01
- IP: 192.168.1.10
- Subnet: 255.255.255.0
- Gateway: 192.168.1.1
- DNS: 1.1.1.1, 1.0.0.1

### oc-pub-01
- IP: 192.168.1.11
- Subnet: 255.255.255.0
- Gateway: 192.168.1.1
- DNS: 1.1.1.1, 1.0.0.1
