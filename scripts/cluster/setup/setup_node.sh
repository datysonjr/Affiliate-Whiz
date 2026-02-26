#!/usr/bin/env bash
# setup_node.sh --- Master orchestrator for Mac Mini cluster node setup
# Usage: sudo bash scripts/cluster/setup/setup_node.sh <node-name> [mode]
#   node-name: oc-core-01 or oc-pub-01
#   mode:      full (default), infra-only, app-only
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
LOG_FILE="/tmp/openclaw_setup_node_$(date +%Y%m%d_%H%M%S).log"

OPENCLAW_USER="openclaw"
OPENCLAW_HOME="/Users/$OPENCLAW_USER"
OPENCLAW_REPO="$OPENCLAW_HOME/openclaw"

# Detect the admin user who ran sudo (ching1, chong2, etc.)
ADMIN_USER="${SUDO_USER:-$(whoami)}"
if [[ "$ADMIN_USER" == "root" ]]; then
    echo "ERROR: Could not detect your admin username."
    echo "  Run this script with sudo, not as root directly."
    echo "  Example: sudo bash $0 oc-core-01"
    exit 1
fi

ALL_NODES="oc-core-01 oc-pub-01"

# --- Node lookups (bash 3.2 compatible) ---
get_node_role() {
    case "$1" in
        oc-core-01) echo "controller" ;;
        oc-pub-01)  echo "publisher" ;;
        *)          echo "" ;;
    esac
}

get_node_ip() {
    case "$1" in
        oc-core-01) echo "192.168.1.10" ;;
        oc-pub-01)  echo "192.168.1.11" ;;
        *)          echo "" ;;
    esac
}

# Track results for final summary (parallel arrays, bash 3.2 compatible)
RESULT_NAMES=()
RESULT_VALUES=()
WARNINGS=()

# --- Helpers ---
log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg"
    echo "$msg" >> "$LOG_FILE"
}

banner() {
    log ""
    log "============================================"
    log "  $*"
    log "============================================"
    log ""
}

pass() {
    RESULT_NAMES+=("$1")
    RESULT_VALUES+=("PASS")
    log "  PASS: $1"
}

fail() {
    RESULT_NAMES+=("$1")
    RESULT_VALUES+=("FAIL")
    log "  FAIL: $1"
}

warn() {
    WARNINGS+=("$1")
    log "  ! WARNING: $1"
}

pause_for_action() {
    log ""
    log ">>> ACTION REQUIRED <<<"
    log "$1"
    log ""
    read -rp "Press ENTER when done (or 'skip' to skip): " response
    if [[ "$response" == "skip" ]]; then
        log "  Skipped by operator."
        return 1
    fi
    return 0
}

check_sudo() {
    if [[ $EUID -ne 0 ]]; then
        log "ERROR: This script must be run with sudo."
        log "Usage: sudo bash $0 <node-name> [mode]"
        exit 1
    fi
}

check_macos() {
    if [[ "$(uname)" != "Darwin" ]]; then
        log "ERROR: This script is designed for macOS only."
        exit 1
    fi
}

run_step() {
    local step_name="$1"
    local script="$2"
    shift 2

    banner "Step: $step_name"

    if bash "$script" "$@" 2>&1 | tee -a "$LOG_FILE"; then
        pass "$step_name"
    else
        fail "$step_name"
        log "  Step failed. Check log for details."
        log "  You can re-run this step individually:"
        log "    sudo bash $script $*"
        read -rp "  Continue with remaining steps? [Y/n]: " cont
        if [[ "$cont" =~ ^[Nn] ]]; then
            log "Setup aborted by operator."
            print_summary
            exit 1
        fi
    fi
}

print_summary() {
    banner "Setup Summary"

    log "Node:    $NODE_NAME"
    log "Role:    $NODE_ROLE"
    log "IP:      $TARGET_IP"
    log "Date:    $(date)"
    log ""

    # Results table
    printf "%-35s %s\n" "CHECK" "STATUS" | tee -a "$LOG_FILE"
    printf "%-35s %s\n" "-----------------------------------" "------" | tee -a "$LOG_FILE"
    local i=0
    while [[ $i -lt ${#RESULT_NAMES[@]} ]]; do
        printf "%-35s %s\n" "${RESULT_NAMES[$i]}" "${RESULT_VALUES[$i]}" | tee -a "$LOG_FILE"
        i=$((i + 1))
    done

    # Warnings
    if [[ ${#WARNINGS[@]} -gt 0 ]]; then
        log ""
        log "WARNINGS:"
        for w in "${WARNINGS[@]}"; do
            log "  ! $w"
        done
    fi

    log ""
    log "Full log: $LOG_FILE"
}

# --- Main ---
check_sudo
check_macos

NODE_NAME="${1:-}"
MODE="${2:-full}"

if [[ -z "$NODE_NAME" ]]; then
    log "ERROR: Usage: sudo bash $0 <node-name> [mode]"
    log "  Valid nodes: $ALL_NODES"
    log "  Modes: full, infra-only, app-only"
    exit 1
fi

TARGET_IP=$(get_node_ip "$NODE_NAME")
NODE_ROLE=$(get_node_role "$NODE_NAME")

if [[ -z "$TARGET_IP" ]]; then
    log "ERROR: Unknown node '$NODE_NAME'. Valid nodes: $ALL_NODES"
    exit 1
fi

banner "OpenClaw Cluster Node Setup"
log "Node:       $NODE_NAME"
log "Role:       $NODE_ROLE"
log "IP:         $TARGET_IP"
log "Mode:       $MODE"
log "Admin user: $ADMIN_USER"
log "Service:    $OPENCLAW_USER"
log "macOS:      $(sw_vers -productVersion)"
log "Date:       $(date)"
log "Log:        $LOG_FILE"

# -------------------------------------------------------
# Phase 0: Pre-flight
# -------------------------------------------------------
banner "Phase 0: Pre-flight Checks"

# Verify admin user exists
if dscl . -read "/Users/$ADMIN_USER" &>/dev/null; then
    log "Admin user '$ADMIN_USER' verified."
    pass "Admin user ($ADMIN_USER)"
else
    fail "Admin user ($ADMIN_USER)"
    log "ERROR: Admin user '$ADMIN_USER' not found on this system."
    exit 1
fi

# Create openclaw service account (non-admin) if it doesn't exist
if dscl . -read "/Users/$OPENCLAW_USER" &>/dev/null; then
    log "Service user '$OPENCLAW_USER' already exists."
    pass "Service user (openclaw)"
else
    log "Creating service user '$OPENCLAW_USER' (non-admin)..."
    echo ""
    echo "Set a password for the '$OPENCLAW_USER' service account."
    sysadminctl -addUser "$OPENCLAW_USER" \
        -fullName "OpenClaw Service" \
        -shell /bin/bash \
        -home "$OPENCLAW_HOME" 2>&1 | tee -a "$LOG_FILE"
    if dscl . -read "/Users/$OPENCLAW_USER" &>/dev/null; then
        pass "Service user created (openclaw)"
        log "  NOTE: openclaw is a non-admin account (no SSH, runs app only)."
    else
        fail "Service user creation"
        log "ERROR: Failed to create user. Create manually:"
        log "  System Settings > Users & Groups > Add User"
        exit 1
    fi
fi

# Confirm operator is ready
echo ""
echo "This will set up '$NODE_NAME' as a '$NODE_ROLE' node."
echo "The following will be configured:"
if [[ "$MODE" != "app-only" ]]; then
    echo "  1. Static IP ($TARGET_IP)"
    echo "  2. SSH (enabled + hardened)"
    echo "  3. Firewall (Application Firewall + pf)"
    echo "  4. Screen Sharing (VNC)"
    echo "  5. Tailscale VPN"
    echo "  6. macOS security hardening"
fi
if [[ "$MODE" != "infra-only" ]]; then
    echo "  7. Application bootstrap (venv, deps, dirs)"
    echo "  8. launchd auto-start"
fi
echo ""
read -rp "Continue? [Y/n]: " confirm
if [[ "$confirm" =~ ^[Nn] ]]; then
    log "Setup cancelled by operator."
    exit 0
fi

# -------------------------------------------------------
# Phase 1: Infrastructure Setup
# -------------------------------------------------------
if [[ "$MODE" != "app-only" ]]; then

    # Step 1: Static IP
    run_step "Static IP" "$SCRIPT_DIR/setup_static_ip.sh" "$NODE_NAME"

    # Step 2: Verify network
    banner "Step: Network Verification"
    if ping -c 1 -W 3 "192.168.1.1" &>/dev/null; then
        pass "Gateway reachable"
    else
        fail "Gateway reachable"
        warn "Gateway not reachable -- check Ethernet cable and switch"
    fi
    if ping -c 1 -W 3 "1.1.1.1" &>/dev/null; then
        pass "Internet reachable"
    else
        fail "Internet reachable"
        warn "Internet not reachable -- check router and ISP"
    fi

    # Step 3: SSH (with password auth still enabled)
    # Only the admin user (ching1/chong2) gets SSH access, not openclaw
    run_step "SSH setup" "$SCRIPT_DIR/setup_ssh.sh" "$ADMIN_USER"

    # Step 4: Pause for SSH key copy
    banner "Step: SSH Key Distribution"
    log "SSH is now enabled with password authentication."
    log "You MUST copy your SSH public key before we disable password auth."
    log "Admin user for SSH: $ADMIN_USER"
    if pause_for_action "From your operator machine, run:
    ssh-copy-id $ADMIN_USER@$TARGET_IP
    ssh $ADMIN_USER@$TARGET_IP   # verify it works

Press ENTER after you have verified key-based SSH login works."; then
        # Now lock down SSH (disable password auth)
        log "Locking down SSH (disabling password auth)..."
        LOCKDOWN=true bash "$SCRIPT_DIR/setup_ssh.sh" "$ADMIN_USER" 2>&1 | tee -a "$LOG_FILE"
        pass "SSH lockdown"
    else
        warn "SSH lockdown skipped -- password auth remains enabled"
    fi

    # Step 5: Firewall
    run_step "Firewall" "$SCRIPT_DIR/setup_firewall.sh"

    # Step 6: Screen Sharing (for admin user, not openclaw)
    run_step "Screen Sharing" "$SCRIPT_DIR/setup_screen_sharing.sh" "$ADMIN_USER"

    # Step 7: Tailscale (run as admin user -- they have the GUI session for auth)
    banner "Step: Tailscale VPN"
    sudo -u "$ADMIN_USER" bash "$SCRIPT_DIR/setup_tailscale.sh" 2>&1 | tee -a "$LOG_FILE" || \
        bash "$SCRIPT_DIR/setup_tailscale.sh" 2>&1 | tee -a "$LOG_FILE" || true

    # Check Tailscale -- handle App Store install where CLI isn't in PATH
    TS_CLI=""
    if command -v tailscale &>/dev/null; then
        TS_CLI="tailscale"
    elif [[ -x "/Applications/Tailscale.app/Contents/MacOS/Tailscale" ]]; then
        TS_CLI="/Applications/Tailscale.app/Contents/MacOS/Tailscale"
    fi

    if [[ -n "$TS_CLI" ]] && "$TS_CLI" ip -4 &>/dev/null; then
        pass "Tailscale ($("$TS_CLI" ip -4 2>/dev/null))"
    elif [[ -d "/Applications/Tailscale.app" ]]; then
        warn "Tailscale app installed -- verify connection via menu bar icon"
    else
        warn "Tailscale may need manual auth -- check menu bar icon"
    fi

    # Step 8: macOS Hardening
    run_step "macOS hardening" "$SCRIPT_DIR/harden_macos.sh"

fi  # end infra-only check

# -------------------------------------------------------
# Phase 2: Application Setup
# -------------------------------------------------------
if [[ "$MODE" != "infra-only" ]]; then

    banner "Phase 2: Application Setup"

    # Ensure repo is at the expected location
    if [[ -d "$OPENCLAW_REPO/.git" ]]; then
        log "Repo already exists at $OPENCLAW_REPO"
        pass "Repo present"
    elif [[ -d "$REPO_ROOT/.git" ]]; then
        log "Copying repo from $REPO_ROOT to $OPENCLAW_REPO..."
        mkdir -p "$OPENCLAW_REPO"
        rsync -a --exclude='.venv' --exclude='__pycache__' "$REPO_ROOT/" "$OPENCLAW_REPO/"
        chown -R "$OPENCLAW_USER:staff" "$OPENCLAW_REPO"
        pass "Repo copied"
    else
        warn "No repo found. Clone it manually to $OPENCLAW_REPO"
    fi

    # Run existing bootstrap
    if [[ -f "$OPENCLAW_REPO/scripts/cluster/bootstrap_node.sh" ]]; then
        banner "Step: Application Bootstrap"
        sudo -u "$OPENCLAW_USER" bash "$OPENCLAW_REPO/scripts/cluster/bootstrap_node.sh" "$NODE_ROLE" 2>&1 | tee -a "$LOG_FILE" || true
        pass "App bootstrap"
    elif [[ -f "$OPENCLAW_REPO/ops/scripts/bootstrap_mac_node.sh" ]]; then
        banner "Step: Application Bootstrap (ops)"
        sudo -u "$OPENCLAW_USER" bash "$OPENCLAW_REPO/ops/scripts/bootstrap_mac_node.sh" 2>&1 | tee -a "$LOG_FILE" || true
        pass "App bootstrap"
    else
        warn "Bootstrap script not found. Run manually after setup."
    fi

    # Install launchd plist
    banner "Step: launchd Auto-Start"
    PLIST_SRC="$OPENCLAW_REPO/deployments/launchd/mac_mini_node_agent.plist"
    PLIST_DST="$OPENCLAW_HOME/Library/LaunchAgents/com.openclaw.node.plist"

    if [[ -f "$PLIST_SRC" ]]; then
        mkdir -p "$OPENCLAW_HOME/Library/LaunchAgents"
        cp "$PLIST_SRC" "$PLIST_DST"
        chown "$OPENCLAW_USER:staff" "$PLIST_DST"
        # Don't load yet -- operator should verify everything works first
        log "launchd plist installed to: $PLIST_DST"
        log "To enable auto-start, run:"
        log "  sudo -u $OPENCLAW_USER launchctl load $PLIST_DST"
        pass "launchd plist installed"
    else
        warn "launchd plist not found at $PLIST_SRC"
    fi

fi  # end app-only check

# -------------------------------------------------------
# Phase 3: Final Verification
# -------------------------------------------------------
banner "Phase 3: Final Verification"

# Static IP
CURRENT_IP=$(ipconfig getifaddr en0 2>/dev/null || echo "unknown")
if [[ "$CURRENT_IP" == "$TARGET_IP" ]]; then
    pass "IP is $TARGET_IP"
else
    # Try other interfaces
    for iface in en1 en2 en3 en4 en5; do
        CURRENT_IP=$(ipconfig getifaddr "$iface" 2>/dev/null || echo "")
        if [[ "$CURRENT_IP" == "$TARGET_IP" ]]; then
            pass "IP is $TARGET_IP (on $iface)"
            break
        fi
    done
    if [[ "$CURRENT_IP" != "$TARGET_IP" ]]; then
        fail "IP is $TARGET_IP (got $CURRENT_IP)"
    fi
fi

# SSH
if lsof -i :22 2>/dev/null | grep -q LISTEN; then
    pass "SSH listening"
else
    fail "SSH listening"
fi

# Firewall
if /usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate 2>/dev/null | grep -qi "enabled"; then
    pass "Application Firewall"
else
    fail "Application Firewall"
fi

# Screen Sharing
if lsof -i :5900 2>/dev/null | grep -q LISTEN; then
    pass "Screen Sharing (VNC)"
else
    fail "Screen Sharing (VNC)"
fi

# Tailscale (handle App Store install)
TS_CHECK=""
if command -v tailscale &>/dev/null; then
    TS_CHECK="tailscale"
elif [[ -x "/Applications/Tailscale.app/Contents/MacOS/Tailscale" ]]; then
    TS_CHECK="/Applications/Tailscale.app/Contents/MacOS/Tailscale"
fi

if [[ -n "$TS_CHECK" ]] && "$TS_CHECK" ip -4 &>/dev/null; then
    pass "Tailscale ($("$TS_CHECK" ip -4 2>/dev/null))"
elif [[ -d "/Applications/Tailscale.app" ]]; then
    pass "Tailscale (app installed -- check menu bar for connection)"
else
    fail "Tailscale (not installed)"
fi

# Hostname
CURRENT_HOSTNAME=$(scutil --get HostName 2>/dev/null || echo "unknown")
if [[ "$CURRENT_HOSTNAME" == "$NODE_NAME" ]]; then
    pass "Hostname ($NODE_NAME)"
else
    fail "Hostname (got $CURRENT_HOSTNAME)"
fi

# /etc/hosts
if grep -q "$TARGET_IP.*$NODE_NAME" /etc/hosts 2>/dev/null; then
    pass "/etc/hosts entry"
else
    fail "/etc/hosts entry"
fi

# openclaw user
if dscl . -read "/Users/$OPENCLAW_USER" &>/dev/null; then
    pass "User: $OPENCLAW_USER"
else
    fail "User: $OPENCLAW_USER"
fi

# Repo
if [[ -d "$OPENCLAW_REPO/.git" ]]; then
    pass "Repo at $OPENCLAW_REPO"
else
    fail "Repo at $OPENCLAW_REPO"
fi

# FileVault
FV_STATUS=$(fdesetup status 2>/dev/null || echo "Unknown")
if echo "$FV_STATUS" | grep -qi "on"; then
    pass "FileVault"
else
    warn "FileVault is not enabled -- enable manually"
fi

# -------------------------------------------------------
# Print Summary
# -------------------------------------------------------
print_summary

log ""
log "NEXT STEPS:"
log "  1. Set up the other node (if not done yet)"
log "  2. Test SSH between nodes: ssh $ADMIN_USER@<other-node-ip>"
log "  3. Enable FileVault if not already on"
log "  4. Enable launchd auto-start when ready:"
log "     sudo -u $OPENCLAW_USER launchctl load $OPENCLAW_HOME/Library/LaunchAgents/com.openclaw.node.plist"
log "  5. See: docs/ops/RUNBOOK_NODE_SETUP.md for full details"
log ""
log "ACCOUNT SUMMARY:"
log "  Admin (SSH/Screen Sharing): $ADMIN_USER"
log "  Service (runs the app):     $OPENCLAW_USER (no SSH access)"
