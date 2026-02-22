#!/usr/bin/env bash
# bootstrap_node.sh — Bootstrap a cluster node for OpenClaw
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

NODE_ROLE="${1:-full}"

echo "=== OpenClaw Node Bootstrap ==="
echo "Role: $NODE_ROLE"

# 1) Check Python
PYTHON="${PYTHON:-python3}"
echo "Python: $($PYTHON --version 2>&1)"

# 2) Create venv
if [ ! -d ".venv" ]; then
    $PYTHON -m venv .venv
fi
source .venv/bin/activate

# 3) Install deps
pip install --upgrade pip -q
pip install -r requirements.txt -q

# 4) Setup .env
if [ ! -f ".env" ]; then
    if [ -f "ops/env/example.env" ]; then
        cp ops/env/example.env .env
        echo "WARNING: .env copied from template — fill in secrets before running!"
    fi
fi

# 5) Create dirs
mkdir -p data data/exports data/backups logs tmp

# 6) Init DB
python -m src.cli init

echo ""
echo "=== Node Bootstrap Complete ==="
echo "Role: $NODE_ROLE"
echo "Next: configure .env, then run deploy_stack.sh"
