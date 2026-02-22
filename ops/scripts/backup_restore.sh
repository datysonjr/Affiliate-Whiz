#!/usr/bin/env bash
set -euo pipefail

# Backup and restore script for OpenClaw
# Usage:
#   bash ops/scripts/backup_restore.sh backup
#   bash ops/scripts/backup_restore.sh restore --latest
#   bash ops/scripts/backup_restore.sh restore --file <backup_file>

BACKUP_DIR="${BACKUP_DIR:-backups}"
DATA_DIR="${DATA_DIR:-data}"
CONFIG_DIR="${CONFIG_DIR:-config}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

backup() {
    echo "=== OpenClaw Backup ==="
    echo "Timestamp: $TIMESTAMP"

    BACKUP_FILE="$BACKUP_DIR/openclaw_backup_$TIMESTAMP.tar.gz"

    # Create backup
    tar -czf "$BACKUP_FILE" \
        "$DATA_DIR/" \
        "$CONFIG_DIR/" \
        2>/dev/null || true

    echo "Backup created: $BACKUP_FILE"
    echo "Size: $(du -h "$BACKUP_FILE" | cut -f1)"

    # Clean old backups (keep last 7)
    ls -t "$BACKUP_DIR"/openclaw_backup_*.tar.gz 2>/dev/null | tail -n +8 | xargs rm -f 2>/dev/null || true
    echo "Old backups cleaned (keeping last 7)"
}

restore() {
    echo "=== OpenClaw Restore ==="

    if [[ "${1:-}" == "--latest" ]]; then
        RESTORE_FILE=$(ls -t "$BACKUP_DIR"/openclaw_backup_*.tar.gz 2>/dev/null | head -1)
        if [ -z "$RESTORE_FILE" ]; then
            echo "ERROR: No backups found in $BACKUP_DIR"
            exit 1
        fi
    elif [[ "${1:-}" == "--file" ]]; then
        RESTORE_FILE="${2:-}"
        if [ -z "$RESTORE_FILE" ] || [ ! -f "$RESTORE_FILE" ]; then
            echo "ERROR: Backup file not found: $RESTORE_FILE"
            exit 1
        fi
    else
        echo "Usage: $0 restore --latest | --file <backup_file>"
        exit 1
    fi

    echo "Restoring from: $RESTORE_FILE"

    # Create pre-restore backup
    echo "Creating pre-restore safety backup..."
    SAFETY_BACKUP="$BACKUP_DIR/pre_restore_$TIMESTAMP.tar.gz"
    tar -czf "$SAFETY_BACKUP" "$DATA_DIR/" "$CONFIG_DIR/" 2>/dev/null || true

    # Restore
    tar -xzf "$RESTORE_FILE"

    echo "Restore complete"
    echo "Safety backup: $SAFETY_BACKUP"
}

case "${1:-}" in
    backup)
        backup
        ;;
    restore)
        shift
        restore "$@"
        ;;
    *)
        echo "Usage: $0 {backup|restore}"
        echo "  backup              Create a backup"
        echo "  restore --latest    Restore from latest backup"
        echo "  restore --file <f>  Restore from specific backup file"
        exit 1
        ;;
esac
