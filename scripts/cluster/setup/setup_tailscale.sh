#!/usr/bin/env bash
# setup_tailscale.sh --- Install and configure Tailscale VPN
# Usage: bash scripts/cluster/setup/setup_tailscale.sh
# NOTE: Does NOT require sudo (Homebrew path). Direct install may need sudo.
set -euo pipefail

LOG_FILE="/tmp/openclaw_setup_tailscale_$(date +%Y%m%d_%H%M%S).log"

# --- Helpers ---
log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg"
    echo "$msg" >> "$LOG_FILE"
}

check_macos() {
    if [[ "$(uname)" != "Darwin" ]]; then
        log "ERROR: This script is designed for macOS only."
        exit 1
    fi
}

# --- Main ---
check_macos

log "=== Tailscale VPN Setup ==="
log "macOS: $(sw_vers -productVersion)"

# Check if already installed
INSTALLED=false
if command -v tailscale &>/dev/null; then
    INSTALLED=true
    log "Tailscale CLI already available."
elif [[ -d "/Applications/Tailscale.app" ]]; then
    INSTALLED=true
    log "Tailscale.app already installed."
fi

if [[ "$INSTALLED" == "false" ]]; then
    log "Installing Tailscale..."

    if command -v brew &>/dev/null; then
        log "  Using Homebrew..."
        brew install --cask tailscale 2>&1 | tee -a "$LOG_FILE"
        log "  Installed via Homebrew."
    else
        log "  Homebrew not found. Downloading Tailscale directly..."
        log "  Please install Tailscale from: https://tailscale.com/download/mac"
        log ""
        log "  Options:"
        log "    a) Install Homebrew first: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
        log "    b) Download from Mac App Store: search 'Tailscale'"
        log "    c) Direct download: https://pkgs.tailscale.com/stable/#macos"
        log ""
        log "  After installing, re-run this script."
        exit 1
    fi
fi

# Launch Tailscale app
log "Launching Tailscale..."
open -a Tailscale 2>/dev/null || true
sleep 3

# Attempt to bring up Tailscale with the node's hostname
HOSTNAME=$(scutil --get HostName 2>/dev/null || hostname -s)
log "Setting Tailscale hostname to: $HOSTNAME"

if command -v tailscale &>/dev/null; then
    # Check if already connected
    if tailscale status &>/dev/null; then
        TS_STATUS=$(tailscale status --json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('BackendState',''))" 2>/dev/null || echo "unknown")
        if [[ "$TS_STATUS" == "Running" ]]; then
            log "Tailscale is already connected."
            TS_IP=$(tailscale ip -4 2>/dev/null || echo "unknown")
            log "Tailscale IP: $TS_IP"
        else
            log "Tailscale backend state: $TS_STATUS"
            log "Bringing up Tailscale..."
            tailscale up --hostname="$HOSTNAME" 2>&1 | tee -a "$LOG_FILE" || true
        fi
    else
        log "Bringing up Tailscale..."
        tailscale up --hostname="$HOSTNAME" 2>&1 | tee -a "$LOG_FILE" || true
    fi
else
    log "Tailscale CLI not yet available (app may still be starting)."
    log "The CLI becomes available after the app launches for the first time."
fi

log ""
log "=========================================="
log "  ACTION REQUIRED: Tailscale Authentication"
log "=========================================="
log ""
log "  1. A browser window should open (or check the Tailscale menu bar icon)"
log "  2. Sign in at https://login.tailscale.com/"
log "  3. Authorize this node ('$HOSTNAME')"
log "  4. Verify with: tailscale status"
log ""
log "  After both nodes are connected, you can:"
log "    - SSH from anywhere: ssh openclaw@<tailscale-ip>"
log "    - Screen Share from anywhere: vnc://<tailscale-ip>:5900"
log ""
log "  Tailscale Admin Console: https://login.tailscale.com/admin/machines"
log ""

# Wait for connection (with timeout)
log "Waiting for Tailscale to connect (up to 60s)..."
for i in {1..12}; do
    if command -v tailscale &>/dev/null && tailscale status &>/dev/null; then
        TS_IP=$(tailscale ip -4 2>/dev/null || echo "")
        if [[ -n "$TS_IP" ]]; then
            log "Tailscale connected!"
            log "  Tailscale IP: $TS_IP"
            log "  Hostname: $HOSTNAME"
            break
        fi
    fi
    if [[ $i -eq 12 ]]; then
        log "Tailscale not yet connected. Complete auth manually (see instructions above)."
    fi
    sleep 5
done

log ""
log "=== Tailscale Setup Complete ==="
log "Log saved to: $LOG_FILE"
