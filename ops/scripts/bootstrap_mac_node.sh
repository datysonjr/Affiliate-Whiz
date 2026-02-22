#!/usr/bin/env bash
set -euo pipefail

# Bootstrap a Mac Mini node for OpenClaw
# Usage: bash ops/scripts/bootstrap_mac_node.sh

echo "=== OpenClaw Node Bootstrap ==="
echo "Node: $(hostname)"
echo "Date: $(date)"
echo ""

# Check macOS
if [[ "$(uname)" != "Darwin" ]]; then
    echo "WARNING: This script is designed for macOS. Proceeding anyway..."
fi

# Check Python
echo "Checking Python..."
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version)
    echo "  Found: $PYTHON_VERSION"
else
    echo "  ERROR: Python 3 not found. Install from https://python.org"
    exit 1
fi

# Check pip
echo "Checking pip..."
if command -v pip3 &> /dev/null; then
    echo "  Found: $(pip3 --version)"
else
    echo "  Installing pip..."
    python3 -m ensurepip --upgrade
fi

# Create virtual environment
echo "Setting up virtual environment..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "  Created .venv"
else
    echo "  .venv already exists"
fi

source .venv/bin/activate
echo "  Activated .venv"

# Install dependencies
echo "Installing dependencies..."
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
    echo "  Dependencies installed"
else
    echo "  WARNING: requirements.txt not found"
fi

# Create required directories
echo "Creating directories..."
mkdir -p logs tmp data
echo "  Created logs/, tmp/, data/"

# Copy environment template
if [ ! -f ".env" ]; then
    cp ops/env/example.env .env
    echo "  Copied example.env to .env"
    echo "  IMPORTANT: Edit .env with your configuration"
else
    echo "  .env already exists"
fi

# Set permissions
echo "Setting permissions..."
chmod 700 ops/secrets/
chmod 600 .env 2>/dev/null || true
echo "  Permissions set"

echo ""
echo "=== Bootstrap Complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit .env with your configuration"
echo "  2. Set NODE_NAME and NODE_ROLE in .env"
echo "  3. Initialize the database: python src/cli.py init-db"
echo "  4. Run in dry-run mode first: python src/main.py --dry-run"
