# RUNBOOK_NODE_SETUP.md --- Fresh Mac Mini Setup for OpenClaw Cluster

## Overview

This runbook covers setting up a fresh Mac Mini as a cluster node for the OpenClaw affiliate system. It covers static IPs, SSH hardening, firewall, Screen Sharing, Tailscale VPN, and macOS security hardening.

**Automated path:** `sudo bash scripts/cluster/setup/setup_node.sh <node-name>`
**Manual path:** Follow each phase below step by step.

---

## Node Reference

| Node | Hostname | IP | Role |
|------|----------|-----|------|
| A | oc-core-01 | 192.168.1.10 | Controller (orchestrator, scheduler, DB, light worker) |
| B | oc-pub-01 | 192.168.1.11 | Publisher (heavy worker, publishing, analytics) |

---

## Prerequisites

- [ ] Mac Mini connected to power, Ethernet switch, and UPS
- [ ] macOS installed (Ventura 13.x / Sonoma 14.x / Sequoia 15.x)
- [ ] Initial macOS setup wizard completed (create a temporary admin user)
- [ ] Terminal.app granted Full Disk Access:
  - System Settings > Privacy & Security > Full Disk Access > add Terminal
- [ ] This repo available on the Mac (USB drive or temporary network download)
- [ ] Your SSH public key ready on your operator machine (`~/.ssh/id_ed25519.pub`)
- [ ] Tailscale account created at https://tailscale.com/

---

## Phase 0: Create the openclaw User

### Automated
The master script handles this. Or manually:

```bash
sudo sysadminctl -addUser openclaw -fullName "OpenClaw Service" -shell /bin/bash -home /Users/openclaw -admin
```

### Manual (GUI)
1. System Settings > Users & Groups
2. Click Add User
3. Name: **OpenClaw Service**, Account name: **openclaw**
4. Set a strong password (store in password manager)
5. Make the user an Administrator (needed for setup, can downgrade later)

### Verification
- [ ] `dscl . -read /Users/openclaw` succeeds
- [ ] `ls /Users/openclaw` shows home directory

---

## Phase 1: Static IP

### Automated
```bash
sudo bash scripts/cluster/setup/setup_static_ip.sh oc-core-01   # or oc-pub-01
```

### Manual (GUI)
1. System Settings > Network > Ethernet
2. Click Details
3. TCP/IP tab: Configure IPv4 = **Manually**
4. IP Address: **192.168.1.10** (or **.11** for oc-pub-01)
5. Subnet Mask: **255.255.255.0**
6. Router: **192.168.1.1**
7. DNS tab: Add **1.1.1.1** and **1.0.0.1**
8. Apply

### Manual (CLI)
```bash
# Detect your Ethernet interface name
networksetup -listallnetworkservices

# Set static IP (replace "Ethernet" with your interface name)
sudo networksetup -setmanual "Ethernet" 192.168.1.10 255.255.255.0 192.168.1.1
sudo networksetup -setdnsservers "Ethernet" 1.1.1.1 1.0.0.1

# Set hostname
sudo scutil --set HostName oc-core-01
sudo scutil --set LocalHostName oc-core-01
sudo scutil --set ComputerName oc-core-01

# Add both nodes to /etc/hosts
echo "192.168.1.10  oc-core-01" | sudo tee -a /etc/hosts
echo "192.168.1.11  oc-pub-01" | sudo tee -a /etc/hosts
```

### Verification
- [ ] `ping 192.168.1.1` -- gateway reachable
- [ ] `ping 1.1.1.1` -- internet reachable
- [ ] `nslookup github.com` -- DNS works
- [ ] `scutil --get HostName` -- shows correct hostname
- [ ] `networksetup -getinfo "Ethernet"` -- shows correct IP

---

## Phase 2: SSH Setup & Hardening

### Automated
```bash
# Step 1: Enable SSH with password auth (so you can copy keys)
sudo bash scripts/cluster/setup/setup_ssh.sh

# Step 2: Copy your SSH key from your operator machine
#   (run this on YOUR machine, not the Mac Mini)
ssh-copy-id openclaw@192.168.1.10

# Step 3: Verify key-based login works
ssh openclaw@192.168.1.10

# Step 4: Lock down -- disable password auth
sudo LOCKDOWN=true bash scripts/cluster/setup/setup_ssh.sh
```

### Manual
```bash
# Enable Remote Login
sudo systemsetup -setremotelogin on

# Backup sshd_config
sudo cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak

# Edit /etc/ssh/sshd_config -- set these values:
#   PermitRootLogin no
#   PasswordAuthentication no        # ONLY after copying keys!
#   KbdInteractiveAuthentication no
#   MaxAuthTries 3
#   MaxSessions 5
#   LoginGraceTime 30
#   AllowUsers openclaw
#   PubkeyAuthentication yes
#   X11Forwarding no
#   PermitEmptyPasswords no
#   ClientAliveInterval 300
#   ClientAliveCountMax 2

# Validate config
sudo sshd -t -f /etc/ssh/sshd_config

# Restart sshd
sudo launchctl stop com.openssh.sshd
sudo launchctl start com.openssh.sshd

# Set up SSH directory
sudo mkdir -p /Users/openclaw/.ssh
sudo chmod 700 /Users/openclaw/.ssh
sudo touch /Users/openclaw/.ssh/authorized_keys
sudo chmod 600 /Users/openclaw/.ssh/authorized_keys
sudo chown -R openclaw:staff /Users/openclaw/.ssh

# Generate node keypair
sudo -u openclaw ssh-keygen -t ed25519 -C "openclaw@oc-core-01" -f /Users/openclaw/.ssh/id_ed25519 -N ""
```

### Verification
- [ ] `ssh openclaw@192.168.1.10` -- key-based login works
- [ ] `ssh root@192.168.1.10` -- DENIED
- [ ] `grep PasswordAuthentication /etc/ssh/sshd_config` -- shows "no"
- [ ] `grep AllowUsers /etc/ssh/sshd_config` -- shows "openclaw"

---

## Phase 3: Firewall

### Automated
```bash
sudo bash scripts/cluster/setup/setup_firewall.sh
```

### What it configures

**Application Firewall:**
- Global firewall ON
- Stealth mode ON (no response to probes)
- Logging ON
- Signed apps allowed automatically

**Packet Filter (pf) rules** at `/etc/pf.anchors/com.openclaw`:
- Allow all loopback traffic
- Allow SSH (22) from LAN only (192.168.1.0/24)
- Allow VNC (5900) from LAN only
- Allow Tailscale WireGuard (UDP 41641)
- Allow all Tailscale tunnel interfaces
- Allow all inter-node LAN traffic
- Block everything else inbound

**Boot persistence:** Installs a launchd plist at `/Library/LaunchDaemons/com.openclaw.pf.plist` to reload pf rules on boot.

### Verification
- [ ] `/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate` -- enabled
- [ ] `sudo pfctl -sr` -- shows rules including "com.openclaw"
- [ ] From another machine on LAN: `ssh openclaw@192.168.1.10` -- works
- [ ] From outside LAN (without Tailscale): SSH should be refused

---

## Phase 4: Screen Sharing

### Automated
```bash
sudo bash scripts/cluster/setup/setup_screen_sharing.sh
```

### Manual (GUI)
1. System Settings > General > Sharing
2. Screen Sharing: **ON**
3. Allow access for: **Only These Users** > add **openclaw**

### Manual (CLI)
```bash
sudo /System/Library/CoreServices/RemoteManagement/ARDAgent.app/Contents/Resources/kickstart \
    -activate \
    -configure -access -on \
    -configure -allowAccessFor -specifiedUsers \
    -configure -users openclaw \
    -configure -privs -all \
    -restart -agent -console
```

### Verification
- [ ] From another Mac: Finder > Go > Connect to Server > `vnc://192.168.1.10`
- [ ] Prompted for username/password
- [ ] Can see and control the desktop

---

## Phase 5: Tailscale VPN

### Automated
```bash
bash scripts/cluster/setup/setup_tailscale.sh
```

### Manual
```bash
# Install via Homebrew
brew install --cask tailscale

# Or download from https://tailscale.com/download/mac

# Launch
open -a Tailscale

# Authenticate (follow browser prompt)
tailscale up --hostname=oc-core-01
```

### Post-Install (required manual steps)
1. A browser opens to https://login.tailscale.com/
2. Sign in with your Tailscale account
3. Authorize the node
4. Repeat for the second node
5. In Tailscale Admin Console (https://login.tailscale.com/admin/machines):
   - Verify both nodes appear
   - Both should show as "Connected"

### Verification
- [ ] `tailscale status` -- shows "Connected"
- [ ] `tailscale ip -4` -- shows a 100.x.x.x IP
- [ ] From remote machine on same Tailscale network: `ssh openclaw@<tailscale-ip>` -- works
- [ ] From remote machine: `vnc://<tailscale-ip>:5900` -- Screen Sharing works

---

## Phase 6: macOS Security Hardening

### Automated
```bash
sudo bash scripts/cluster/setup/harden_macos.sh
```

### What it configures
- Guest user disabled
- Guest folder access disabled (SMB and AFP)
- Auto-restart on power failure (critical for headless cluster)
- Auto-restart on system freeze
- Computer sleep set to Never (server mode)
- AirDrop disabled
- Bluetooth discoverability disabled
- Remote Apple Events disabled
- Secure keyboard entry in Terminal
- Automatic macOS updates enabled
- Password required immediately on wake
- Printer sharing disabled
- Login window shows username/password (not user list)

### Manual steps (required)
- [ ] **Enable FileVault:** System Settings > Privacy & Security > FileVault > Turn On
  - Save the recovery key in your password manager
- [ ] **Verify auto-updates:** System Settings > General > Software Update > Automatic Updates: all ON

### Verification
- [ ] `fdesetup status` -- "FileVault is On"
- [ ] `defaults read /Library/Preferences/com.apple.loginwindow GuestEnabled` -- 0
- [ ] `systemsetup -getrestartpowerfailure` -- "On"
- [ ] `systemsetup -getcomputersleep` -- "Never"

---

## Phase 7: Application Layer

### Automated
```bash
# Clone repo to openclaw's home
sudo -u openclaw git clone <repo-url> /Users/openclaw/openclaw

# Run app bootstrap
sudo -u openclaw bash /Users/openclaw/openclaw/scripts/cluster/bootstrap_node.sh controller  # or publisher
```

### Verification
- [ ] `/Users/openclaw/openclaw/.venv/bin/python --version` -- Python 3.x
- [ ] `/Users/openclaw/openclaw/.env` exists and is populated
- [ ] `cd /Users/openclaw/openclaw && .venv/bin/python -m src.cli health` -- passes

---

## Phase 8: launchd Auto-Start

```bash
# Copy plist
cp /Users/openclaw/openclaw/deployments/launchd/mac_mini_node_agent.plist \
   /Users/openclaw/Library/LaunchAgents/com.openclaw.node.plist

# Load (starts the service)
sudo -u openclaw launchctl load /Users/openclaw/Library/LaunchAgents/com.openclaw.node.plist

# Verify
launchctl list | grep com.openclaw
```

---

## Full Automated Setup (One Command)

```bash
sudo bash scripts/cluster/setup/setup_node.sh oc-core-01  # Node A
sudo bash scripts/cluster/setup/setup_node.sh oc-pub-01   # Node B
```

The script will pause at key points for manual actions (SSH key copy, Tailscale auth).

---

## Post-Setup Cross-Node Checklist

- [ ] From Node A: `ssh openclaw@oc-pub-01` -- works
- [ ] From Node B: `ssh openclaw@oc-core-01` -- works
- [ ] From remote machine (via Tailscale): `ssh openclaw@<ts-ip-node-a>` -- works
- [ ] From remote machine (via Tailscale): `vnc://<ts-ip-node-a>:5900` -- works
- [ ] Both nodes visible in Tailscale admin console
- [ ] Firewall enabled on both nodes
- [ ] FileVault enabled on both nodes
- [ ] `python -m src.cli health` passes on both nodes

### Copy SSH keys between nodes (for inter-node communication)
```bash
# From Node A, copy key to Node B
sudo -u openclaw ssh-copy-id openclaw@192.168.1.11

# From Node B, copy key to Node A
sudo -u openclaw ssh-copy-id openclaw@192.168.1.10

# Test bidirectional SSH
# On Node A:
ssh openclaw@oc-pub-01 hostname
# On Node B:
ssh openclaw@oc-core-01 hostname
```

---

## Troubleshooting

### SSH: "Permission denied (publickey)"
- Verify your public key is in `/Users/openclaw/.ssh/authorized_keys`
- Check permissions: `ls -la /Users/openclaw/.ssh/`
  - `.ssh/` should be `700`
  - `authorized_keys` should be `600`
  - Owner should be `openclaw:staff`
- Check sshd logs: `log show --predicate 'process == "sshd"' --last 5m`
- If locked out, use Screen Sharing to access the Mac and fix SSH config

### Static IP not taking effect
- Verify interface name: `networksetup -listallnetworkservices`
- Restart networking: `sudo ifconfig en0 down && sudo ifconfig en0 up`
- Check cable connection to switch

### Screen Sharing: "Connection refused"
- Verify service: `launchctl list | grep screensharing`
- Re-enable: `sudo launchctl load -w /System/Library/LaunchDaemons/com.apple.screensharing.plist`
- Check firewall allows port 5900

### Tailscale not connecting
- Verify app is running (check menu bar icon)
- Try: `tailscale up --reset`
- Check firewall allows UDP 41641
- Check Tailscale admin console for auth issues

### Node can't reach the other node
- Verify both nodes are on the same subnet: `ping 192.168.1.10` / `ping 192.168.1.11`
- Check `/etc/hosts` has entries for both nodes
- Check switch port LEDs are active

### pf blocking legitimate traffic
- View blocked packets: `sudo tcpdump -n -e -ttt -i pflog0`
- Temporarily disable pf: `sudo pfctl -d`
- Fix rules in `/etc/pf.anchors/com.openclaw`, then: `sudo pfctl -f /etc/pf.conf && sudo pfctl -e`

---

## References
- `config/cluster.yaml` -- Cluster node and network config
- `config/cluster/nodes.example.yaml` -- Node config template
- `config/cluster/network.example.yaml` -- Network config template
- `docs/ops/RUNBOOK_CLUSTER.md` -- Cluster operations runbook
- `docs/ops/RUNBOOK_DEPLOYMENT.md` -- Deployment procedures
- `docs/ops/RUNBOOK_SECURITY.md` -- Security policies
- `ops/infra/static_ip_plan.md` -- Static IP plan
- `STARTUP_CHECKLIST.md` -- Post-boot verification checklist
