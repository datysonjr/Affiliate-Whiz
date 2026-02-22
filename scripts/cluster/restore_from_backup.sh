#!/usr/bin/env bash
# restore_from_backup.sh — Restore from a backup snapshot
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BACKUP_DIR="$REPO_ROOT/data/backups"

if [ -z "${1:-}" ]; then
    echo "=== Available Backups ==="
    ls -1t "$BACKUP_DIR"/*.db 2>/dev/null | head -10 || echo "No backups found."
    echo ""
    echo "Usage: restore_from_backup.sh <backup_name>"
    echo "Example: restore_from_backup.sh openclaw_backup_20250615_120000"
    exit 1
fi

BACKUP_NAME="$1"
echo "=== OpenClaw Restore ==="
echo "Restoring from: $BACKUP_NAME"

# Restore database
DB_BACKUP="$BACKUP_DIR/${BACKUP_NAME}.db"
if [ -f "$DB_BACKUP" ]; then
    echo "Restoring database..."
    cp "$DB_BACKUP" "$REPO_ROOT/data/openclaw.db"
    echo "Database restored."
else
    echo "ERROR: Database backup not found: $DB_BACKUP"
    exit 1
fi

# Restore exports if available
EXPORTS_BACKUP="$BACKUP_DIR/${BACKUP_NAME}_exports.tar.gz"
if [ -f "$EXPORTS_BACKUP" ]; then
    echo "Restoring exports..."
    tar -xzf "$EXPORTS_BACKUP" -C "$REPO_ROOT/data/"
    echo "Exports restored."
else
    echo "No exports backup found (skipping)."
fi

echo ""
echo "=== Restore Complete ==="
echo "Run 'python -m src.cli health' to verify integrity."
echo "Start in DRY_RUN mode first to confirm system health."
