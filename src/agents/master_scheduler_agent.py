"""
agents.master_scheduler_agent
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The MasterSchedulerAgent is the top-level coordinator that creates daily and
weekly task lists based on the system configuration.  It reads schedule
definitions from ``config/schedules.yaml``, determines which agents need to
run, and dispatches tasks to the orchestrator's task queue.

Design references:
    - ARCHITECTURE.md  Section 2 (Agent Architecture)
    - config/schedules.yaml  (cron-like schedule definitions)
    - config/agents.yaml     (per-agent enabled/frequency settings)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, unique
from typing import Any, Dict, List, Optional

from src.agents.base_agent import BaseAgent
from src.core.constants import (
    AgentName,
    DEFAULT_SCHEDULER_INTERVAL_SECONDS,
    TaskStatus,
)
from src.core.logger import log_event


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@unique
class ScheduleFrequency(str, Enum):
    """How often a scheduled task should fire."""

    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    ON_DEMAND = "on_demand"


@dataclass
class ScheduledTask:
    """A single task the scheduler intends to dispatch.

    Attributes:
        task_id:        Unique identifier for tracking.
        target_agent:   Which agent should handle this task.
        action:         The action name the agent should perform.
        priority:       Numeric priority (lower = higher priority).
        frequency:      How often this task recurs.
        parameters:     Arbitrary kwargs forwarded to the target agent.
        scheduled_at:   When the scheduler created this task.
        status:         Current dispatch status.
    """

    task_id: str
    target_agent: str
    action: str
    priority: int = 50
    frequency: ScheduleFrequency = ScheduleFrequency.DAILY
    parameters: Dict[str, Any] = field(default_factory=dict)
    scheduled_at: Optional[datetime] = None
    status: TaskStatus = TaskStatus.PENDING
    dispatch_result: Optional[str] = None


@dataclass
class SchedulePlan:
    """Output of the planning phase -- a prioritised list of tasks to dispatch.

    Attributes:
        plan_timestamp: UTC time the plan was generated.
        tasks:          Ordered list of tasks (highest priority first).
        skipped_agents: Agents that were skipped (disabled, on cooldown, etc.).
        schedule_window_start: Start of the evaluation window.
        schedule_window_end:   End of the evaluation window.
    """

    plan_timestamp: datetime
    tasks: List[ScheduledTask] = field(default_factory=list)
    skipped_agents: List[str] = field(default_factory=list)
    schedule_window_start: Optional[datetime] = None
    schedule_window_end: Optional[datetime] = None


@dataclass
class DispatchSummary:
    """Aggregated results after all tasks have been dispatched.

    Attributes:
        dispatched:  Number of tasks successfully queued.
        failed:      Number of tasks that could not be dispatched.
        skipped:     Number of tasks intentionally skipped.
        details:     Per-task dispatch outcomes.
    """

    dispatched: int = 0
    failed: int = 0
    skipped: int = 0
    details: List[Dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent implementation
# ---------------------------------------------------------------------------


class MasterSchedulerAgent(BaseAgent):
    """Creates daily/weekly task lists and dispatches them to other agents.

    The scheduler reads agent configurations to decide which agents are due
    to run, builds a prioritised task list, then dispatches each task to the
    orchestrator's routing layer.  It deliberately does **not** execute agent
    logic itself -- it only schedules and monitors dispatch outcomes.

    Configuration keys (from ``config/agents.yaml`` under ``master_scheduler``):
        enabled:            bool -- whether the scheduler is active.
        interval_seconds:   int  -- minimum seconds between schedule cycles.
        max_tasks_per_cycle: int -- cap on tasks dispatched in one run.
        agent_schedules:    dict -- per-agent schedule overrides.
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        super().__init__(name=str(AgentName.MASTER_SCHEDULER), config=config)
        self._interval_seconds: int = config.get(
            "interval_seconds", DEFAULT_SCHEDULER_INTERVAL_SECONDS
        )
        self._max_tasks_per_cycle: int = config.get("max_tasks_per_cycle", 20)
        self._agent_schedules: Dict[str, Dict[str, Any]] = config.get(
            "agent_schedules", {}
        )
        self._last_schedule_time: Optional[datetime] = None
        self._task_counter: int = 0
        self._dispatch_registry: Dict[str, ScheduledTask] = {}

    # ------------------------------------------------------------------
    # BaseAgent lifecycle
    # ------------------------------------------------------------------

    def plan(self) -> SchedulePlan:
        """Evaluate schedules and build a prioritised task list.

        Iterates over all registered agents, checks whether each is due
        according to its configured frequency, and collects tasks into a
        :class:`SchedulePlan`.

        Returns:
            A :class:`SchedulePlan` containing the ordered task list.
        """
        now = datetime.now(timezone.utc)
        plan = SchedulePlan(
            plan_timestamp=now,
            schedule_window_start=self._last_schedule_time or now,
            schedule_window_end=now,
        )

        log_event(
            self.logger, "scheduler.plan.start", window_start=plan.schedule_window_start
        )

        # Evaluate each agent's schedule
        for agent_name in AgentName:
            if agent_name == AgentName.MASTER_SCHEDULER:
                continue  # The scheduler does not schedule itself

            agent_cfg = self._agent_schedules.get(str(agent_name), {})
            if not agent_cfg.get("enabled", True):
                plan.skipped_agents.append(str(agent_name))
                self.logger.debug("Skipping disabled agent: %s", agent_name)
                continue

            if not self._is_agent_due(str(agent_name), agent_cfg, now):
                self.logger.debug("Agent %s is not due yet.", agent_name)
                continue

            tasks = self._build_tasks_for_agent(str(agent_name), agent_cfg, now)
            plan.tasks.extend(tasks)

        # Sort by priority (ascending -- lower number = higher priority)
        plan.tasks.sort(key=lambda t: t.priority)

        # Apply per-cycle cap
        if len(plan.tasks) > self._max_tasks_per_cycle:
            self.logger.warning(
                "Task count %d exceeds max_tasks_per_cycle %d; truncating.",
                len(plan.tasks),
                self._max_tasks_per_cycle,
            )
            plan.tasks = plan.tasks[: self._max_tasks_per_cycle]

        log_event(
            self.logger,
            "scheduler.plan.complete",
            task_count=len(plan.tasks),
            skipped_agents=len(plan.skipped_agents),
        )
        return plan

    def execute(self, plan: SchedulePlan) -> DispatchSummary:
        """Dispatch each planned task to the orchestrator's task queue.

        Parameters:
            plan: The :class:`SchedulePlan` produced by ``plan()``.

        Returns:
            A :class:`DispatchSummary` with per-task outcomes.
        """
        summary = DispatchSummary()

        for task in plan.tasks:
            if self._check_dry_run(
                f"dispatch task {task.task_id} to {task.target_agent}"
            ):
                task.status = TaskStatus.SKIPPED
                task.dispatch_result = "dry_run"
                summary.skipped += 1
                summary.details.append(self._task_detail(task))
                continue

            try:
                self._dispatch_task(task)
                task.status = TaskStatus.QUEUED
                task.dispatch_result = "dispatched"
                summary.dispatched += 1
                log_event(
                    self.logger,
                    "scheduler.task.dispatched",
                    task_id=task.task_id,
                    target=task.target_agent,
                    action=task.action,
                )
            except Exception as exc:
                task.status = TaskStatus.FAILED
                task.dispatch_result = str(exc)
                summary.failed += 1
                self.logger.error(
                    "Failed to dispatch task %s to %s: %s",
                    task.task_id,
                    task.target_agent,
                    exc,
                )

            summary.details.append(self._task_detail(task))

        self._last_schedule_time = datetime.now(timezone.utc)
        return summary

    def report(self, plan: SchedulePlan, result: DispatchSummary) -> Dict[str, Any]:
        """Summarise what was scheduled and dispatched.

        Parameters:
            plan:   The schedule plan from the planning phase.
            result: The dispatch summary from execution.

        Returns:
            A summary dict suitable for the orchestrator's audit log.
        """
        report_data: Dict[str, Any] = {
            "plan_timestamp": plan.plan_timestamp.isoformat(),
            "total_tasks_planned": len(plan.tasks),
            "skipped_agents": plan.skipped_agents,
            "dispatched": result.dispatched,
            "failed": result.failed,
            "skipped_tasks": result.skipped,
            "details": result.details,
        }

        self._log_metric("scheduler.tasks.planned", len(plan.tasks))
        self._log_metric("scheduler.tasks.dispatched", result.dispatched)
        self._log_metric("scheduler.tasks.failed", result.failed)

        if result.failed > 0:
            self.logger.warning(
                "%d of %d tasks failed to dispatch.",
                result.failed,
                len(plan.tasks),
            )

        log_event(
            self.logger,
            "scheduler.report.complete",
            dispatched=result.dispatched,
            failed=result.failed,
        )
        return report_data

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_agent_due(
        self, agent_name: str, agent_cfg: Dict[str, Any], now: datetime
    ) -> bool:
        """Determine whether *agent_name* is due to run based on its schedule.

        Parameters:
            agent_name: Canonical agent identifier.
            agent_cfg:  Per-agent schedule config dict.
            now:        Current UTC datetime.

        Returns:
            ``True`` if the agent should be scheduled in this cycle.
        """
        frequency_str = agent_cfg.get("frequency", "daily")
        try:
            frequency = ScheduleFrequency(frequency_str)
        except ValueError:
            self.logger.warning(
                "Unknown frequency '%s' for agent %s; defaulting to daily.",
                frequency_str,
                agent_name,
            )
            frequency = ScheduleFrequency.DAILY

        last_run_iso = agent_cfg.get("last_run")
        if last_run_iso is None:
            return True  # Never run before -- always due

        try:
            last_run = datetime.fromisoformat(last_run_iso)
        except (ValueError, TypeError):
            return True

        elapsed = (now - last_run).total_seconds()

        thresholds = {
            ScheduleFrequency.HOURLY: 3600,
            ScheduleFrequency.DAILY: 86400,
            ScheduleFrequency.WEEKLY: 604800,
            ScheduleFrequency.MONTHLY: 2592000,
            ScheduleFrequency.ON_DEMAND: float("inf"),
        }
        return elapsed >= thresholds.get(frequency, 86400)

    def _build_tasks_for_agent(
        self, agent_name: str, agent_cfg: Dict[str, Any], now: datetime
    ) -> List[ScheduledTask]:
        """Create one or more :class:`ScheduledTask` instances for an agent.

        Parameters:
            agent_name: Canonical agent identifier.
            agent_cfg:  Per-agent schedule config dict.
            now:        Current UTC datetime.

        Returns:
            A list of tasks to be dispatched.
        """
        self._task_counter += 1
        task_id = f"sched-{self.name}-{self._task_counter:06d}"

        priority = agent_cfg.get("priority", 50)
        action = agent_cfg.get("default_action", "run")
        params = agent_cfg.get("parameters", {})

        task = ScheduledTask(
            task_id=task_id,
            target_agent=agent_name,
            action=action,
            priority=priority,
            frequency=ScheduleFrequency(agent_cfg.get("frequency", "daily")),
            parameters=params,
            scheduled_at=now,
        )
        return [task]

    def _dispatch_task(self, task: ScheduledTask) -> None:
        """Send a task to the orchestrator's routing layer.

        In the current scaffold this records the task in an internal registry.
        A production implementation would push onto a message queue or call
        the orchestrator's ``route_task()`` API.

        Parameters:
            task: The task to dispatch.

        Raises:
            RuntimeError: If the task has already been dispatched.
        """
        if task.task_id in self._dispatch_registry:
            raise RuntimeError(f"Task {task.task_id} has already been dispatched.")

        self._dispatch_registry[task.task_id] = task
        self.logger.info(
            "Dispatched task %s -> agent=%s action=%s",
            task.task_id,
            task.target_agent,
            task.action,
        )

    @staticmethod
    def _task_detail(task: ScheduledTask) -> Dict[str, Any]:
        """Build a serialisable detail dict for a single task.

        Parameters:
            task: The task to summarise.

        Returns:
            Dict with task metadata.
        """
        return {
            "task_id": task.task_id,
            "target_agent": task.target_agent,
            "action": task.action,
            "priority": task.priority,
            "status": task.status.value,
            "dispatch_result": task.dispatch_result,
        }
