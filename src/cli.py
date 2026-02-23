"""
cli.py
~~~~~~

Command-line interface for OpenClaw.

Provides the ``oc`` commands for local development and operations:

    python -m src.cli init              # Initialize DB + config
    python -m src.cli run --dry-run     # Run all agents in dry-run mode
    python -m src.cli run --pipeline content --dry-run
    python -m src.cli status            # Show system status
    python -m src.cli health            # Health checks
    python -m src.cli kill-switch --engage
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from src.core.constants import APP_NAME, APP_VERSION
from src.core.errors import OpenClawError
from src.core.logger import get_logger, setup_logging
from src.core.settings import settings
from src.data.db import Database

logger = get_logger("cli")


# =====================================================================
# Subcommand: init
# =====================================================================


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize the OpenClaw system: database, directories, config validation."""
    print(f"\n  {APP_NAME} -- Initializing...\n")

    # 1. Create required directories
    dirs = ["data", "logs", "data/backups"]
    for d in dirs:
        p = Path(d)
        p.mkdir(parents=True, exist_ok=True)
        print(f"  [OK] Directory: {d}/")

    # 2. Initialize database
    db = Database()
    db.connect()
    applied = db.migrate()
    version = db.get_schema_version()
    db.disconnect()
    print(
        f"  [OK] Database initialized (schema v{version}, {applied} migration(s) applied)"
    )

    # 3. Validate config files exist
    config_dir = Path("config")
    if config_dir.is_dir():
        yamls = list(config_dir.glob("*.yaml"))
        print(f"  [OK] Config: {len(yamls)} YAML file(s) in config/")
    else:
        print("  [WARN] Config directory 'config/' not found")

    # 4. Check .env
    env_path = Path(".env")
    if env_path.is_file():
        print("  [OK] Environment: .env file found")
    else:
        # Create from template if available
        template = Path("ops/env/example.env")
        if template.is_file():
            import shutil

            shutil.copy(template, env_path)
            print("  [OK] Environment: .env created from template")
        else:
            print("  [WARN] No .env file (create from ops/env/example.env)")

    # 5. Validate settings load
    try:
        settings.load()
        print("  [OK] Settings loaded successfully")
    except OpenClawError as exc:
        print(f"  [WARN] Settings: {exc}")

    print(
        "\n  Initialization complete. Run 'python -m src.cli run --dry-run' to test.\n"
    )
    return 0


# =====================================================================
# Subcommand: run
# =====================================================================


def cmd_run(args: argparse.Namespace) -> int:
    """Run the OpenClaw pipeline (delegates to main.main_loop)."""
    from src.main import main_loop, install_signal_handlers
    from src.core.constants import NodeRole

    dry_run = args.dry_run
    pipeline = args.pipeline or ""
    ticks = args.ticks
    real_agents = args.real_agents

    if not dry_run:
        print("\n  WARNING: Running in LIVE mode. Real API calls will be made.")
        print("  Use --dry-run for safe testing.\n")

    if real_agents:
        print("  Using REAL agents (LLMTool, CMSTool, etc.)")
    else:
        print("  Using STUB agents (no real API calls)")

    install_signal_handlers()

    try:
        settings.load()
    except OpenClawError as exc:
        logger.warning("Config load issue (non-fatal): %s", exc)

    exit_code = main_loop(
        node_role=NodeRole.CORE,
        dry_run=dry_run,
        heartbeat_interval=args.interval,
        pipeline=pipeline,
        max_ticks=ticks,
        real_agents=real_agents,
    )
    return exit_code


# =====================================================================
# Subcommand: status
# =====================================================================


def cmd_status(args: argparse.Namespace) -> int:
    """Show system status: DB state, recent runs, queue depth."""
    print(f"\n{'=' * 60}")
    print(f"  {APP_NAME} v{APP_VERSION} -- System Status")
    print(f"{'=' * 60}\n")

    # Database status
    db = Database()
    try:
        db.connect()
        version = db.get_schema_version()
        print(f"  Database:       OK (schema v{version})")

        # Recent agent runs
        runs = db.fetch_all(
            "SELECT agent_name, status, dry_run, duration_s, started_at "
            "FROM agent_runs ORDER BY id DESC LIMIT 10"
        )
        if runs:
            print(f"\n  Recent Agent Runs ({len(runs)}):")
            print(f"  {'Agent':<25} {'Status':<12} {'Duration':<10} {'Time'}")
            print(f"  {'-' * 25} {'-' * 12} {'-' * 10} {'-' * 20}")
            for r in runs:
                dr = " [DRY]" if r["dry_run"] else ""
                print(
                    f"  {r['agent_name']:<25} {r['status']:<12} {r['duration_s']:.3f}s     {r['started_at']}{dr}"
                )
        else:
            print("\n  No agent runs recorded yet.")

        # Task queue
        queued = db.fetch_one(
            "SELECT COUNT(*) as cnt FROM task_queue WHERE status='queued'"
        )
        if queued:
            print(f"\n  Task Queue:     {queued['cnt']} task(s) queued")

        # Content stats
        content = db.fetch_all(
            "SELECT status, COUNT(*) as cnt FROM content GROUP BY status"
        )
        if content:
            print("\n  Content:")
            for c in content:
                print(f"    {c['status']}: {c['cnt']}")

        # Offers stats
        offers = db.fetch_one("SELECT COUNT(*) as cnt FROM offers WHERE active=1")
        if offers and offers["cnt"] > 0:
            print(f"\n  Active Offers:  {offers['cnt']}")

        db.disconnect()

    except Exception as exc:
        print("  Database:       NOT INITIALIZED (run 'python -m src.cli init' first)")
        print(f"                  Error: {exc}")
        return 1

    # Config status
    try:
        settings.load()
        yaml_keys = list(settings._yaml.keys()) if settings._yaml else []
        print(
            f"\n  Config:         {len(yaml_keys)} YAML section(s) loaded: {', '.join(yaml_keys) or 'none'}"
        )
    except OpenClawError:
        print("\n  Config:         Not loaded")

    # Disk usage
    data_dir = Path("data")
    if data_dir.is_dir():
        total_size = sum(f.stat().st_size for f in data_dir.rglob("*") if f.is_file())
        print(f"  Data dir:       {total_size / 1024:.1f} KB")

    log_dir = Path("logs")
    if log_dir.is_dir():
        total_size = sum(f.stat().st_size for f in log_dir.rglob("*") if f.is_file())
        print(f"  Log dir:        {total_size / 1024:.1f} KB")

    print(f"\n{'=' * 60}\n")
    return 0


# =====================================================================
# Subcommand: health
# =====================================================================


def cmd_health(args: argparse.Namespace) -> int:
    """Run system health checks."""
    checks: dict[str, str] = {}

    # Config
    try:
        settings.load()
        checks["configuration"] = "OK"
    except OpenClawError as exc:
        checks["configuration"] = f"WARN: {exc}"

    # Database
    try:
        db = Database()
        db.connect()
        db.get_schema_version()
        db.disconnect()
        checks["database"] = "OK"
    except Exception as exc:
        checks["database"] = f"FAIL: {exc}"

    # Disk space
    import shutil

    usage = shutil.disk_usage(".")
    pct = usage.used / usage.total * 100
    if pct > 90:
        checks["disk_space"] = f"WARN: {pct:.0f}% used"
    else:
        checks["disk_space"] = f"OK ({pct:.0f}% used, {usage.free // (1024**3)}GB free)"

    # Config files
    config_dir = Path("config")
    if config_dir.is_dir():
        checks["config_files"] = (
            f"OK ({len(list(config_dir.glob('*.yaml')))} YAML files)"
        )
    else:
        checks["config_files"] = "FAIL: config/ directory missing"

    # Print report
    print(f"\n{'=' * 50}")
    print(f"  {APP_NAME} Health Report")
    print(f"{'=' * 50}")
    failed = []
    for name, status in checks.items():
        if status.startswith("OK"):
            indicator = "[OK]  "
        elif status.startswith("WARN"):
            indicator = "[WARN]"
        else:
            indicator = "[FAIL]"
            failed.append(name)
        print(f"  {indicator} {name}: {status}")
    print(f"{'=' * 50}")

    if failed:
        print(f"\n  {len(failed)} check(s) failed.")
        return 1
    print("\n  All checks passed.")
    return 0


# =====================================================================
# Subcommand: kill-switch
# =====================================================================


def cmd_kill_switch(args: argparse.Namespace) -> int:
    """Engage or disengage the kill switch."""
    reason = args.reason or "manual operator action"

    # Store kill switch state in a simple file for cross-process coordination
    ks_file = Path("data/.kill_switch")
    ks_file.parent.mkdir(parents=True, exist_ok=True)

    if args.engage:
        ks_file.write_text(
            json.dumps(
                {
                    "engaged": True,
                    "reason": reason,
                    "engaged_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        )
        print(f"  Kill switch ENGAGED. Reason: {reason}")
        print("  All agents will be halted on next tick.")
    else:
        if ks_file.exists():
            ks_file.unlink()
        print(f"  Kill switch DISENGAGED. Reason: {reason}")
        print("  Normal operations can resume.")

    return 0


# =====================================================================
# Subcommand: publish-canary
# =====================================================================


def cmd_publish_canary(args: argparse.Namespace) -> int:
    """Publish a single canary draft to WordPress staging."""
    from src.ops.canary_publish import run_canary_publish

    print(f"\n  {APP_NAME} -- Canary Publish\n")
    print(f"  Title:   {args.title}")
    print("  Target:  WordPress staging (draft)")
    print()

    try:
        result = run_canary_publish(staging=args.staging, title=args.title)
    except Exception as exc:
        print(f"  FAILED: {exc}\n")
        logger.error("Canary publish failed: %s", exc)
        return 1

    print("  SUCCESS!")
    print(f"  Post ID:  {result.get('post_id', 'N/A')}")
    print(f"  URL:      {result.get('url', 'N/A')}")
    print(f"  Status:   {result.get('status', 'N/A')}")
    print(f"  Words:    {result.get('word_count', 'N/A')}")
    print("\n  Check WP Admin -> Posts -> Drafts to verify.\n")
    return 0


# =====================================================================
# Parser construction
# =====================================================================


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oc",
        description=f"{APP_NAME} v{APP_VERSION} -- CLI",
    )
    parser.add_argument(
        "--version", action="version", version=f"{APP_NAME} {APP_VERSION}"
    )

    subparsers = parser.add_subparsers(
        dest="command",
        title="commands",
        description="Available commands",
        required=True,
    )

    # -- init
    sp_init = subparsers.add_parser(
        "init", help="Initialize database, directories, and config."
    )
    sp_init.set_defaults(func=cmd_init)

    # -- run
    sp_run = subparsers.add_parser("run", help="Run the agent pipeline.")
    sp_run.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="No side-effects (safe mode).",
    )
    sp_run.add_argument(
        "--pipeline",
        type=str,
        default="",
        choices=["", "content", "publishing", "analytics"],
        help="Run only a specific pipeline.",
    )
    sp_run.add_argument(
        "--ticks",
        type=int,
        default=1,
        help="Number of scheduler ticks to run (default: 1).",
    )
    sp_run.add_argument(
        "--interval", type=int, default=5, help="Seconds between ticks (default: 5)."
    )
    sp_run.add_argument(
        "--real-agents",
        action="store_true",
        default=False,
        help="Use real agent classes with actual tool integrations (LLM, CMS, etc.).",
    )
    sp_run.set_defaults(func=cmd_run)

    # -- status
    sp_status = subparsers.add_parser(
        "status", help="Show system status and recent activity."
    )
    sp_status.set_defaults(func=cmd_status)

    # -- health
    sp_health = subparsers.add_parser("health", help="Run system health checks.")
    sp_health.set_defaults(func=cmd_health)

    # -- publish-canary
    sp_canary = subparsers.add_parser(
        "publish-canary",
        help="Publish a single canary draft to WordPress staging to verify CMS integration.",
    )
    sp_canary.add_argument(
        "--staging",
        action="store_true",
        default=True,
        help="Target WordPress staging (default, required for canary).",
    )
    sp_canary.add_argument(
        "--title",
        type=str,
        default="Best Wireless Earbuds for Running 2025 — Honest Review",
        help="Title for the canary article.",
    )
    sp_canary.set_defaults(func=cmd_publish_canary)

    # -- kill-switch
    sp_kill = subparsers.add_parser(
        "kill-switch", help="Engage or disengage the kill switch."
    )
    sp_kill_group = sp_kill.add_mutually_exclusive_group(required=True)
    sp_kill_group.add_argument("--engage", action="store_true", help="Halt all agents.")
    sp_kill_group.add_argument(
        "--disengage", action="store_true", help="Resume operations."
    )
    sp_kill.add_argument(
        "--reason", type=str, default=None, help="Reason (for audit log)."
    )
    sp_kill.set_defaults(func=cmd_kill_switch)

    return parser


# =====================================================================
# Entry point
# =====================================================================


def main(argv: Sequence[str] | None = None) -> int:
    setup_logging(enable_file=False, enable_json=False)

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return args.func(args)
    except OpenClawError as exc:
        logger.error("Command failed: %s", exc)
        print(f"ERROR: {exc}")
        return 1
    except Exception as exc:
        logger.critical("Unexpected error: %s", exc, exc_info=True)
        print(f"FATAL: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
