#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

echo "== OpenClaw: Local Bootstrap =="

# 1) Ensure .env exists
if [[ ! -f ".env" ]]; then
  echo "No .env found. Copying from .env.example..."
  cp .env.example .env
  echo "Created .env (placeholders). Edit it before SAFE_STAGING/PRODUCTION."
fi

# 2) Create local data dirs
mkdir -p ./data/exports ./data/logs ./data/db

# 3) Create venv if missing
if [[ ! -d ".venv" ]]; then
  echo "Creating venv..."
  python3 -m venv .venv
fi

# 4) Install deps (expects Claude Code to create pyproject.toml)
echo "Upgrading pip..."
./.venv/bin/pip install --upgrade pip >/dev/null

if [[ -f "pyproject.toml" ]]; then
  echo "Installing dependencies..."
  ./.venv/bin/pip install -e .
else
  echo "pyproject.toml not found yet."
  echo "That's OK if you haven't generated the Python scaffold with Claude Code yet."
  echo "Once it exists, re-run: bash scripts/dev/bootstrap_local.sh"
fi

echo "Bootstrap complete."
echo ""
echo "Next:"
echo "  1) Generate code scaffold with Claude Code (if not done)"
echo "  2) Run DRY_RUN: bash scripts/dev/run_local_dry.sh"
