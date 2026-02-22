# Makefile — OpenClaw Affiliate Bot

PY=python3
VENV=.venv
PIP=$(VENV)/bin/pip
PYTHON=$(VENV)/bin/python

DATA_DIR=./data
EXPORTS_DIR=$(DATA_DIR)/exports
LOGS_DIR=$(DATA_DIR)/logs
DB_DIR=$(DATA_DIR)/db

.PHONY: help venv install fmt lint test clean dirs dry-run staging status tail-logs backup

help:
	@echo ""
	@echo "OpenClaw Affiliate Bot — Commands"
	@echo "  make venv        Create local venv"
	@echo "  make install     Install dependencies"
	@echo "  make test        Run tests"
	@echo "  make dry-run     Run local DRY_RUN pipeline"
	@echo "  make staging     Run SAFE_STAGING pipeline (requires env + ALLOW_PUBLISHING=true)"
	@echo "  make status      Print system status"
	@echo "  make tail-logs   Tail logs"
	@echo "  make backup      Run a local backup snapshot"
	@echo "  make clean       Remove venv + local data (DANGEROUS)"
	@echo ""

venv:
	$(PY) -m venv $(VENV)

install: venv
	$(PIP) install --upgrade pip
	@if [ -f pyproject.toml ]; then \
		$(PIP) install -e .; \
	else \
		echo "pyproject.toml not found yet (Claude Code will generate)."; \
	fi

dirs:
	@mkdir -p $(EXPORTS_DIR) $(LOGS_DIR) $(DB_DIR)

dry-run: dirs
	@echo "Running DRY_RUN..."
	@OPENCLAW_MODE=DRY_RUN ALLOW_PUBLISHING=false STAGING_ONLY=true $(PYTHON) -m src.main --dry-run

staging: dirs
	@echo "Running SAFE_STAGING..."
	@OPENCLAW_MODE=SAFE_STAGING ALLOW_PUBLISHING=true STAGING_ONLY=true $(PYTHON) -m src.main --staging

status:
	$(PYTHON) -m src.cli status

tail-logs:
	@tail -n 200 -f $(LOGS_DIR)/openclaw.log

backup: dirs
	@bash scripts/dev/backup_local.sh

test:
	$(PYTHON) -m pytest -q

clean:
	@echo "This removes .venv and ./data. CTRL+C to cancel."
	@sleep 2
	rm -rf $(VENV) $(DATA_DIR)
