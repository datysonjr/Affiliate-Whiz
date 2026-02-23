"""
main.py
~~~~~~~

Entry point for the OpenClaw affiliate marketing automation system.

Starts the orchestrator controller, registers all agents, and runs
the scheduler loop.  Supports DRY_RUN mode (default) where no
side-effects occur.

Usage::

    # Start in dry-run mode (default, safe)
    python -m src.main --node-role core --dry-run

    # Start with a specific pipeline only
    python -m src.main --node-role core --dry-run --pipeline content

    # Override log level
    python -m src.main --node-role core --dry-run --log-level DEBUG
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
from typing import NoReturn

from src.core.constants import (
    APP_NAME,
    APP_VERSION,
    AgentName,
    DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    NodeRole,
)
from src.core.errors import KillSwitchActiveError, OpenClawError
from src.core.logger import get_logger, log_event, setup_logging
from src.core.settings import settings
from src.data.db import Database

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

logger = get_logger("main")
_shutdown_event = threading.Event()


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------


def _handle_shutdown_signal(signum: int, _frame: object) -> None:
    sig_name = signal.Signals(signum).name
    log_event(logger, "shutdown.signal_received", signal=sig_name)
    logger.info("Received %s -- initiating graceful shutdown...", sig_name)
    _shutdown_event.set()


def install_signal_handlers() -> None:
    signal.signal(signal.SIGINT, _handle_shutdown_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_shutdown_signal)


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------


def _create_agents(dry_run: bool, pipeline_filter: str = "", real_agents: bool = False):
    """Create and return agent instances for the current node role.

    Parameters
    ----------
    dry_run:
        When True, agents will skip real side-effects.
    pipeline_filter:
        Restrict to a specific pipeline ("content", "publishing", "analytics").
    real_agents:
        When True, instantiate real agent classes from src/agents/*.py that
        use LLMTool, CMSTool, etc.  When False (default), use lightweight
        Local* stubs that simulate the flow without real integrations.
    """

    # Build agent config with dry_run flag
    base_config: dict = {"enabled": True, "dry_run": dry_run, "risk_level": "low"}

    if real_agents:
        return _create_real_agents(base_config, pipeline_filter)

    return _create_stub_agents(base_config, pipeline_filter)


def _create_real_agents(base_config: dict, pipeline_filter: str = "") -> list:
    """Instantiate real agent classes that use actual tools (LLM, CMS, etc.).

    These agents are from src/agents/*.py and will make real API calls
    when not in dry-run mode.
    """
    import os

    from src.agents.research_agent import ResearchAgent
    from src.agents.content_generation_agent import ContentGenerationAgent
    from src.agents.publishing_agent import PublishingAgent
    from src.agents.analytics_agent import AnalyticsAgent
    from src.agents.health_monitor_agent import HealthMonitorAgent
    from src.agents.error_recovery_agent import ErrorRecoveryAgent

    # Research agent config
    research_config = {
        **base_config,
        "niches": ["tech accessories", "home office"],
        "seed_keywords": ["wireless earbuds", "standing desk", "ergonomic keyboard"],
        "max_keywords": 50,
        "competitor_domains": [],
        "research_depth": "normal",
    }

    # Content generation config (LLMTool reads keys from env)
    content_config = {
        **base_config,
        "max_articles_per_run": 3,
        "target_word_count": 1500,
        "quality_threshold": 0.7,
        "default_topics": [
            "best wireless earbuds 2026",
            "home office desk setup guide",
        ],
    }

    # Publishing config (CMSTool reads keys from env)
    publishing_config = {
        **base_config,
        "max_posts_per_day": 5,
        "cadence_per_day": 3,
        "cooldown_minutes": 0,
        "target_site": os.environ.get("WP_STAGING_BASE_URL", "staging.example.com"),
        "cms_api_base_url": os.environ.get(
            "WP_STAGING_BASE_URL",
            "http://localhost:8080/wp-json/wp/v2",
        ),
    }

    # Analytics config
    analytics_config = {
        **base_config,
        "sites": ["default"],
    }

    # Health monitor config
    health_config = {
        **base_config,
    }

    # Error recovery config
    error_config = {
        **base_config,
    }

    # Map pipeline names to agent sets
    pipeline_agents: dict[str, list] = {
        "": [  # all agents
            ResearchAgent(config=research_config),
            ContentGenerationAgent(config=content_config),
            PublishingAgent(config=publishing_config),
            AnalyticsAgent(config=analytics_config),
            HealthMonitorAgent(config=health_config),
            ErrorRecoveryAgent(config=error_config),
        ],
        "content": [
            ResearchAgent(config=research_config),
            ContentGenerationAgent(config=content_config),
        ],
        "publishing": [
            PublishingAgent(config=publishing_config),
        ],
        "analytics": [
            AnalyticsAgent(config=analytics_config),
        ],
    }

    agents = pipeline_agents.get(pipeline_filter, pipeline_agents[""])
    logger.info(
        "Created %d REAL agent(s) for pipeline=%s",
        len(agents),
        pipeline_filter or "all",
    )
    return agents


def _create_stub_agents(base_config: dict, pipeline_filter: str = "") -> list:
    """Create lightweight stub agents that simulate the flow without real integrations."""
    from src.agents.base_agent import BaseAgent

    class LocalResearchAgent(BaseAgent):
        def plan(self):
            self.logger.info("[%s] Planning: scan for niche opportunities", self.name)
            return {
                "keywords": ["best wireless earbuds 2025", "home office desk setup"],
                "niches": ["tech accessories"],
            }

        def execute(self, plan):
            self.logger.info(
                "[%s] Executing: researching %d keywords",
                self.name,
                len(plan["keywords"]),
            )
            if self._check_dry_run("call SERP API"):
                return {
                    "offers_found": 5,
                    "keywords_analyzed": len(plan["keywords"]),
                    "dry_run": True,
                }
            return {"offers_found": 5, "keywords_analyzed": len(plan["keywords"])}

        def report(self, plan, result):
            self._log_metric("keywords.analyzed", result["keywords_analyzed"])
            self._log_metric("offers.found", result.get("offers_found", 0))
            return {
                "summary": f"Researched {result['keywords_analyzed']} keywords, found {result.get('offers_found', 0)} offers"
            }

    class LocalContentAgent(BaseAgent):
        def plan(self):
            self.logger.info(
                "[%s] Planning: generate content from approved briefs", self.name
            )
            return {
                "briefs": [
                    {
                        "title": "Top 5 Wireless Earbuds for 2025",
                        "type": "roundup",
                        "target_words": 1500,
                    }
                ]
            }

        def execute(self, plan):
            self.logger.info(
                "[%s] Executing: drafting %d articles", self.name, len(plan["briefs"])
            )
            if self._check_dry_run("call LLM API for content generation"):
                return {
                    "articles_drafted": len(plan["briefs"]),
                    "total_words": 1500,
                    "dry_run": True,
                }
            return {"articles_drafted": len(plan["briefs"]), "total_words": 1500}

        def report(self, plan, result):
            self._log_metric("articles.drafted", result["articles_drafted"])
            self._log_metric("words.written", result["total_words"])
            return {
                "summary": f"Drafted {result['articles_drafted']} articles ({result['total_words']} words)"
            }

    class LocalPublishingAgent(BaseAgent):
        def plan(self):
            self.logger.info("[%s] Planning: check approved content queue", self.name)
            return {"posts_ready": 1, "target_site": "example-niche.com"}

        def execute(self, plan):
            self.logger.info(
                "[%s] Executing: publishing %d posts", self.name, plan["posts_ready"]
            )
            if self._check_dry_run("publish to WordPress CMS"):
                return {"published": 0, "skipped": plan["posts_ready"], "dry_run": True}
            return {"published": plan["posts_ready"], "skipped": 0}

        def report(self, plan, result):
            self._log_metric("posts.published", result.get("published", 0))
            self._log_metric("posts.skipped", result.get("skipped", 0))
            return {
                "summary": f"Published {result.get('published', 0)}, skipped {result.get('skipped', 0)}"
            }

    class LocalAnalyticsAgent(BaseAgent):
        def plan(self):
            self.logger.info("[%s] Planning: collect performance metrics", self.name)
            return {"sites": ["example-niche.com"], "period": "24h"}

        def execute(self, plan):
            self.logger.info(
                "[%s] Executing: gathering analytics for %d sites",
                self.name,
                len(plan["sites"]),
            )
            if self._check_dry_run("query analytics APIs"):
                return {"pageviews": 0, "clicks": 0, "revenue": 0.0, "dry_run": True}
            return {"pageviews": 142, "clicks": 23, "revenue": 4.50}

        def report(self, plan, result):
            self._log_metric("pageviews", result.get("pageviews", 0))
            self._log_metric("clicks", result.get("clicks", 0))
            self._log_metric("revenue_usd", result.get("revenue", 0.0))
            return {
                "summary": f"Traffic: {result.get('pageviews', 0)} PV, {result.get('clicks', 0)} clicks, ${result.get('revenue', 0.0):.2f} revenue"
            }

    # Map pipeline names to agent sets
    pipeline_agents: dict[str, list[tuple[str, type[BaseAgent]]]] = {
        "": [
            (AgentName.RESEARCH.value, LocalResearchAgent),
            (AgentName.CONTENT_GENERATION.value, LocalContentAgent),
            (AgentName.PUBLISHING.value, LocalPublishingAgent),
            (AgentName.ANALYTICS.value, LocalAnalyticsAgent),
        ],
        "content": [
            (AgentName.RESEARCH.value, LocalResearchAgent),
            (AgentName.CONTENT_GENERATION.value, LocalContentAgent),
        ],
        "publishing": [
            (AgentName.PUBLISHING.value, LocalPublishingAgent),
        ],
        "analytics": [
            (AgentName.ANALYTICS.value, LocalAnalyticsAgent),
        ],
    }

    agent_list = pipeline_agents.get(pipeline_filter, pipeline_agents[""])
    agents = []
    for name, cls in agent_list:
        agents.append(cls(name=name, config={**base_config}))

    return agents


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def main_loop(
    node_role: NodeRole,
    dry_run: bool = True,
    heartbeat_interval: int = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    pipeline: str = "",
    max_ticks: int = 0,
    real_agents: bool = False,
) -> int:
    """Run the orchestrator controller's main loop.

    Parameters
    ----------
    max_ticks:
        If > 0, exit after this many ticks (useful for testing).
        0 means run forever until shutdown signal.
    real_agents:
        If True, use real agent classes with actual tool integrations.
        If False (default), use lightweight stub agents.
    """
    from src.orchestrator.controller import OrchestratorController

    # Initialize database
    db = Database()
    db.connect()
    migrations_applied = db.migrate()
    if migrations_applied:
        logger.info("Applied %d database migration(s)", migrations_applied)

    # Create controller
    controller = OrchestratorController(dry_run=dry_run)

    # Create and register agents
    agents = _create_agents(
        dry_run=dry_run, pipeline_filter=pipeline, real_agents=real_agents
    )
    for agent in agents:
        controller.register_agent(agent)

    agent_names = [a.name for a in agents]
    log_event(
        logger,
        "main_loop.starting",
        node_role=node_role.value,
        dry_run=dry_run,
        agents=agent_names,
        heartbeat_interval=heartbeat_interval,
    )

    # Start controller
    controller.start()

    tick_count = 0
    agent_sequence = agent_names  # Run agents in registration order

    agent_mode = "REAL" if real_agents else "STUB"
    print(f"\n{'=' * 60}")
    print(f"  {APP_NAME} v{APP_VERSION} -- Local Dev Mode")
    print(f"  Node role: {node_role.value}")
    print(f"  DRY_RUN: {dry_run}")
    print(f"  Agents: {agent_mode} ({', '.join(agent_names)})")
    print(f"  Heartbeat: {heartbeat_interval}s")
    if max_ticks:
        print(f"  Max ticks: {max_ticks}")
    print(f"{'=' * 60}\n")

    try:
        while not _shutdown_event.is_set():
            tick_count += 1
            logger.info("--- Heartbeat tick #%d ---", tick_count)

            # Run each agent in sequence
            for agent_name in agent_sequence:
                if _shutdown_event.is_set():
                    break
                try:
                    result = controller.run_agent(agent_name)

                    # Record run to database
                    try:
                        db.execute(
                            """INSERT INTO agent_runs
                               (run_id, agent_name, status, dry_run, duration_s,
                                plan_output, exec_output, report_output, error,
                                started_at, finished_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                result.run_id,
                                result.agent_name,
                                result.status.value
                                if hasattr(result.status, "value")
                                else str(result.status),
                                1 if dry_run else 0,
                                result.duration_s,
                                json.dumps(result.plan_output, default=str)
                                if result.plan_output
                                else None,
                                json.dumps(result.exec_output, default=str)
                                if result.exec_output
                                else None,
                                json.dumps(result.report_output, default=str)
                                if result.report_output
                                else None,
                                result.error,
                                result.started_at.isoformat()
                                if result.started_at
                                else None,
                                result.finished_at.isoformat()
                                if result.finished_at
                                else None,
                            ),
                        )
                    except Exception as db_err:
                        logger.warning("Failed to record run to DB: %s", db_err)

                    status_str = (
                        result.status.value
                        if hasattr(result.status, "value")
                        else str(result.status)
                    )
                    logger.info(
                        "Agent '%s' completed: status=%s duration=%.3fs",
                        agent_name,
                        status_str,
                        result.duration_s,
                    )

                except KillSwitchActiveError:
                    logger.warning("Kill switch active -- halting.")
                    _shutdown_event.set()
                    break
                except OpenClawError as exc:
                    logger.error("Agent '%s' error: %s", agent_name, exc)

            # Check max_ticks limit
            if max_ticks and tick_count >= max_ticks:
                logger.info("Reached max_ticks=%d -- shutting down.", max_ticks)
                break

            # Sleep until next tick (interruptible)
            _shutdown_event.wait(timeout=heartbeat_interval)

    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt -- shutting down.")

    # Cleanup
    controller.stop()
    db.disconnect()

    log_event(logger, "main_loop.stopped", ticks_completed=tick_count)
    print(f"\nShutdown complete after {tick_count} tick(s).")
    return 0


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openclaw",
        description=f"{APP_NAME} v{APP_VERSION} -- Affiliate Marketing Automation System",
    )
    parser.add_argument(
        "--version", action="version", version=f"{APP_NAME} {APP_VERSION}"
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
        default="core",
        help="Role of this node (default: core).",
    )
    parser.add_argument(
        "--pipeline",
        type=str,
        default="",
        choices=["", "content", "publishing", "analytics"],
        help="Run only agents for a specific pipeline.",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Override the log level.",
    )
    parser.add_argument(
        "--heartbeat-interval",
        type=int,
        default=DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
        help=f"Seconds between heartbeat ticks (default: {DEFAULT_HEARTBEAT_INTERVAL_SECONDS}).",
    )
    parser.add_argument(
        "--max-ticks",
        type=int,
        default=0,
        help="Exit after N ticks (0 = run forever). Useful for testing.",
    )
    parser.add_argument(
        "--real-agents",
        action="store_true",
        default=False,
        help="Use real agent classes with actual tool integrations (LLM, CMS, etc.).",
    )
    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> NoReturn:
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    # -- Logging
    setup_logging(level=args.log_level, enable_file=True, enable_json=True)

    logger.info(
        "Starting %s v%s  node_role=%s  dry_run=%s  pipeline=%s",
        APP_NAME,
        APP_VERSION,
        args.node_role,
        args.dry_run,
        args.pipeline or "all",
    )

    # -- Settings
    try:
        settings.load()
        logger.info("Configuration loaded: %s", settings)
    except OpenClawError as exc:
        logger.warning("Config load issue (non-fatal for local dev): %s", exc)

    # -- Signals
    install_signal_handlers()

    # -- Main loop
    node_role = NodeRole(args.node_role)
    exit_code = main_loop(
        node_role=node_role,
        dry_run=args.dry_run,
        heartbeat_interval=args.heartbeat_interval,
        pipeline=args.pipeline,
        max_ticks=args.max_ticks,
        real_agents=args.real_agents,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
