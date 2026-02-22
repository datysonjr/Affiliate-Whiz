#!/usr/bin/env bash
# backup_now.sh — Create a timestamped backup of DB and exports
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BACKUP_DIR="$REPO_ROOT/data/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="openclaw_backup_$TIMESTAMP"

echo "=== OpenClaw Backup ==="

mkdir -p "$BACKUP_DIR"

# Backup database
DB_FILE="$REPO_ROOT/data/openclaw.db"
if [ -f "$DB_FILE" ]; then
    cp "$DB_FILE" "$BACKUP_DIR/${BACKUP_NAME}.db"
    echo "Database backed up: ${BACKUP_NAME}.db"
else
    echo "No database found at $DB_FILE"
fi

# Backup exports
EXPORTS_DIR="$REPO_ROOT/data/exports"
if [ -d "$EXPORTS_DIR" ] && [ "$(ls -A "$EXPORTS_DIR" 2>/dev/null)" ]; then
    tar -czf "$BACKUP_DIR/${BACKUP_NAME}_exports.tar.gz" -C "$REPO_ROOT/data" exports/
    echo "Exports backed up: ${BACKUP_NAME}_exports.tar.gz"
else
    echo "No exports to backup."
fi

# Backup config (non-secret)
tar -czf "$BACKUP_DIR/${BACKUP_NAME}_config.tar.gz" -C "$REPO_ROOT" config/ --exclude='*.key' --exclude='*.pem' --exclude='*.secret' 2>/dev/null || true
echo "Config backed up: ${BACKUP_NAME}_config.tar.gz"

# Cleanup old backups (keep last 30)
BACKUP_COUNT=$(ls -1 "$BACKUP_DIR" | wc -l)
if [ "$BACKUP_COUNT" -gt 90 ]; then
    echo "Cleaning old backups (keeping newest 90 files)..."
    ls -1t "$BACKUP_DIR" | tail -n +"91" | xargs -I {} rm "$BACKUP_DIR/{}"
fi

echo "=== Backup Complete ==="
echo "Location: $BACKUP_DIR"
