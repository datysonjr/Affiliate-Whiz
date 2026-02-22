"""
orchestrator.controller
~~~~~~~~~~~~~~~~~~~~~~~~

The **OrchestratorController** is the central brain of the OpenClaw system.
Every agent action -- research, content generation, publishing, analytics --
routes through this controller so that rate limiting, logging, policy
enforcement, and kill-switch checks are applied uniformly.

Key responsibilities:
    1. Agent registration and lifecycle management.
    2. Global DRY_RUN mode (AI_RULES.md, Core Constraint #2).
    3. Kill-switch (AI_RULES.md, Core Constraint #4).
    4. Delegation to the :class:`StateMachine` for state tracking.
    5. Pre-run policy checks via the policies sub-package.

Design references:
    - AI_RULES.md       (all five Core Constraints)
    - ARCHITECTURE.md   Section 3 (Orchestrator)
    - config/agents.yaml, config/thresholds.yaml
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from core.constants import (
    DEFAULT_COOLDOWN_MINUTES,
    DEFAULT_MAX_POSTS_PER_DAY,
    RiskLevel,
    TaskStatus,
)
from core.errors import (
    AgentNotRegisteredError,
    KillSwitchActiveError,
    OrchestratorError,
)
from core.logger import get_logger, log_event

from orchestrator.state_machine import StateMachine, SystemState

# Re-import so callers can use ``from orchestrator.controller import BaseAgent``
# without touching the agents package directly.
from agents.base_agent import BaseAgent, RunResult


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class AgentRecord:
    """Bookkeeping entry for a registered agent.

    Attributes
    ----------
    agent:
        The live agent instance.
    registered_at:
        UTC datetime when the agent was registered with the controller.
    run_count:
        Total number of completed runs.
    last_run_at:
        Timestamp of the most recent run, or ``None``.
    last_result:
        The most recent :class:`RunResult`, or ``None``.
    """

    agent: BaseAgent
    registered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    run_count: int = 0
    last_run_at: Optional[datetime] = None
    last_result: Optional[RunResult] = None


# ---------------------------------------------------------------------------
# OrchestratorController
# ---------------------------------------------------------------------------

class OrchestratorController:
    """Central orchestrator that manages every agent in the OpenClaw system.

    Parameters
    ----------
    dry_run:
        When ``True`` (the default for new deployments), all agents execute
        in simulation mode -- plans are computed and logged but no
        side-effects (publishing, API writes) are performed.
    config:
        Top-level configuration dict (typically loaded from YAML files).
        Individual sections are forwarded to subsystems as needed.
    """

    def __init__(
        self,
        *,
        dry_run: bool = True,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._logger: logging.Logger = get_logger("orchestrator.controller")
        self._config: Dict[str, Any] = config or {}

        # -- state --
        self._state_machine = StateMachine(entity="system")
        self._agents: Dict[str, AgentRecord] = {}
        self._dry_run: bool = dry_run
        self._kill_switch: bool = False
        self._started_at: Optional[datetime] = None
        self._stopped_at: Optional[datetime] = None

        # -- rate-limit tracking --
        self._run_timestamps: Dict[str, List[float]] = {}  # agent_name -> monotonic ts

        log_event(
            self._logger,
            "controller.init",
            dry_run=dry_run,
            kill_switch=self._kill_switch,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the orchestrator, transitioning the system to RUNNING.

        Raises
        ------
        KillSwitchActiveError
            If the kill switch is currently engaged.
        OrchestratorError
            If the system is already running or in an invalid state.
        """
        self._assert_kill_switch_off("start")

        self._state_machine.transition(
            SystemState.RUNNING,
            reason="controller.start() called",
        )
        self._started_at = datetime.now(timezone.utc)
        self._stopped_at = None

        log_event(self._logger, "controller.started", dry_run=self._dry_run)

    def stop(self) -> None:
        """Gracefully stop the orchestrator, transitioning to SHUTDOWN.

        All registered agents are left intact so that the controller can be
        restarted later without re-registration.
        """
        self._state_machine.transition(
            SystemState.SHUTDOWN,
            reason="controller.stop() called",
        )
        self._stopped_at = datetime.now(timezone.utc)

        log_event(self._logger, "controller.stopped")

    def pause(self) -> None:
        """Pause all execution without tearing down state.

        Agents currently mid-run will finish their current step but no new
        runs will be dispatched.

        Raises
        ------
        KillSwitchActiveError
            If the kill switch is engaged (use ``kill_switch_off`` first).
        """
        self._assert_kill_switch_off("pause")

        self._state_machine.transition(
            SystemState.PAUSED,
            reason="controller.pause() called",
        )
        log_event(self._logger, "controller.paused")

    def resume(self) -> None:
        """Resume from a PAUSED state back to RUNNING.

        Raises
        ------
        KillSwitchActiveError
            If the kill switch is engaged.
        """
        self._assert_kill_switch_off("resume")

        self._state_machine.transition(
            SystemState.RUNNING,
            reason="controller.resume() called",
        )
        log_event(self._logger, "controller.resumed")

    # ------------------------------------------------------------------
    # Kill switch
    # ------------------------------------------------------------------

    def kill_switch_on(self, *, reason: str = "manual") -> None:
        """Engage the kill switch, immediately halting all dispatching.

        When the kill switch is active every call to :meth:`run_agent` will
        raise :class:`KillSwitchActiveError`.

        Parameters
        ----------
        reason:
            Explanation for why the kill switch was activated.
        """
        self._kill_switch = True

        # Try to transition to ERROR -- acceptable even if already there.
        if self._state_machine.can_transition(SystemState.ERROR):
            self._state_machine.transition(
                SystemState.ERROR,
                reason=f"kill_switch_on: {reason}",
            )

        log_event(
            self._logger,
            "controller.kill_switch_on",
            reason=reason,
            level=logging.CRITICAL,
        )

    def kill_switch_off(self, *, reason: str = "manual") -> None:
        """Disengage the kill switch, allowing operations to resume.

        The system transitions back to IDLE; call :meth:`start` to begin
        dispatching again.

        Parameters
        ----------
        reason:
            Explanation for why the kill switch was deactivated.
        """
        self._kill_switch = False

        # Attempt to return to IDLE from ERROR.
        if self._state_machine.can_transition(SystemState.IDLE):
            self._state_machine.transition(
                SystemState.IDLE,
                reason=f"kill_switch_off: {reason}",
            )

        log_event(
            self._logger,
            "controller.kill_switch_off",
            reason=reason,
            level=logging.WARNING,
        )

    # ------------------------------------------------------------------
    # Agent registration
    # ------------------------------------------------------------------

    def register_agent(self, agent: BaseAgent) -> None:
        """Register an agent with the controller.

        An agent **must** be registered before it can be dispatched via
        :meth:`run_agent`.  Registering the same agent name twice is
        idempotent -- the existing record is replaced.

        Parameters
        ----------
        agent:
            A fully-constructed :class:`BaseAgent` subclass instance.
        """
        record = AgentRecord(agent=agent)
        self._agents[agent.name] = record
        self._run_timestamps.setdefault(agent.name, [])

        log_event(
            self._logger,
            "controller.agent_registered",
            agent=agent.name,
            risk_level=agent.risk_level,
        )

    # ------------------------------------------------------------------
    # Agent execution
    # ------------------------------------------------------------------

    def run_agent(self, agent_name: str) -> RunResult:
        """Run a registered agent through its full lifecycle.

        Performs the following checks **before** dispatching:
            1. Kill switch is off.
            2. System is in RUNNING state.
            3. Agent is registered.
            4. Agent is enabled.
            5. Rate-limit / cooldown has elapsed.
            6. DRY_RUN flag is propagated to the agent.

        Parameters
        ----------
        agent_name:
            Name of a previously-registered agent.

        Returns
        -------
        RunResult
            The result produced by the agent's ``run()`` method.

        Raises
        ------
        KillSwitchActiveError
            If the kill switch is engaged.
        OrchestratorError
            If the system is not in RUNNING state.
        AgentNotRegisteredError
            If *agent_name* has not been registered.
        """
        self._assert_kill_switch_off(f"run_agent({agent_name})")
        self._assert_running(f"run_agent({agent_name})")

        if agent_name not in self._agents:
            raise AgentNotRegisteredError(
                f"Agent '{agent_name}' is not registered with the controller.",
                details={"agent": agent_name, "registered": list(self._agents.keys())},
            )

        record = self._agents[agent_name]
        agent = record.agent

        if not agent.is_enabled():
            self._logger.info("Agent '%s' is disabled -- skipping.", agent_name)
            result = RunResult(
                run_id="skipped",
                agent_name=agent_name,
                status=TaskStatus.SKIPPED,  # type: ignore[arg-type]
                started_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
            )
            return result

        # Enforce cooldown between runs of the same agent.
        cooldown_s = self._get_agent_cooldown_seconds(agent_name)
        if not self._cooldown_elapsed(agent_name, cooldown_s):
            self._logger.info(
                "Agent '%s' is within its cooldown period (%ds) -- skipping.",
                agent_name,
                cooldown_s,
            )
            result = RunResult(
                run_id="cooldown",
                agent_name=agent_name,
                status=TaskStatus.SKIPPED,  # type: ignore[arg-type]
                started_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
            )
            return result

        # Propagate DRY_RUN flag to the agent.
        agent._dry_run = self._dry_run  # noqa: SLF001

        log_event(
            self._logger,
            "controller.agent_run_start",
            agent=agent_name,
            dry_run=self._dry_run,
        )

        # Dispatch
        run_result = agent.run()

        # Book-keeping
        now = time.monotonic()
        self._run_timestamps[agent_name].append(now)
        record.run_count += 1
        record.last_run_at = datetime.now(timezone.utc)
        record.last_result = run_result

        log_event(
            self._logger,
            "controller.agent_run_end",
            agent=agent_name,
            status=str(run_result.status),
            duration_s=run_result.duration_s,
        )

        return run_result

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def is_dry_run(self) -> bool:
        """Return ``True`` if the controller is operating in DRY_RUN mode.

        In DRY_RUN mode agents plan and log but do not perform any
        side-effects (no publishing, no API writes).

        Returns
        -------
        bool
        """
        return self._dry_run

    def get_status(self) -> Dict[str, Any]:
        """Return a comprehensive snapshot of the controller's current status.

        The dict includes system state, kill-switch flag, DRY_RUN flag,
        registered agents and their last-run info, and uptime.

        Returns
        -------
        dict[str, Any]
            JSON-serialisable status dict.
        """
        now_utc = datetime.now(timezone.utc)
        uptime_s: Optional[float] = None
        if self._started_at is not None and self._stopped_at is None:
            uptime_s = (now_utc - self._started_at).total_seconds()

        agent_summaries: Dict[str, Any] = {}
        for name, rec in self._agents.items():
            agent_summaries[name] = {
                "enabled": rec.agent.is_enabled(),
                "risk_level": rec.agent.risk_level,
                "run_count": rec.run_count,
                "last_run_at": rec.last_run_at.isoformat() if rec.last_run_at else None,
                "last_status": (
                    str(rec.last_result.status) if rec.last_result else None
                ),
            }

        return {
            "system_state": str(self._state_machine.get_state()),
            "kill_switch": self._kill_switch,
            "dry_run": self._dry_run,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "uptime_seconds": uptime_s,
            "registered_agents": len(self._agents),
            "agents": agent_summaries,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _assert_kill_switch_off(self, action: str) -> None:
        """Raise :class:`KillSwitchActiveError` if the switch is engaged."""
        if self._kill_switch:
            raise KillSwitchActiveError(
                f"Kill switch is active -- cannot perform '{action}'.",
                details={"action": action},
            )

    def _assert_running(self, action: str) -> None:
        """Raise :class:`OrchestratorError` if the system is not RUNNING."""
        current = self._state_machine.get_state()
        if current != SystemState.RUNNING:
            raise OrchestratorError(
                f"System is in '{current}' state -- cannot perform '{action}'. "
                f"Call start() first.",
                details={"current_state": str(current), "action": action},
            )

    def _get_agent_cooldown_seconds(self, agent_name: str) -> int:
        """Look up cooldown for *agent_name* from config, falling back to default."""
        agents_cfg = self._config.get("agents", {})
        agent_cfg = agents_cfg.get(agent_name, {})
        cooldown_min = agent_cfg.get("cooldown_minutes", DEFAULT_COOLDOWN_MINUTES)
        return int(cooldown_min) * 60

    def _cooldown_elapsed(self, agent_name: str, cooldown_s: int) -> bool:
        """Return ``True`` if enough time has passed since the agent's last run."""
        timestamps = self._run_timestamps.get(agent_name, [])
        if not timestamps:
            return True
        elapsed = time.monotonic() - timestamps[-1]
        return elapsed >= cooldown_s

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"OrchestratorController("
            f"state={self._state_machine.get_state()!s}, "
            f"dry_run={self._dry_run}, "
            f"kill_switch={self._kill_switch}, "
            f"agents={len(self._agents)})"
        )
