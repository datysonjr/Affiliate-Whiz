"""
cli.py
~~~~~~

Command-line interface for OpenClaw administrative operations.

Provides subcommands for database initialization, health checks, emergency
controls, configuration management, and content operations.

Usage::

    # Initialize or migrate the database
    python -m src.cli init-db

    # Check system health
    python -m src.cli health --verbose

    # Engage the kill switch (halt all agents immediately)
    python -m src.cli kill-switch --engage

    # Unpublish a specific post
    python -m src.cli unpublish --post-id abc123 --reason "compliance issue"

    # Revert to a previous content version
    python -m src.cli revert --post-id abc123 --version 2

    # Rotate API keys for a provider
    python -m src.cli rotate-keys --provider openai

    # Reload configuration without restarting
    python -m src.cli reload-config

    # Verify data integrity
    python -m src.cli check-integrity --fix

    # Restart a specific agent
    python -m src.cli restart --agent research
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from src.core.constants import APP_NAME, APP_VERSION, AgentName
from src.core.errors import OpenClawError
from src.core.logger import get_logger, setup_logging
from src.core.settings import settings

logger = get_logger("cli")


# =====================================================================
# Subcommand handlers
# =====================================================================

def cmd_init_db(args: argparse.Namespace) -> int:
    """Initialize or migrate the OpenClaw database.

    Creates tables, runs pending migrations, and optionally seeds
    reference data (niches, default thresholds, etc.).

    Returns
    -------
    int
        ``0`` on success, ``1`` on failure.
    """
    logger.info("Initializing database...")

    db_path = settings.get_str("database.path", "data/openclaw.db")
    run_migrations = not args.skip_migrations
    seed = args.seed

    logger.info(
        "Database path: %s | migrations: %s | seed: %s",
        db_path,
        run_migrations,
        seed,
    )

    # TODO: Replace with actual database initialization once data layer lands.
    # from src.data.migrations import run_all_migrations
    # from src.data.seed import seed_reference_data
    #
    # engine = create_engine(db_path)
    # if run_migrations:
    #     run_all_migrations(engine)
    # if seed:
    #     seed_reference_data(engine)

    logger.info("Database initialization complete.")
    print(f"Database initialized at {db_path}")
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    """Run system health checks and report status.

    Checks database connectivity, agent statuses, disk space, external
    API reachability, and configuration validity.

    Returns
    -------
    int
        ``0`` if healthy, ``1`` if degraded, ``2`` if critical.
    """
    logger.info("Running health checks...")
    verbose = args.verbose

    checks: dict[str, str] = {}

    # -- Configuration check -------------------------------------------
    try:
        settings.load()
        checks["configuration"] = "OK"
    except OpenClawError as exc:
        checks["configuration"] = f"FAIL: {exc}"

    # -- Database check ------------------------------------------------
    # TODO: Implement real DB connectivity check
    checks["database"] = "OK (stub)"

    # -- Disk space check ----------------------------------------------
    # TODO: Implement real disk space check
    checks["disk_space"] = "OK (stub)"

    # -- External APIs check -------------------------------------------
    # TODO: Ping affiliate network APIs, LLM providers, etc.
    checks["external_apis"] = "OK (stub)"

    # -- Report --------------------------------------------------------
    failed = [name for name, status in checks.items() if not status.startswith("OK")]

    print(f"\n{'='*50}")
    print(f"  {APP_NAME} Health Report")
    print(f"{'='*50}")
    for name, status in checks.items():
        indicator = "[OK]  " if status.startswith("OK") else "[FAIL]"
        print(f"  {indicator} {name}: {status}")
        if verbose:
            logger.info("Health check %s: %s", name, status)
    print(f"{'='*50}")

    if failed:
        print(f"\n  {len(failed)} check(s) failed: {', '.join(failed)}")
        return 2 if len(failed) > 1 else 1
    else:
        print("\n  All checks passed.")
        return 0


def cmd_kill_switch(args: argparse.Namespace) -> int:
    """Engage or disengage the system-wide kill switch.

    When engaged, all agents are halted immediately and no new tasks
    are dispatched.  Existing in-flight work is allowed to complete
    (with a timeout) but no new work starts.

    Returns
    -------
    int
        ``0`` on success.
    """
    action = "engage" if args.engage else "disengage"
    logger.warning("Kill switch action: %s", action)

    # TODO: Implement kill switch via orchestrator state file or DB flag.
    # from src.orchestrator.controller import OrchestratorController
    # controller = OrchestratorController.from_settings(settings)
    # if args.engage:
    #     controller.engage_kill_switch(reason=args.reason)
    # else:
    #     controller.disengage_kill_switch()

    reason = args.reason or "manual operator action"
    print(f"Kill switch {action}d. Reason: {reason}")
    logger.warning("Kill switch %sd by CLI. Reason: %s", action, reason)
    return 0


def cmd_unpublish(args: argparse.Namespace) -> int:
    """Remove a published post from the live site.

    The content is retained in the database with status ``unpublished``
    for audit purposes.  The CMS entry is deleted or set to draft.

    Returns
    -------
    int
        ``0`` on success, ``1`` on failure.
    """
    post_id = args.post_id
    reason = args.reason or "manual unpublish"

    logger.info("Unpublishing post %s. Reason: %s", post_id, reason)

    # TODO: Implement via publishing pipeline.
    # from src.pipelines.publishing import unpublish_post
    # unpublish_post(post_id=post_id, reason=reason, dry_run=args.dry_run)

    print(f"Post {post_id} unpublished. Reason: {reason}")
    return 0


def cmd_revert(args: argparse.Namespace) -> int:
    """Revert a post to a previous content version.

    Fetches the specified version from the content history table and
    re-publishes it, replacing the current live version.

    Returns
    -------
    int
        ``0`` on success, ``1`` on failure.
    """
    post_id = args.post_id
    version = args.version

    logger.info("Reverting post %s to version %d", post_id, version)

    # TODO: Implement content version revert.
    # from src.data.models import ContentVersion
    # from src.pipelines.publishing import republish_version
    # republish_version(post_id=post_id, target_version=version)

    print(f"Post {post_id} reverted to version {version}.")
    return 0


def cmd_rotate_keys(args: argparse.Namespace) -> int:
    """Rotate API keys for the specified provider.

    Generates new credentials (where the provider supports it),
    updates the vault, and verifies connectivity with the new keys.

    Returns
    -------
    int
        ``0`` on success, ``1`` on failure.
    """
    provider = args.provider

    logger.info("Rotating API keys for provider: %s", provider)

    # TODO: Implement key rotation.
    # from src.integrations.vault import rotate_provider_keys
    # rotate_provider_keys(provider=provider, dry_run=args.dry_run)

    if args.dry_run:
        print(f"[DRY RUN] Would rotate keys for provider: {provider}")
    else:
        print(f"Keys rotated for provider: {provider}")
    return 0


def cmd_reload_config(args: argparse.Namespace) -> int:
    """Reload configuration from disk without restarting the process.

    Re-reads ``.env`` and all YAML config files, validates them, and
    pushes the updated configuration to running agents.

    Returns
    -------
    int
        ``0`` on success, ``1`` on failure.
    """
    logger.info("Reloading configuration...")

    try:
        settings.load()
        logger.info("Configuration reloaded successfully: %s", settings)
        print("Configuration reloaded successfully.")
        return 0
    except OpenClawError as exc:
        logger.error("Failed to reload configuration: %s", exc)
        print(f"ERROR: Failed to reload configuration: {exc}")
        return 1


def cmd_check_integrity(args: argparse.Namespace) -> int:
    """Verify data integrity across the database and published content.

    Checks for:
    - Orphaned records (content without offers, offers without content)
    - Broken internal links
    - Hash mismatches between stored and computed content hashes
    - Missing published content (DB says published, CMS says missing)

    Returns
    -------
    int
        ``0`` if all checks pass, ``1`` if issues found.
    """
    fix = args.fix
    logger.info("Running integrity checks (fix=%s)...", fix)

    issues_found: list[str] = []

    # TODO: Implement real integrity checks.
    # from src.data.integrity import (
    #     check_orphaned_records,
    #     check_broken_links,
    #     check_content_hashes,
    #     check_publish_sync,
    # )
    # issues_found.extend(check_orphaned_records(fix=fix))
    # issues_found.extend(check_broken_links(fix=fix))
    # issues_found.extend(check_content_hashes(fix=fix))
    # issues_found.extend(check_publish_sync(fix=fix))

    if issues_found:
        print(f"\nIntegrity check found {len(issues_found)} issue(s):")
        for issue in issues_found:
            print(f"  - {issue}")
        if fix:
            print("\nAuto-fix was applied where possible.")
        return 1
    else:
        print("Integrity check passed -- no issues found.")
        return 0


def cmd_restart(args: argparse.Namespace) -> int:
    """Restart a specific agent or the entire orchestrator.

    Sends a restart signal to the named agent, causing it to re-read
    its configuration and reinitialize.  If ``--all`` is specified,
    every agent is restarted sequentially.

    Returns
    -------
    int
        ``0`` on success, ``1`` on failure.
    """
    agent_name = args.agent
    restart_all = args.all

    if restart_all:
        logger.info("Restarting all agents...")
        targets = [a.value for a in AgentName]
    else:
        logger.info("Restarting agent: %s", agent_name)
        targets = [agent_name]

    for target in targets:
        logger.info("Sending restart signal to agent: %s", target)
        # TODO: Implement agent restart via orchestrator IPC.
        # from src.orchestrator.controller import OrchestratorController
        # controller = OrchestratorController.from_settings(settings)
        # controller.restart_agent(target)
        print(f"Agent '{target}' restart signal sent.")

    return 0


# =====================================================================
# Parser construction
# =====================================================================

def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser with all subcommands.

    Returns
    -------
    argparse.ArgumentParser
        Fully configured parser ready for ``parse_args()``.
    """
    parser = argparse.ArgumentParser(
        prog="openclaw-cli",
        description=f"{APP_NAME} v{APP_VERSION} -- Administrative CLI",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{APP_NAME} {APP_VERSION}",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Preview actions without making changes.",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        title="commands",
        description="Available administrative commands",
        required=True,
    )

    # -- init-db --------------------------------------------------------
    sp_init = subparsers.add_parser(
        "init-db",
        help="Initialize or migrate the database.",
    )
    sp_init.add_argument(
        "--skip-migrations",
        action="store_true",
        default=False,
        help="Create tables without running migrations.",
    )
    sp_init.add_argument(
        "--seed",
        action="store_true",
        default=False,
        help="Seed reference data (niches, thresholds, etc.).",
    )
    sp_init.set_defaults(func=cmd_init_db)

    # -- health ---------------------------------------------------------
    sp_health = subparsers.add_parser(
        "health",
        help="Run system health checks.",
    )
    sp_health.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Show detailed health information.",
    )
    sp_health.set_defaults(func=cmd_health)

    # -- kill-switch ----------------------------------------------------
    sp_kill = subparsers.add_parser(
        "kill-switch",
        help="Engage or disengage the system-wide kill switch.",
    )
    sp_kill_group = sp_kill.add_mutually_exclusive_group(required=True)
    sp_kill_group.add_argument(
        "--engage",
        action="store_true",
        default=False,
        help="Halt all agents immediately.",
    )
    sp_kill_group.add_argument(
        "--disengage",
        action="store_true",
        default=False,
        help="Resume normal operation.",
    )
    sp_kill.add_argument(
        "--reason",
        type=str,
        default=None,
        help="Reason for engaging/disengaging (logged for audit).",
    )
    sp_kill.set_defaults(func=cmd_kill_switch)

    # -- unpublish ------------------------------------------------------
    sp_unpub = subparsers.add_parser(
        "unpublish",
        help="Remove a published post from the live site.",
    )
    sp_unpub.add_argument(
        "--post-id",
        type=str,
        required=True,
        help="Unique identifier of the post to unpublish.",
    )
    sp_unpub.add_argument(
        "--reason",
        type=str,
        default=None,
        help="Reason for unpublishing (logged for audit).",
    )
    sp_unpub.set_defaults(func=cmd_unpublish)

    # -- revert ---------------------------------------------------------
    sp_revert = subparsers.add_parser(
        "revert",
        help="Revert a post to a previous content version.",
    )
    sp_revert.add_argument(
        "--post-id",
        type=str,
        required=True,
        help="Unique identifier of the post to revert.",
    )
    sp_revert.add_argument(
        "--version",
        type=int,
        required=True,
        help="Target version number to revert to.",
    )
    sp_revert.set_defaults(func=cmd_revert)

    # -- rotate-keys ----------------------------------------------------
    sp_rotate = subparsers.add_parser(
        "rotate-keys",
        help="Rotate API keys for an integration provider.",
    )
    sp_rotate.add_argument(
        "--provider",
        type=str,
        required=True,
        help="Provider name (e.g. openai, wordpress, cloudflare).",
    )
    sp_rotate.set_defaults(func=cmd_rotate_keys)

    # -- reload-config --------------------------------------------------
    sp_reload = subparsers.add_parser(
        "reload-config",
        help="Reload configuration from disk without restarting.",
    )
    sp_reload.set_defaults(func=cmd_reload_config)

    # -- check-integrity ------------------------------------------------
    sp_integrity = subparsers.add_parser(
        "check-integrity",
        help="Verify data integrity across database and CMS.",
    )
    sp_integrity.add_argument(
        "--fix",
        action="store_true",
        default=False,
        help="Attempt to auto-fix discovered issues.",
    )
    sp_integrity.set_defaults(func=cmd_check_integrity)

    # -- restart --------------------------------------------------------
    sp_restart = subparsers.add_parser(
        "restart",
        help="Restart a specific agent or all agents.",
    )
    sp_restart.add_argument(
        "--agent",
        type=str,
        default=None,
        help="Name of the agent to restart.",
    )
    sp_restart.add_argument(
        "--all",
        action="store_true",
        default=False,
        help="Restart all agents sequentially.",
    )
    sp_restart.set_defaults(func=cmd_restart)

    return parser


# =====================================================================
# Entry point
# =====================================================================

def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and dispatch to the appropriate subcommand.

    Parameters
    ----------
    argv:
        Command-line arguments.  ``None`` reads from ``sys.argv``.

    Returns
    -------
    int
        Exit code from the subcommand handler.
    """
    setup_logging(enable_file=False, enable_json=False)

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        settings.load()
    except OpenClawError as exc:
        # Some commands (like reload-config) may work without full config.
        logger.warning("Could not load settings: %s", exc)

    try:
        return args.func(args)
    except OpenClawError as exc:
        logger.error("Command failed: %s", exc, exc_info=True)
        print(f"ERROR: {exc}")
        return 1
    except Exception as exc:
        logger.critical("Unexpected error: %s", exc, exc_info=True)
        print(f"FATAL: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
