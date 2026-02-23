# Developer Setup — OpenClaw

## Quick Start

```bash
# One-command bootstrap (venv + deps + pre-commit hooks + init)
make bootstrap
```

Or manually:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -U pre-commit ruff
pre-commit install
```

## Pre-commit Hooks

Pre-commit runs automatically on every `git commit`. It catches lint and
formatting issues before they reach CI so you never get surprised by a red
build.

**What runs on each commit:**

| Hook | What it does |
|---|---|
| `ruff --fix` | Lint check + auto-fix (unused imports, etc.) |
| `ruff-format` | Code formatting (Black-compatible) |
| `end-of-file-fixer` | Ensures files end with a newline |
| `trailing-whitespace` | Removes trailing whitespace |
| `check-yaml` | Validates YAML syntax |
| `check-added-large-files` | Blocks accidental large file commits |

### Install hooks (one-time)

```bash
make precommit-install
```

### Run hooks on all files

```bash
make precommit-run
```

## Makefile Targets

| Target | Description |
|---|---|
| `make lint` | Check lint + formatting + types (same as CI) |
| `make fix` | Auto-fix lint + format the whole repo |
| `make fmt` | Auto-format only (no lint fixes) |
| `make test` | Run pytest |
| `make dry-run` | Run the pipeline in DRY_RUN mode |
| `make status` | Print system status |

## Recommended Workflow

```bash
# 1. Write code
# 2. Before pushing, fix any lint issues:
make fix

# 3. Run tests:
make test

# 4. Commit (pre-commit hooks run automatically):
git add -A && git commit -m "your message"

# 5. Push:
git push
```

If pre-commit blocks your commit, it usually means ruff found an issue it
couldn't auto-fix (e.g., an unused variable in logic). Fix it manually, then
re-commit.

## CI Alignment

CI (`.github/workflows/ci.yml`) runs the same checks as `make lint`:

1. `ruff check .`
2. `ruff format --check .`
3. `mypy src/ --ignore-missing-imports`
4. `pytest -q`

If `make lint` passes locally, CI will pass too.
