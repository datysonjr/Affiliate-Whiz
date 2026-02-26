#!/usr/bin/env bash
# setup_firewall.sh --- Configure macOS Application Firewall and pf rules
# Usage: sudo bash scripts/cluster/setup/setup_firewall.sh
set -euo pipefail

LOG_FILE="/tmp/openclaw_setup_firewall_$(date +%Y%m%d_%H%M%S).log"
SOCKETFILTERFW="/usr/libexec/ApplicationFirewall/socketfilterfw"
PF_ANCHOR_FILE="/etc/pf.anchors/com.openclaw"
PF_CONF="/etc/pf.conf"
LAUNCHD_PLIST="/Library/LaunchDaemons/com.openclaw.pf.plist"

LAN_SUBNET="192.168.1.0/24"

# --- Helpers ---
log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg"
    echo "$msg" >> "$LOG_FILE"
}

check_sudo() {
    if [[ $EUID -ne 0 ]]; then
        log "ERROR: This script must be run with sudo."
        exit 1
    fi
}

check_macos() {
    if [[ "$(uname)" != "Darwin" ]]; then
        log "ERROR: This script is designed for macOS only."
        exit 1
    fi
}

# --- Main ---
check_sudo
check_macos

log "=== Firewall Setup ==="
log "macOS: $(sw_vers -productVersion)"

# -------------------------------------------------------
# Part 1: macOS Application Firewall (socketfilterfw)
# -------------------------------------------------------
log ""
log "--- Application Firewall ---"

# Enable global firewall
if "$SOCKETFILTERFW" --getglobalstate 2>/dev/null | grep -qi "enabled"; then
    log "Application Firewall already enabled."
else
    "$SOCKETFILTERFW" --setglobalstate on
    log "Application Firewall enabled."
fi

# Enable stealth mode (no response to probes/pings from unknown sources)
"$SOCKETFILTERFW" --setstealthmode on
log "Stealth mode enabled."

# Enable logging
"$SOCKETFILTERFW" --setloggingmode on
log "Firewall logging enabled."

# Allow signed apps automatically
"$SOCKETFILTERFW" --setallowsigned on
"$SOCKETFILTERFW" --setallowsignedapp on
log "Signed apps allowed automatically."

# -------------------------------------------------------
# Part 2: pf (Packet Filter) rules
# -------------------------------------------------------
log ""
log "--- Packet Filter (pf) ---"

# Create pf anchor file
log "Writing pf anchor to: $PF_ANCHOR_FILE"
cat > "$PF_ANCHOR_FILE" << 'PFRULES'
# OpenClaw Cluster Firewall Rules
# Managed by scripts/cluster/setup/setup_firewall.sh

# Allow all loopback traffic
pass quick on lo0 all

# Allow all established/related connections
pass in quick proto tcp from any to any flags A/A

# Allow SSH (port 22) from LAN and Tailscale
pass in quick proto tcp from 192.168.1.0/24 to any port 22
pass in quick proto tcp from 100.64.0.0/10 to any port 22

# Allow VNC/Screen Sharing (port 5900) from LAN and Tailscale
pass in quick proto tcp from 192.168.1.0/24 to any port 5900
pass in quick proto tcp from 100.64.0.0/10 to any port 5900

# Allow Tailscale WireGuard (UDP 41641)
pass in quick proto udp from any to any port 41641

# Allow all Tailscale tunnel interfaces (utun*)
pass quick on utun0 all
pass quick on utun1 all
pass quick on utun2 all
pass quick on utun3 all
pass quick on utun4 all
pass quick on utun5 all

# Allow all inter-node traffic on LAN
pass in quick proto tcp from 192.168.1.0/24 to any
pass in quick proto udp from 192.168.1.0/24 to any

# Allow ICMP from LAN (ping between nodes)
pass in quick proto icmp from 192.168.1.0/24 to any

# Allow mDNS/Bonjour from LAN
pass in quick proto udp from 192.168.1.0/24 to any port 5353

# Allow outbound traffic (no restrictions on outgoing)
pass out all

# Block everything else inbound and log it
block in log all
PFRULES
log "Anchor file written."

# Backup pf.conf if not already backed up today
if [[ ! -f "${PF_CONF}.bak.$(date +%Y%m%d)" ]]; then
    cp "$PF_CONF" "${PF_CONF}.bak.$(date +%Y%m%d)"
    log "Backed up pf.conf."
fi

# Add anchor reference to pf.conf if not present
if ! grep -q "com.openclaw" "$PF_CONF" 2>/dev/null; then
    log "Adding OpenClaw anchor to pf.conf..."
    # Insert anchor lines before any existing rules but after the default anchor
    cat >> "$PF_CONF" << 'PFANCHOR'

# OpenClaw cluster firewall rules
anchor "com.openclaw"
load anchor "com.openclaw" from "/etc/pf.anchors/com.openclaw"
PFANCHOR
    log "Anchor added to pf.conf."
else
    log "Anchor already present in pf.conf."
fi

# Test rules (parse only, don't load)
log "Testing pf rules (dry-run)..."
if pfctl -n -f "$PF_CONF" 2>/dev/null; then
    log "  pf rules are valid."
else
    log "  ERROR: pf rules failed validation!"
    log "  Check $PF_ANCHOR_FILE and $PF_CONF"
    exit 1
fi

# Load and enable pf
log "Loading pf rules..."
pfctl -f "$PF_CONF" 2>/dev/null || true
pfctl -e 2>/dev/null || true  # -e may fail if already enabled; that's fine
log "pf rules loaded and enabled."

# -------------------------------------------------------
# Part 3: Boot-time launchd plist for pf
# -------------------------------------------------------
log ""
log "--- Boot-time pf Loader ---"

if [[ -f "$LAUNCHD_PLIST" ]]; then
    log "Launchd plist already exists."
else
    log "Creating launchd plist for pf at boot..."
    cat > "$LAUNCHD_PLIST" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.openclaw.pf</string>
    <key>ProgramArguments</key>
    <array>
        <string>/sbin/pfctl</string>
        <string>-e</string>
        <string>-f</string>
        <string>/etc/pf.conf</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardErrorPath</key>
    <string>/tmp/openclaw_pf_err.log</string>
    <key>StandardOutPath</key>
    <string>/tmp/openclaw_pf_out.log</string>
</dict>
</plist>
PLIST
    chmod 644 "$LAUNCHD_PLIST"
    chown root:wheel "$LAUNCHD_PLIST"
    launchctl load -w "$LAUNCHD_PLIST" 2>/dev/null || true
    log "Launchd plist created and loaded."
fi

# -------------------------------------------------------
# Summary
# -------------------------------------------------------
log ""
log "=== Firewall Setup Complete ==="
log ""
log "Active pf rules:"
pfctl -sr 2>/dev/null | tee -a "$LOG_FILE"
log ""
log "Application Firewall state:"
"$SOCKETFILTERFW" --getglobalstate 2>/dev/null | tee -a "$LOG_FILE"
log ""
log "Log saved to: $LOG_FILE"
