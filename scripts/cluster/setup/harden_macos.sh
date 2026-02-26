#!/usr/bin/env bash
# harden_macos.sh --- Apply macOS security hardening for cluster nodes
# Usage: sudo bash scripts/cluster/setup/harden_macos.sh
set -euo pipefail

LOG_FILE="/tmp/openclaw_setup_harden_$(date +%Y%m%d_%H%M%S).log"

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

apply_setting() {
    local description="$1"
    shift
    log "  Applying: $description"
    if "$@" 2>/dev/null; then
        log "    OK"
    else
        log "    WARNING: Command failed (may not apply on this macOS version)"
    fi
}

# --- Main ---
check_sudo
check_macos

log "=== macOS Security Hardening ==="
log "macOS: $(sw_vers -productVersion)"
log "Build:  $(sw_vers -buildVersion)"
log "Date:   $(date)"

# -------------------------------------------------------
# 1. User Account Hardening
# -------------------------------------------------------
log ""
log "--- User Account Hardening ---"

apply_setting "Disable Guest User" \
    defaults write /Library/Preferences/com.apple.loginwindow GuestEnabled -bool false

apply_setting "Disable Guest access to shared folders (SMB)" \
    defaults write /Library/Preferences/SystemConfiguration/com.apple.smb.server AllowGuestAccess -bool false

apply_setting "Disable Guest access to shared folders (AFP)" \
    defaults write /Library/Preferences/com.apple.AppleFileServer guestAccess -bool false

apply_setting "Show login window as username/password fields (not user list)" \
    defaults write /Library/Preferences/com.apple.loginwindow SHOWFULLNAME -bool true

# -------------------------------------------------------
# 2. Power & Recovery (critical for headless cluster)
# -------------------------------------------------------
log ""
log "--- Power & Recovery ---"

apply_setting "Auto-restart after power failure" \
    systemsetup -setrestartpowerfailure on

apply_setting "Auto-restart after system freeze" \
    systemsetup -setrestartfreeze on

apply_setting "Set computer sleep to Never (server mode)" \
    systemsetup -setcomputersleep Never

apply_setting "Set display sleep to 15 minutes" \
    systemsetup -setdisplaysleep 15

apply_setting "Disable wake for network access" \
    systemsetup -setwakeonnetworkaccess on

# -------------------------------------------------------
# 3. Network Hardening
# -------------------------------------------------------
log ""
log "--- Network Hardening ---"

apply_setting "Disable AirDrop" \
    defaults write com.apple.NetworkBrowser DisableAirDrop -bool true

apply_setting "Disable Bluetooth discoverability" \
    defaults write /Library/Preferences/com.apple.Bluetooth DiscoverableState -bool false

apply_setting "Disable Remote Apple Events" \
    systemsetup -setremoteappleevents off

apply_setting "Disable Bonjour multicast advertising" \
    defaults write /Library/Preferences/com.apple.mDNSResponder.plist NoMulticastAdvertisements -bool true

# -------------------------------------------------------
# 4. Security Features
# -------------------------------------------------------
log ""
log "--- Security Features ---"

apply_setting "Enable Secure Keyboard Entry in Terminal" \
    defaults write com.apple.Terminal SecureKeyboardEntry -bool true

apply_setting "Require password immediately after sleep/screensaver" \
    defaults write com.apple.screensaver askForPassword -int 1

apply_setting "No delay for password prompt" \
    defaults write com.apple.screensaver askForPasswordDelay -int 0

apply_setting "Enable automatic macOS updates" \
    defaults write /Library/Preferences/com.apple.SoftwareUpdate AutomaticCheckEnabled -bool true

apply_setting "Enable automatic download of updates" \
    defaults write /Library/Preferences/com.apple.SoftwareUpdate AutomaticDownload -bool true

apply_setting "Enable critical security updates" \
    defaults write /Library/Preferences/com.apple.SoftwareUpdate CriticalUpdateInstall -bool true

apply_setting "Enable app auto-updates from App Store" \
    defaults write /Library/Preferences/com.apple.commerce AutoUpdate -bool true

# -------------------------------------------------------
# 5. FileVault Check (cannot enable automatically)
# -------------------------------------------------------
log ""
log "--- FileVault Status ---"

FV_STATUS=$(fdesetup status 2>/dev/null || echo "Unknown")
log "  FileVault: $FV_STATUS"

if echo "$FV_STATUS" | grep -qi "off\|not supported"; then
    log ""
    log "  *** ACTION REQUIRED: Enable FileVault manually ***"
    log "  System Settings > Privacy & Security > FileVault > Turn On"
    log "  Save the recovery key in your team password manager."
fi

# -------------------------------------------------------
# 6. Disable unnecessary services
# -------------------------------------------------------
log ""
log "--- Disable Unnecessary Services ---"

# Disable Printer Sharing
apply_setting "Disable Printer Sharing" \
    cupsctl --no-share-printers

# Disable Internet Sharing (if enabled)
if defaults read /Library/Preferences/SystemConfiguration/com.apple.nat NAT 2>/dev/null | grep -q "Enabled = 1"; then
    apply_setting "Disable Internet Sharing" \
        defaults write /Library/Preferences/SystemConfiguration/com.apple.nat NAT -dict Enabled -int 0
else
    log "  Internet Sharing already disabled."
fi

# -------------------------------------------------------
# Summary
# -------------------------------------------------------
log ""
log "=== macOS Hardening Complete ==="
log ""
log "Applied:"
log "  [x] Guest user disabled"
log "  [x] Guest folder access disabled"
log "  [x] Auto-restart on power failure"
log "  [x] Auto-restart on freeze"
log "  [x] Computer sleep disabled (server mode)"
log "  [x] AirDrop disabled"
log "  [x] Bluetooth discoverability disabled"
log "  [x] Remote Apple Events disabled"
log "  [x] Secure keyboard entry enabled"
log "  [x] Automatic updates enabled"
log "  [x] Password required on wake"
log "  [x] Printer sharing disabled"
log ""
log "Manual steps remaining:"
if echo "$FV_STATUS" | grep -qi "off"; then
    log "  [ ] Enable FileVault (System Settings > Privacy & Security)"
fi
log "  [ ] Verify auto-updates in System Settings > General > Software Update"
log ""
log "Log saved to: $LOG_FILE"
