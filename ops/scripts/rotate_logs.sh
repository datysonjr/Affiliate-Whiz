#!/usr/bin/env bash
set -euo pipefail

# Log rotation script for OpenClaw
# Usage: bash ops/scripts/rotate_logs.sh
# Recommended: Add to crontab to run daily

LOG_DIR="${LOG_DIR:-logs}"
MAX_LOG_FILES=30
MAX_LOG_SIZE_MB=100

echo "=== OpenClaw Log Rotation ==="
echo "Log directory: $LOG_DIR"

if [ ! -d "$LOG_DIR" ]; then
    echo "Log directory does not exist. Nothing to rotate."
    exit 0
fi

# Rotate logs larger than MAX_LOG_SIZE_MB
for logfile in "$LOG_DIR"/*.log; do
    [ -f "$logfile" ] || continue

    size_mb=$(du -m "$logfile" 2>/dev/null | cut -f1)
    if [ "$size_mb" -gt "$MAX_LOG_SIZE_MB" ]; then
        timestamp=$(date +%Y%m%d_%H%M%S)
        rotated="${logfile}.${timestamp}"
        mv "$logfile" "$rotated"
        gzip "$rotated"
        touch "$logfile"
        echo "Rotated: $logfile ($size_mb MB) -> ${rotated}.gz"
    fi
done

# Clean old rotated logs (keep last MAX_LOG_FILES)
for logfile in "$LOG_DIR"/*.log; do
    [ -f "$logfile" ] || continue
    basename=$(basename "$logfile" .log)
    ls -t "$LOG_DIR/${basename}.log."*.gz 2>/dev/null | tail -n +$((MAX_LOG_FILES + 1)) | xargs rm -f 2>/dev/null || true
done

echo "Log rotation complete"
