"""
base_agent.py - Abstract base class for all OpenClaw agents.

Every agent in the system inherits from BaseAgent and implements the
plan -> execute -> report lifecycle.  The orchestrator controller invokes
agents through the public ``run()`` method, which enforces the correct
call order, captures timing metrics, and applies uniform error handling.

Design references:
    - ARCHITECTURE.md  Section 2 (Agent Architecture)
    - AI_RULES.md      (all actions route through orchestrator)
    - config/agents.yaml  (per-agent settings: enabled, frequency, risk_level)
"""

from __future__ import annotations

import logging
import time
import traceback
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class AgentStatus(Enum):
    """Lifecycle states an agent can be in."""

    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    REPORTING = "reporting"
    COMPLETED = "completed"
    FAILED = "failed"
    DISABLED = "disabled"


@dataclass
class RunResult:
    """Immutable record of a single plan-execute-report cycle.

    Attributes:
        run_id:       Unique identifier for this run.
        agent_name:   Name of the agent that produced this result.
        status:       Terminal status after the run finished.
        started_at:   UTC timestamp when the run began.
        finished_at:  UTC timestamp when the run ended (None if still running).
        plan_output:  Data returned by ``plan()``.
        exec_output:  Data returned by ``execute()``.
        report_output: Data returned by ``report()``.
        error:        Formatted traceback string if the run failed.
        duration_s:   Wall-clock seconds for the entire run.
    """

    run_id: str
    agent_name: str
    status: AgentStatus = AgentStatus.IDLE
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    plan_output: Any = None
    exec_output: Any = None
    report_output: Any = None
    error: Optional[str] = None
    duration_s: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseAgent(ABC):
    """Abstract base class that every OpenClaw agent must extend.

    Subclasses are required to implement three methods:

    * ``plan()``    -- decide what work to do based on current state / config.
    * ``execute()`` -- carry out the planned work (call pipelines, tools, etc.).
    * ``report()``  -- log outcomes, emit metrics, and return a summary.

    The public entry-point is ``run()``, which calls the three methods in
    sequence, wraps them in timing / error-handling, and produces a
    :class:`RunResult`.

    Parameters:
        name:   Human-readable agent name (e.g. ``"research"``).
        config: Agent-specific section from ``config/agents.yaml`` merged
                with any runtime overrides supplied by the orchestrator.
    """

    def __init__(self, name: str, config: Dict[str, Any]) -> None:
        self.name = name
        self.config = config
        self.logger = logging.getLogger(f"openclaw.agent.{name}")
        self._status: AgentStatus = AgentStatus.IDLE
        self._run_history: List[RunResult] = []
        self._current_run: Optional[RunResult] = None
        self._dry_run: bool = config.get("dry_run", False)

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def plan(self) -> Any:
        """Determine the next set of actions based on current state.

        Returns:
            Arbitrary plan data that ``execute()`` will consume.  The
            concrete type is agent-specific (e.g. a list of tasks, a dict
            of research targets, etc.).
        """

    @abstractmethod
    def execute(self, plan: Any) -> Any:
        """Carry out the actions described by *plan*.

        Parameters:
            plan: The output of the preceding ``plan()`` call.

        Returns:
            Execution results whose shape is agent-specific.
        """

    @abstractmethod
    def report(self, plan: Any, result: Any) -> Any:
        """Log outcomes, emit metrics, and build a human-readable summary.

        Parameters:
            plan:   The output of ``plan()``.
            result: The output of ``execute()``.

        Returns:
            A summary dict (or similar) suitable for the orchestrator's
            audit log.
        """

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def get_status(self) -> AgentStatus:
        """Return the agent's current lifecycle status."""
        return self._status

    def is_enabled(self) -> bool:
        """Return ``True`` if this agent is enabled in its configuration.

        Disabled agents will be skipped by the scheduler.
        """
        return bool(self.config.get("enabled", True))

    @property
    def risk_level(self) -> str:
        """Return the configured risk level (``low``, ``medium``, ``high``)."""
        return str(self.config.get("risk_level", "low"))

    @property
    def max_concurrent_tasks(self) -> int:
        """Return the maximum number of concurrent tasks this agent may run."""
        return int(self.config.get("max_concurrent_tasks", 1))

    @property
    def last_run(self) -> Optional[RunResult]:
        """Return the most recent :class:`RunResult`, or ``None``."""
        return self._run_history[-1] if self._run_history else None

    @property
    def run_history(self) -> List[RunResult]:
        """Return the full list of past run results (oldest first)."""
        return list(self._run_history)

    # ------------------------------------------------------------------
    # Core lifecycle
    # ------------------------------------------------------------------

    def run(self) -> RunResult:
        """Execute the full plan -> execute -> report cycle.

        This is the **only** method the orchestrator should call.  It
        enforces ordering, captures wall-clock timing, and guarantees that
        a :class:`RunResult` is always returned -- even when an exception
        is raised inside one of the lifecycle methods.

        Returns:
            A :class:`RunResult` summarising what happened.
        """
        run_id = uuid.uuid4().hex[:12]
        result = RunResult(
            run_id=run_id,
            agent_name=self.name,
            started_at=datetime.now(timezone.utc),
        )
        self._current_run = result

        if not self.is_enabled():
            self.logger.info("Agent '%s' is disabled -- skipping run.", self.name)
            self._status = AgentStatus.DISABLED
            result.status = AgentStatus.DISABLED
            result.finished_at = datetime.now(timezone.utc)
            self._run_history.append(result)
            self._current_run = None
            return result

        start = time.monotonic()
        self.logger.info(
            "[%s] Starting run %s (dry_run=%s)",
            self.name,
            run_id,
            self._dry_run,
        )

        try:
            # --- Plan ---
            self._status = AgentStatus.PLANNING
            self.logger.debug("[%s] Planning...", self.name)
            plan_output = self.plan()
            result.plan_output = plan_output

            # --- Execute ---
            self._status = AgentStatus.EXECUTING
            self.logger.debug("[%s] Executing...", self.name)
            exec_output = self.execute(plan_output)
            result.exec_output = exec_output

            # --- Report ---
            self._status = AgentStatus.REPORTING
            self.logger.debug("[%s] Reporting...", self.name)
            report_output = self.report(plan_output, exec_output)
            result.report_output = report_output

            # --- Success ---
            self._status = AgentStatus.COMPLETED
            result.status = AgentStatus.COMPLETED

        except Exception:
            self._status = AgentStatus.FAILED
            result.status = AgentStatus.FAILED
            result.error = traceback.format_exc()
            self.logger.error(
                "[%s] Run %s failed:\n%s", self.name, run_id, result.error
            )

        finally:
            elapsed = time.monotonic() - start
            result.duration_s = round(elapsed, 3)
            result.finished_at = datetime.now(timezone.utc)
            self._run_history.append(result)
            self._current_run = None
            self.logger.info(
                "[%s] Run %s finished in %.3fs with status %s",
                self.name,
                run_id,
                result.duration_s,
                result.status.value,
            )

        return result

    # ------------------------------------------------------------------
    # Utility methods available to subclasses
    # ------------------------------------------------------------------

    def _log_metric(self, metric_name: str, value: Any) -> None:
        """Emit a structured metric line to the agent logger.

        This is a convenience wrapper that subclasses can use inside
        ``report()`` or anywhere else metrics need to be recorded.

        Parameters:
            metric_name: Dot-separated metric key (e.g. ``"articles.created"``).
            value:       Numeric or string metric value.
        """
        self.logger.info(
            "METRIC agent=%s metric=%s value=%s", self.name, metric_name, value
        )

    def _check_dry_run(self, action_description: str) -> bool:
        """Return ``True`` if dry-run mode is active, logging the skipped action.

        Subclasses should call this before any side-effectful operation::

            if self._check_dry_run("publish post to CMS"):
                return {"skipped": True, "reason": "dry_run"}

        Parameters:
            action_description: Human-readable description of the action
                that would be taken.

        Returns:
            ``True`` when in dry-run mode (caller should skip the action).
        """
        if self._dry_run:
            self.logger.info(
                "[DRY RUN] %s -- would have: %s", self.name, action_description
            )
            return True
        return False
