#!/usr/bin/env bash
# setup_ssh.sh --- Enable and harden SSH on a Mac Mini cluster node
# Usage: sudo bash scripts/cluster/setup/setup_ssh.sh [allowed-users]
#   allowed-users: comma-separated list (default: detected from $SUDO_USER)
set -euo pipefail

LOG_FILE="/tmp/openclaw_setup_ssh_$(date +%Y%m%d_%H%M%S).log"
SSHD_CONFIG="/etc/ssh/sshd_config"
DEFAULT_USER="${SUDO_USER:-$(whoami)}"
ALLOWED_USERS="${1:-$DEFAULT_USER}"

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

set_sshd_option() {
    # Sets a key-value pair in sshd_config. Replaces existing (commented or not) or appends.
    local key="$1"
    local value="$2"

    if grep -qE "^#?\s*${key}\s" "$SSHD_CONFIG"; then
        # Replace existing line (commented or uncommented)
        sed -i.tmp "s|^#*\s*${key}\s.*|${key} ${value}|" "$SSHD_CONFIG"
        rm -f "${SSHD_CONFIG}.tmp"
    else
        # Append
        echo "${key} ${value}" >> "$SSHD_CONFIG"
    fi
    log "  Set: ${key} ${value}"
}

# --- Main ---
check_sudo
check_macos

log "=== SSH Setup & Hardening ==="
log "macOS: $(sw_vers -productVersion)"
log "Allowed users: $ALLOWED_USERS"

# Enable Remote Login
log "Enabling Remote Login (SSH)..."
if systemsetup -getremotelogin 2>/dev/null | grep -qi "on"; then
    log "  Remote Login already enabled."
else
    systemsetup -setremotelogin on 2>/dev/null || {
        # Fallback for newer macOS
        launchctl load -w /System/Library/LaunchDaemons/ssh.plist 2>/dev/null || true
    }
    log "  Remote Login enabled."
fi

# Backup sshd_config
BACKUP="${SSHD_CONFIG}.bak.$(date +%Y%m%d_%H%M%S)"
cp "$SSHD_CONFIG" "$BACKUP"
log "Backed up sshd_config to: $BACKUP"

# Apply hardening
log "Hardening sshd_config..."
set_sshd_option "PermitRootLogin" "no"
set_sshd_option "MaxAuthTries" "3"
set_sshd_option "MaxSessions" "5"
set_sshd_option "LoginGraceTime" "30"
set_sshd_option "PubkeyAuthentication" "yes"
set_sshd_option "AuthorizedKeysFile" ".ssh/authorized_keys"
set_sshd_option "X11Forwarding" "no"
set_sshd_option "PermitEmptyPasswords" "no"
set_sshd_option "ClientAliveInterval" "300"
set_sshd_option "ClientAliveCountMax" "2"
set_sshd_option "UsePAM" "yes"

# AllowUsers - replace commas with spaces for sshd format
ALLOW_LIST="${ALLOWED_USERS//,/ }"
set_sshd_option "AllowUsers" "$ALLOW_LIST"

# NOTE: We do NOT disable password auth yet. The master orchestrator (setup_node.sh)
# will call this script first with passwords enabled, pause for key copy, then
# call setup_ssh_lockdown.sh to disable password auth.
# However, if running standalone AND you've already copied your keys:
if [[ "${LOCKDOWN:-false}" == "true" ]]; then
    log "LOCKDOWN mode: Disabling password authentication..."
    set_sshd_option "PasswordAuthentication" "no"
    set_sshd_option "KbdInteractiveAuthentication" "no"
    set_sshd_option "ChallengeResponseAuthentication" "no"
else
    log "Password auth left ENABLED (run with LOCKDOWN=true after copying SSH keys)."
    log "  Or the master setup_node.sh will handle this automatically."
fi

# Validate config
log "Validating sshd_config..."
if sshd -t -f "$SSHD_CONFIG" 2>/dev/null; then
    log "  Config is valid."
else
    log "  ERROR: Invalid sshd_config! Restoring backup..."
    cp "$BACKUP" "$SSHD_CONFIG"
    log "  Restored from: $BACKUP"
    exit 1
fi

# Set up SSH directory for openclaw user
for user in $ALLOW_LIST; do
    USER_HOME=$(dscl . -read "/Users/$user" NFSHomeDirectory 2>/dev/null | awk '{print $2}' || true)
    if [[ -z "$USER_HOME" ]]; then
        log "  WARNING: User '$user' not found. Skipping .ssh setup."
        continue
    fi

    log "Setting up .ssh for user: $user ($USER_HOME)"
    mkdir -p "$USER_HOME/.ssh"
    chmod 700 "$USER_HOME/.ssh"
    touch "$USER_HOME/.ssh/authorized_keys"
    chmod 600 "$USER_HOME/.ssh/authorized_keys"
    chown -R "$user:staff" "$USER_HOME/.ssh"

    # Generate keypair if none exists
    if [[ ! -f "$USER_HOME/.ssh/id_ed25519" ]]; then
        log "  Generating ed25519 keypair for $user..."
        sudo -u "$user" ssh-keygen -t ed25519 -C "${user}@$(hostname)" \
            -f "$USER_HOME/.ssh/id_ed25519" -N "" 2>/dev/null
        log "  Keypair generated."
    else
        log "  Keypair already exists."
    fi
done

# Restart sshd
log "Restarting sshd..."
launchctl stop com.openssh.sshd 2>/dev/null || true
launchctl start com.openssh.sshd 2>/dev/null || true
log "sshd restarted."

# Verify
if lsof -i :22 2>/dev/null | grep -q LISTEN; then
    log "SSH is listening on port 22."
else
    log "WARNING: SSH does not appear to be listening on port 22."
fi

log ""
log "=== SSH Setup Complete ==="
log ""
log "SSH AllowUsers: $ALLOW_LIST"
log ""
log "NEXT STEPS:"
log "  1. From your operator machine, copy your SSH key:"
log "     ssh-copy-id $ALLOW_LIST@$(hostname -I 2>/dev/null | awk '{print $1}' || echo '<this-node-ip>')"
log "  2. Test key-based login:"
log "     ssh $ALLOW_LIST@<this-node-ip>"
log "  3. Then disable password auth:"
log "     sudo LOCKDOWN=true bash $0 $ALLOWED_USERS"
log ""
log "Log saved to: $LOG_FILE"
