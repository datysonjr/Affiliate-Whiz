#!/usr/bin/env bash
set -euo pipefail

# Set up Docker environment for OpenClaw
# Usage: bash ops/scripts/setup_docker.sh

echo "=== OpenClaw Docker Setup ==="

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker not found. Install from https://docker.com"
    exit 1
fi

echo "Docker version: $(docker --version)"

# Check Docker Compose
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "ERROR: Docker Compose not found."
    exit 1
fi

# Build images
echo "Building Docker images..."
docker compose -f deployments/docker/docker-compose.yml build

# Create volumes
echo "Creating volumes..."
docker volume create openclaw-data 2>/dev/null || true
docker volume create openclaw-logs 2>/dev/null || true

echo ""
echo "=== Docker Setup Complete ==="
echo ""
echo "To start: docker compose -f deployments/docker/docker-compose.yml up -d"
echo "To stop:  docker compose -f deployments/docker/docker-compose.yml down"
echo "To logs:  docker compose -f deployments/docker/docker-compose.yml logs -f"
