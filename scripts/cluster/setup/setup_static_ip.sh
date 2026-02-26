#!/usr/bin/env bash
# setup_static_ip.sh --- Configure static IP on a Mac Mini cluster node
# Usage: sudo bash scripts/cluster/setup/setup_static_ip.sh <node-name>
#   node-name: oc-core-01 or oc-pub-01
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
LOG_FILE="/tmp/openclaw_setup_static_ip_$(date +%Y%m%d_%H%M%S).log"

# --- Node IP Map ---
declare -A NODE_IPS=(
    ["oc-core-01"]="192.168.1.10"
    ["oc-pub-01"]="192.168.1.11"
)

GATEWAY="192.168.1.1"
SUBNET="255.255.255.0"
DNS_1="1.1.1.1"
DNS_2="1.0.0.1"

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

detect_ethernet_interface() {
    # Parse networksetup output to find the Ethernet hardware port name
    local iface=""
    while IFS= read -r line; do
        if echo "$line" | grep -qi "ethernet\|thunderbolt.*ethernet\|usb.*lan"; then
            iface="$line"
            break
        fi
    done < <(networksetup -listallnetworkservices 2>/dev/null | tail -n +2)

    if [[ -z "$iface" ]]; then
        # Fallback: look for any wired interface that isn't Wi-Fi or Bluetooth
        while IFS= read -r line; do
            if echo "$line" | grep -qiv "wi-fi\|bluetooth\|thunderbolt bridge\|vpn\|iphone"; then
                iface="$line"
                break
            fi
        done < <(networksetup -listallnetworkservices 2>/dev/null | tail -n +2)
    fi

    if [[ -z "$iface" ]]; then
        log "ERROR: Could not detect an Ethernet interface."
        log "Available interfaces:"
        networksetup -listallnetworkservices 2>/dev/null | tee -a "$LOG_FILE"
        exit 1
    fi

    echo "$iface"
}

# --- Main ---
check_sudo
check_macos

NODE_NAME="${1:-}"
if [[ -z "$NODE_NAME" ]]; then
    log "ERROR: Usage: sudo bash $0 <node-name>"
    log "  Valid nodes: ${!NODE_IPS[*]}"
    exit 1
fi

if [[ -z "${NODE_IPS[$NODE_NAME]+x}" ]]; then
    log "ERROR: Unknown node '$NODE_NAME'. Valid nodes: ${!NODE_IPS[*]}"
    exit 1
fi

TARGET_IP="${NODE_IPS[$NODE_NAME]}"

log "=== Static IP Setup ==="
log "Node:    $NODE_NAME"
log "IP:      $TARGET_IP"
log "Gateway: $GATEWAY"
log "Subnet:  $SUBNET"
log "DNS:     $DNS_1, $DNS_2"
log "macOS:   $(sw_vers -productVersion)"

# Detect Ethernet interface
IFACE=$(detect_ethernet_interface)
log "Detected interface: $IFACE"

# Check current IP
CURRENT_IP=$(networksetup -getinfo "$IFACE" 2>/dev/null | grep "^IP address" | awk '{print $NF}' || true)
if [[ "$CURRENT_IP" == "$TARGET_IP" ]]; then
    log "Static IP already set to $TARGET_IP. Skipping network config."
else
    log "Setting static IP on '$IFACE'..."
    networksetup -setmanual "$IFACE" "$TARGET_IP" "$SUBNET" "$GATEWAY"
    log "Static IP set."
fi

# Set DNS
log "Setting DNS servers..."
networksetup -setdnsservers "$IFACE" "$DNS_1" "$DNS_2"
log "DNS set."

# Set hostname
log "Setting hostname to $NODE_NAME..."
scutil --set HostName "$NODE_NAME"
scutil --set LocalHostName "$NODE_NAME"
scutil --set ComputerName "$NODE_NAME"
log "Hostname set."

# Update /etc/hosts
log "Updating /etc/hosts..."
for node in "${!NODE_IPS[@]}"; do
    ip="${NODE_IPS[$node]}"
    if ! grep -q "$ip.*$node" /etc/hosts 2>/dev/null; then
        echo "$ip  $node" >> /etc/hosts
        log "  Added: $ip  $node"
    else
        log "  Already present: $ip  $node"
    fi
done

# Verify connectivity
log "Verifying connectivity..."
if ping -c 1 -W 3 "$GATEWAY" &>/dev/null; then
    log "  Gateway ($GATEWAY): REACHABLE"
else
    log "  WARNING: Gateway ($GATEWAY) not reachable. Check cable and switch."
fi

if ping -c 1 -W 3 "$DNS_1" &>/dev/null; then
    log "  Internet ($DNS_1): REACHABLE"
else
    log "  WARNING: Internet ($DNS_1) not reachable. Check router/ISP."
fi

# Print final state
log ""
log "=== Current Network Info ==="
networksetup -getinfo "$IFACE" 2>/dev/null | tee -a "$LOG_FILE"

log ""
log "=== Static IP Setup Complete ==="
log "Log saved to: $LOG_FILE"
