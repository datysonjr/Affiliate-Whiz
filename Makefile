# Makefile — OpenClaw Affiliate Bot

PY=python3
VENV=.venv
PIP=$(VENV)/bin/pip
PYTHON=$(VENV)/bin/python

DATA_DIR=./data
EXPORTS_DIR=$(DATA_DIR)/exports
LOGS_DIR=$(DATA_DIR)/logs
DB_DIR=$(DATA_DIR)/db

.PHONY: help venv install bootstrap fmt lint fix test clean dirs dry-run staging status tail-logs backup precommit-install precommit-run

help:
	@echo ""
	@echo "OpenClaw Affiliate Bot — Commands"
	@echo "  make bootstrap          One-command setup (venv + deps + env + pre-commit + init)"
	@echo "  make venv               Create local venv"
	@echo "  make install            Install dependencies"
	@echo "  make test               Run tests"
	@echo "  make lint               Run ruff check + ruff format --check + mypy"
	@echo "  make fix                Auto-fix lint issues (ruff --fix + format)"
	@echo "  make fmt                Auto-format code (ruff format)"
	@echo "  make dry-run            Run local DRY_RUN pipeline"
	@echo "  make staging            Run SAFE_STAGING pipeline"
	@echo "  make status             Print system status"
	@echo "  make tail-logs          Tail logs"
	@echo "  make backup             Run a local backup snapshot"
	@echo "  make precommit-install  Install pre-commit git hooks"
	@echo "  make precommit-run      Run all pre-commit hooks on every file"
	@echo "  make clean              Remove venv + local data (DANGEROUS)"
	@echo ""

venv:
	$(PY) -m venv $(VENV)

install: venv
	$(PIP) install --upgrade pip
	@if [ -f pyproject.toml ]; then \
		$(PIP) install -e .; \
	elif [ -f requirements.txt ]; then \
		$(PIP) install -r requirements.txt; \
	else \
		echo "No pyproject.toml or requirements.txt found."; \
	fi

bootstrap: install dirs precommit-install
	@if [ ! -f .env ]; then \
		echo "Copying .env.example -> .env"; \
		cp .env.example .env; \
	else \
		echo ".env already exists, skipping copy."; \
	fi
	@echo "Running init..."
	$(PYTHON) -m src.cli init || echo "Init completed (or cli not fully wired yet)."
	@echo ""
	@echo "Bootstrap complete. Next steps:"
	@echo "  make dry-run    — run a DRY_RUN cycle"
	@echo "  make test       — run the test suite"
	@echo "  make fix        — auto-fix lint before pushing"

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .
	$(PYTHON) -m mypy src/ --ignore-missing-imports

fix:
	$(PYTHON) -m ruff check . --fix
	$(PYTHON) -m ruff check . --fix --unsafe-fixes
	$(PYTHON) -m ruff format .

fmt:
	$(PYTHON) -m ruff format .

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

precommit-install:
	$(PIP) install -U pre-commit
	$(VENV)/bin/pre-commit install

precommit-run:
	$(VENV)/bin/pre-commit run --all-files

clean:
	@echo "This removes .venv and ./data. CTRL+C to cancel."
	@sleep 2
	rm -rf $(VENV) $(DATA_DIR)
