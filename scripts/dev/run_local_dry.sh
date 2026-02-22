#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

# Load env if present
if [[ -f ".env" ]]; then
  set -a
  source .env
  set +a
fi

mkdir -p ./data/exports ./data/logs ./data/db

echo "== OpenClaw: DRY_RUN =="

export OPENCLAW_MODE="DRY_RUN"
export ALLOW_PUBLISHING="false"
export STAGING_ONLY="true"

# Run pipeline (Claude Code will implement flags/entrypoint)
./.venv/bin/python -m src.main --dry-run

echo ""
echo "DRY_RUN complete."
echo "Check outputs in: ./data/exports"
echo "Check logs in:    ./data/logs"
