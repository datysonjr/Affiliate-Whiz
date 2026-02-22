#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

if [[ -f ".env" ]]; then
  set -a
  source .env
  set +a
fi

mkdir -p ./data/exports ./data/logs ./data/db

echo "== OpenClaw: SAFE_STAGING =="

# Guardrails
if [[ "${ALLOW_PUBLISHING:-false}" != "true" ]]; then
  echo "ERROR: ALLOW_PUBLISHING must be true in .env for staging."
  echo "Set ALLOW_PUBLISHING=true and ensure WP_STAGING_* vars are set."
  exit 1
fi

export OPENCLAW_MODE="SAFE_STAGING"
export STAGING_ONLY="true"

./.venv/bin/python -m src.main --staging

echo ""
echo "SAFE_STAGING complete."
echo "Verify staging WordPress posts as drafts."
