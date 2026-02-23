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
elif [[ -f "requirements.txt" ]]; then
  echo "Installing dependencies from requirements.txt..."
  ./.venv/bin/pip install -r requirements.txt
else
  echo "No pyproject.toml or requirements.txt found."
  echo "Once one exists, re-run: bash scripts/dev/bootstrap_local.sh"
fi

# 5) Install pre-commit hooks
echo "Installing pre-commit hooks..."
./.venv/bin/pip install -U pre-commit ruff >/dev/null
./.venv/bin/pre-commit install
echo "Pre-commit hooks installed (ruff lint + format run on every commit)."

echo ""
echo "Bootstrap complete."
echo ""
echo "Next:"
echo "  make dry-run   — run a DRY_RUN cycle"
echo "  make test      — run the test suite"
echo "  make fix       — auto-fix lint before pushing"
