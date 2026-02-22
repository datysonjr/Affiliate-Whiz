#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

TS="$(date +"%Y%m%d-%H%M%S")"
BACKUP_DIR="./data/backups/$TS"

mkdir -p "$BACKUP_DIR"

echo "== OpenClaw: Local Backup =="

# Copy DB + exports + config (no secrets)
if [[ -f "./data/db/openclaw.sqlite" ]]; then
  cp "./data/db/openclaw.sqlite" "$BACKUP_DIR/openclaw.sqlite"
else
  echo "WARN: DB not found at ./data/db/openclaw.sqlite"
fi

if [[ -d "./data/exports" ]]; then
  cp -R "./data/exports" "$BACKUP_DIR/exports"
fi

if [[ -d "./config" ]]; then
  cp -R "./config" "$BACKUP_DIR/config"
fi

echo "Backup created: $BACKUP_DIR"
