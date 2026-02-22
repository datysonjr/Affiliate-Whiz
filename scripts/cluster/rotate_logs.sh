#!/usr/bin/env bash
# rotate_logs.sh — Rotate and compress old log files
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LOG_DIR="$REPO_ROOT/logs"
DAYS_TO_KEEP="${1:-30}"

echo "=== Log Rotation ==="
echo "Log dir: $LOG_DIR"
echo "Keeping logs from last $DAYS_TO_KEEP days"

if [ ! -d "$LOG_DIR" ]; then
    echo "No logs directory found."
    exit 0
fi

# Compress log files older than 1 day
find "$LOG_DIR" -name "*.log" -mtime +1 -exec gzip -q {} \; 2>/dev/null || true
echo "Compressed old .log files."

# Delete compressed logs older than retention period
DELETED=$(find "$LOG_DIR" -name "*.gz" -mtime +"$DAYS_TO_KEEP" -delete -print | wc -l)
echo "Deleted $DELETED compressed logs older than $DAYS_TO_KEEP days."

echo "=== Log Rotation Complete ==="
