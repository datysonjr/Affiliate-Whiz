#!/usr/bin/env bash
# setup_screen_sharing.sh --- Enable macOS Screen Sharing (VNC) for the cluster
# Usage: sudo bash scripts/cluster/setup/setup_screen_sharing.sh [user]
#   user: macOS user to grant access (default: openclaw)
set -euo pipefail

LOG_FILE="/tmp/openclaw_setup_screen_sharing_$(date +%Y%m%d_%H%M%S).log"
ALLOWED_USER="${1:-openclaw}"
KICKSTART="/System/Library/CoreServices/RemoteManagement/ARDAgent.app/Contents/Resources/kickstart"

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

log "=== Screen Sharing Setup ==="
log "macOS: $(sw_vers -productVersion)"
log "Allowed user: $ALLOWED_USER"

# Verify user exists
if ! dscl . -read "/Users/$ALLOWED_USER" &>/dev/null; then
    log "ERROR: User '$ALLOWED_USER' does not exist. Create the user first."
    exit 1
fi

# Enable Screen Sharing via ARD kickstart
log "Enabling Screen Sharing via ARD kickstart..."
if [[ -x "$KICKSTART" ]]; then
    "$KICKSTART" -activate \
        -configure -access -on \
        -configure -allowAccessFor -specifiedUsers \
        -configure -users "$ALLOWED_USER" \
        -configure -privs -all \
        -restart -agent -console 2>&1 | tee -a "$LOG_FILE"
    log "Screen Sharing enabled via kickstart."
else
    # Fallback: enable via launchctl
    log "kickstart not found, using launchctl fallback..."
    launchctl load -w /System/Library/LaunchDaemons/com.apple.screensharing.plist 2>/dev/null || true
    log "Screen Sharing enabled via launchctl."
    log "NOTE: Access restrictions could not be set via kickstart."
    log "  Manually restrict in System Settings > General > Sharing > Screen Sharing."
fi

# Verify service is running
sleep 2
if launchctl list 2>/dev/null | grep -q "com.apple.screensharing"; then
    log "Screen Sharing service is running."
else
    log "WARNING: Screen Sharing service may not be running."
    log "  Try: System Settings > General > Sharing > Screen Sharing: ON"
fi

# Verify VNC port is listening
if lsof -i :5900 2>/dev/null | grep -q LISTEN; then
    log "VNC is listening on port 5900."
else
    log "WARNING: VNC does not appear to be listening on port 5900."
    log "  It may take a moment to start, or may need a manual toggle."
fi

log ""
log "=== Screen Sharing Setup Complete ==="
log ""
log "To connect from another Mac:"
log "  1. Open Finder > Go > Connect to Server"
log "  2. Enter: vnc://$(scutil --get LocalHostName 2>/dev/null || hostname).local"
log "  3. Or use the IP: vnc://$(ipconfig getifaddr en0 2>/dev/null || echo '<this-node-ip>'):5900"
log "  4. Authenticate as: $ALLOWED_USER"
log ""
log "Log saved to: $LOG_FILE"
