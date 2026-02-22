#!/usr/bin/env bash
# bootstrap_local.sh — Set up local dev environment for OpenClaw
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

echo "=== OpenClaw Local Bootstrap ==="

# 1) Check Python version
PYTHON="${PYTHON:-python3}"
REQUIRED_VERSION="3.11"
PYTHON_VERSION=$($PYTHON --version 2>&1 | awk '{print $2}')
echo "Python version: $PYTHON_VERSION (required: >= $REQUIRED_VERSION)"

# 2) Create virtual environment if not present
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    $PYTHON -m venv .venv
fi
source .venv/bin/activate
echo "Virtual environment activated: $(which python)"

# 3) Install dependencies
echo "Installing dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q

# 4) Copy .env if not present
if [ ! -f ".env" ]; then
    if [ -f "ops/env/example.env" ]; then
        cp ops/env/example.env .env
        echo "Copied ops/env/example.env -> .env (fill in your secrets)"
    elif [ -f ".env.example" ]; then
        cp .env.example .env
        echo "Copied .env.example -> .env (fill in your secrets)"
    else
        echo "WARNING: No .env template found. Create .env manually."
    fi
else
    echo ".env already exists, skipping."
fi

# 5) Create runtime directories
mkdir -p data data/exports data/backups logs tmp
echo "Runtime directories created."

# 6) Initialize database
echo "Initializing database..."
python -m src.cli init

echo ""
echo "=== Bootstrap Complete ==="
echo "To activate:  source .venv/bin/activate"
echo "To run:       python -m src.cli run --dry-run --ticks 2"
echo "To check:     python -m src.cli status"
