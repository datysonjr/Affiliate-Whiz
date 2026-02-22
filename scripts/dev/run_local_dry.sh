#!/usr/bin/env bash
# run_local_dry.sh — Run OpenClaw in DRY_RUN mode locally
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

# Activate venv if present
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

TICKS="${1:-3}"
INTERVAL="${2:-10}"

echo "=== OpenClaw DRY_RUN (local) ==="
echo "Ticks: $TICKS | Interval: ${INTERVAL}s"
echo ""

python -m src.cli run --dry-run --ticks "$TICKS" --interval "$INTERVAL"
