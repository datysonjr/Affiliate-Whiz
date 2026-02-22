"""
main.py
~~~~~~~

Entry point for the OpenClaw affiliate marketing automation system.

Responsibilities
----------------
* Parse command-line arguments (``--dry-run``, ``--node-role``, ``--log-level``).
* Install signal handlers for graceful shutdown (SIGINT, SIGTERM).
* Initialise logging and settings.
* Start the orchestrator controller's main loop.

Usage::

    # Start the core node in normal mode
    python -m src.main --node-role core

    # Start the publisher node in dry-run mode
    python -m src.main --node-role pub --dry-run

    # Override log level
    python -m src.main --node-role core --log-level DEBUG

Design notes
------------
* The main loop is intentionally simple: it delegates all scheduling,
  routing, and agent management to the orchestrator controller.
* ``--dry-run`` propagates to every agent so that no side-effects
  (publishing, DNS changes, API calls) occur during validation runs.
* Signal handlers set a threading ``Event`` so the main loop exits
  cleanly without killing in-flight work.
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
from typing import NoReturn

from src.core.constants import APP_NAME, APP_VERSION, DEFAULT_HEARTBEAT_INTERVAL_SECONDS, NodeRole
from src.core.errors import KillSwitchActiveError, OpenClawError
from src.core.logger import get_logger, log_event, setup_logging
from src.core.settings import settings

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

logger = get_logger("main")

# Threading event used to signal graceful shutdown from signal handlers.
_shutdown_event = threading.Event()


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------

def _handle_shutdown_signal(signum: int, _frame: object) -> None:
    """Set the shutdown event when SIGINT or SIGTERM is received.

    This allows the main loop to finish its current iteration and exit
    cleanly rather than being killed mid-operation.

    Parameters
    ----------
    signum:
        The signal number (e.g. ``signal.SIGINT``).
    _frame:
        Current stack frame (unused).
    """
    sig_name = signal.Signals(signum).name
    log_event(logger, "shutdown.signal_received", signal=sig_name)
    logger.info("Received %s -- initiating graceful shutdown...", sig_name)
    _shutdown_event.set()


def install_signal_handlers() -> None:
    """Register handlers for SIGINT and SIGTERM.

    On Windows, only SIGINT (Ctrl-C) is reliably supported.
    """
    signal.signal(signal.SIGINT, _handle_shutdown_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_shutdown_signal)
    logger.debug("Signal handlers installed for SIGINT/SIGTERM")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def build_argument_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser for the main entry point.

    Returns
    -------
    argparse.ArgumentParser
        Fully configured parser.
    """
    parser = argparse.ArgumentParser(
        prog="openclaw",
        description=f"{APP_NAME} v{APP_VERSION} -- Affiliate Marketing Automation System",
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
        help="Run all agents in dry-run mode (no side-effects).",
    )
    parser.add_argument(
        "--node-role",
        type=str,
        choices=[r.value for r in NodeRole],
        required=True,
        help="Role of this node in the cluster topology (core | pub).",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Override the log level (default: from settings / INFO).",
    )
    parser.add_argument(
        "--config-dir",
        type=str,
        default=None,
        help="Override the configuration directory path.",
    )
    parser.add_argument(
        "--heartbeat-interval",
        type=int,
        default=DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
        help=(
            f"Seconds between heartbeat ticks in the main loop "
            f"(default: {DEFAULT_HEARTBEAT_INTERVAL_SECONDS})."
        ),
    )
    return parser


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main_loop(
    node_role: NodeRole,
    dry_run: bool = False,
    heartbeat_interval: int = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
) -> int:
    """Run the orchestrator controller's main loop.

    The loop ticks every *heartbeat_interval* seconds.  On each tick it
    asks the orchestrator controller to evaluate the schedule, dispatch
    due agents, and collect results.  The loop exits cleanly when the
    shutdown event is set (via signal handler or kill switch).

    Parameters
    ----------
    node_role:
        Which cluster role this process fulfils.
    dry_run:
        If ``True``, all agents run in dry-run mode.
    heartbeat_interval:
        Seconds to sleep between ticks.

    Returns
    -------
    int
        Exit code: ``0`` for clean shutdown, ``1`` for error.
    """
    log_event(
        logger,
        "main_loop.starting",
        node_role=node_role.value,
        dry_run=dry_run,
        heartbeat_interval=heartbeat_interval,
    )

    # TODO: Replace with real OrchestratorController instantiation once
    #       orchestrator/controller.py is implemented.
    # from src.orchestrator.controller import OrchestratorController
    # controller = OrchestratorController(
    #     node_role=node_role,
    #     dry_run=dry_run,
    #     settings=settings,
    # )
    # controller.initialize()

    tick_count = 0

    try:
        while not _shutdown_event.is_set():
            tick_count += 1
            logger.debug("Heartbeat tick #%d", tick_count)

            try:
                # TODO: Replace with controller.tick() once implemented.
                # controller.tick()
                pass

            except KillSwitchActiveError:
                logger.warning("Kill switch is active -- halting main loop.")
                break
            except OpenClawError as exc:
                logger.error(
                    "OpenClaw error during tick #%d: %s", tick_count, exc,
                    exc_info=True,
                )
                # Continue running -- the orchestrator should self-heal.

            # Sleep in small increments so we can react to shutdown quickly.
            _interruptible_sleep(heartbeat_interval)

    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt caught -- shutting down.")

    log_event(logger, "main_loop.stopped", ticks_completed=tick_count)
    logger.info("Main loop exited after %d ticks.", tick_count)

    # TODO: controller.shutdown()
    return 0


def _interruptible_sleep(seconds: int) -> None:
    """Sleep for *seconds*, but wake up early if the shutdown event fires.

    Parameters
    ----------
    seconds:
        Maximum number of seconds to sleep.
    """
    _shutdown_event.wait(timeout=seconds)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> NoReturn:
    """Parse arguments, set up the system, and run the main loop.

    Parameters
    ----------
    argv:
        Command-line arguments.  ``None`` reads from ``sys.argv``.
    """
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    # -- Logging ----------------------------------------------------------
    setup_logging(
        level=args.log_level,
        enable_file=True,
        enable_json=True,
    )

    logger.info(
        "Starting %s v%s  node_role=%s  dry_run=%s",
        APP_NAME,
        APP_VERSION,
        args.node_role,
        args.dry_run,
    )

    # -- Settings ---------------------------------------------------------
    try:
        settings.load()
        logger.info("Configuration loaded: %s", settings)
    except OpenClawError as exc:
        logger.critical("Failed to load configuration: %s", exc)
        sys.exit(2)

    # -- Signal handlers --------------------------------------------------
    install_signal_handlers()

    # -- Main loop --------------------------------------------------------
    node_role = NodeRole(args.node_role)
    exit_code = main_loop(
        node_role=node_role,
        dry_run=args.dry_run,
        heartbeat_interval=args.heartbeat_interval,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
