#!/usr/bin/env bash
# deploy_stack.sh — Deploy OpenClaw cluster services via Docker Compose
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

COMPOSE_FILE="deployments/docker/docker-compose.yml"
MODE="${1:-dev}"

echo "=== OpenClaw Cluster Deploy ==="
echo "Mode: $MODE"

case "$MODE" in
    dev)
        echo "Starting local dev node..."
        docker compose -f "$COMPOSE_FILE" up -d openclaw-dev
        ;;
    cluster)
        echo "Starting cluster (core + pub)..."
        docker compose -f "$COMPOSE_FILE" up -d openclaw-core openclaw-pub
        ;;
    *)
        echo "Usage: deploy_stack.sh [dev|cluster]"
        exit 1
        ;;
esac

echo ""
echo "Services started. Check with: docker compose -f $COMPOSE_FILE ps"
