"""
orchestrator.scheduler
~~~~~~~~~~~~~~~~~~~~~~~

Cron-based scheduling engine for OpenClaw agents and maintenance pipelines.

Reads schedule definitions from ``config/schedules.yaml``, evaluates cron
expressions against the current time, and yields the set of tasks that are
due for execution.  The orchestrator controller polls :meth:`get_due_tasks`
on each heartbeat and dispatches the returned tasks.

Cron expressions follow the standard five-field format::

    minute  hour  day_of_month  month  day_of_week

Design references:
    - AI_RULES.md        Core Constraint #1 (no unsupervised agents)
    - config/schedules.yaml
    - config/agents.yaml (per-agent ``frequency`` overrides)
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:
    yaml = None  # type: ignore[assignment]

from src.core.constants import CONFIG_DIR
from src.core.errors import SchedulerError
from src.core.logger import get_logger, log_event


# ---------------------------------------------------------------------------
# Cron helpers
# ---------------------------------------------------------------------------

def _match_cron_field(field_expr: str, value: int, min_val: int, max_val: int) -> bool:
    """Return ``True`` if *value* matches a single cron field expression.

    Supports:
        - ``*``          (any value)
        - ``*/N``        (every N-th value)
        - ``N``          (exact match)
        - ``N,M,...``    (list of values)
        - ``N-M``        (range inclusive)

    Parameters
    ----------
    field_expr:
        A single cron field string.
    value:
        The current calendar value to test.
    min_val:
        Minimum allowed value for this field.
    max_val:
        Maximum allowed value for this field.
    """
    for part in field_expr.split(","):
        part = part.strip()

        # */N  -- step
        step_match = re.fullmatch(r"\*/(\d+)", part)
        if step_match:
            step = int(step_match.group(1))
            if step == 0:
                continue
            if value % step == 0:
                return True
            continue

        # N-M  -- range
        range_match = re.fullmatch(r"(\d+)-(\d+)", part)
        if range_match:
            lo, hi = int(range_match.group(1)), int(range_match.group(2))
            if lo <= value <= hi:
                return True
            continue

        # *  -- wildcard
        if part == "*":
            return True

        # N  -- exact
        if part.isdigit() and int(part) == value:
            return True

    return False


def cron_matches(cron_expr: str, dt: datetime) -> bool:
    """Return ``True`` if the cron expression matches *dt*.

    Parameters
    ----------
    cron_expr:
        Five-field cron string (minute hour dom month dow).
    dt:
        Datetime to evaluate against.

    Raises
    ------
    SchedulerError
        If *cron_expr* does not contain exactly five fields.
    """
    fields = cron_expr.strip().split()
    if len(fields) != 5:
        raise SchedulerError(
            f"Invalid cron expression '{cron_expr}' -- expected 5 fields, got {len(fields)}.",
            details={"expression": cron_expr},
        )

    minute, hour, dom, month, dow = fields
    checks = [
        _match_cron_field(minute, dt.minute, 0, 59),
        _match_cron_field(hour, dt.hour, 0, 23),
        _match_cron_field(dom, dt.day, 1, 31),
        _match_cron_field(month, dt.month, 1, 12),
        _match_cron_field(dow, dt.isoweekday() % 7, 0, 6),  # 0=Sun
    ]
    return all(checks)


# ---------------------------------------------------------------------------
# Scheduled task descriptor
# ---------------------------------------------------------------------------

@dataclass
class ScheduledTask:
    """Descriptor for a single scheduled item.

    Attributes
    ----------
    name:
        Unique task identifier (e.g. ``"agent:research"`` or ``"maintenance:backup"``).
    category:
        Top-level schedule category from the YAML file (``agents``, ``maintenance``,
        ``reporting``, ``orchestrator``).
    cron_expr:
        Five-field cron expression controlling when this task fires.
    enabled:
        Whether the task is currently active.
    last_run_at:
        UTC datetime of the most recent execution, or ``None``.
    """

    name: str
    category: str
    cron_expr: str
    enabled: bool = True
    last_run_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

class Scheduler:
    """Manages cron-based scheduling for the OpenClaw system.

    Parameters
    ----------
    config_dir:
        Path to the ``config/`` directory that contains ``schedules.yaml``.
        When ``None`` the value of :data:`core.constants.CONFIG_DIR` is used.
    """

    def __init__(self, config_dir: Optional[str] = None) -> None:
        self._logger: logging.Logger = get_logger("orchestrator.scheduler")
        self._config_dir: str = config_dir or CONFIG_DIR
        self._tasks: Dict[str, ScheduledTask] = {}
        self._raw_config: Dict[str, Any] = {}

        log_event(self._logger, "scheduler.init", config_dir=self._config_dir)

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_schedules(self, *, config_path: Optional[str] = None) -> int:
        """Parse ``schedules.yaml`` and populate the internal task registry.

        Parameters
        ----------
        config_path:
            Explicit path to the schedules file.  When ``None``, defaults
            to ``<config_dir>/schedules.yaml``.

        Returns
        -------
        int
            Number of tasks loaded.

        Raises
        ------
        SchedulerError
            If the YAML file cannot be read or parsed.
        """
        path = config_path or os.path.join(self._config_dir, "schedules.yaml")

        if yaml is None:
            raise SchedulerError(
                "PyYAML is required for schedule loading. Install with: pip install pyyaml"
            )

        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
        except FileNotFoundError as exc:
            raise SchedulerError(
                f"Schedule config not found at '{path}'.",
                details={"path": path},
            ) from exc
        except yaml.YAMLError as exc:
            raise SchedulerError(
                f"Failed to parse schedule config at '{path}': {exc}",
                details={"path": path},
            ) from exc

        self._raw_config = raw
        schedules = raw.get("schedules", {})
        self._tasks.clear()

        count = 0
        for category, entries in schedules.items():
            if not isinstance(entries, dict):
                continue
            for task_name, cron_expr in entries.items():
                full_name = f"{category}:{task_name}"
                self._tasks[full_name] = ScheduledTask(
                    name=full_name,
                    category=category,
                    cron_expr=str(cron_expr),
                )
                count += 1

        log_event(
            self._logger,
            "scheduler.loaded",
            path=path,
            task_count=count,
        )
        return count

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def get_due_tasks(self, *, now: Optional[datetime] = None) -> List[ScheduledTask]:
        """Return all tasks whose cron expression matches the given time.

        Parameters
        ----------
        now:
            Evaluation time.  Defaults to ``datetime.now(timezone.utc)``.

        Returns
        -------
        list[ScheduledTask]
            Tasks that are due to fire right now.
        """
        now = now or datetime.now(timezone.utc)
        due: List[ScheduledTask] = []

        for task in self._tasks.values():
            if not task.enabled:
                continue
            try:
                if cron_matches(task.cron_expr, now):
                    due.append(task)
            except SchedulerError:
                self._logger.warning(
                    "Skipping task '%s' -- invalid cron expression '%s'.",
                    task.name,
                    task.cron_expr,
                )

        log_event(
            self._logger,
            "scheduler.due_tasks",
            count=len(due),
            tasks=[t.name for t in due],
        )
        return due

    def get_next_run(self, task_name: str) -> Optional[str]:
        """Return the cron expression for a task so callers can compute the next fire time.

        This is a lightweight helper -- full next-fire-time calculation
        requires iterating future minutes, which is left to the caller or
        a specialised library.

        Parameters
        ----------
        task_name:
            Fully-qualified task name (e.g. ``"agents:research"``).

        Returns
        -------
        str or None
            The cron expression string, or ``None`` if the task is unknown.
        """
        task = self._tasks.get(task_name)
        if task is None:
            return None
        return task.cron_expr

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def schedule_task(
        self,
        name: str,
        cron_expr: str,
        *,
        category: str = "custom",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ScheduledTask:
        """Add or replace a scheduled task at runtime.

        Parameters
        ----------
        name:
            Task identifier.  Will be stored as ``<category>:<name>``.
        cron_expr:
            Five-field cron expression.
        category:
            Schedule category (default ``"custom"``).
        metadata:
            Arbitrary key-value data attached to the task.

        Returns
        -------
        ScheduledTask
            The newly-created (or updated) task descriptor.

        Raises
        ------
        SchedulerError
            If *cron_expr* is malformed.
        """
        # Validate expression before storing.
        fields = cron_expr.strip().split()
        if len(fields) != 5:
            raise SchedulerError(
                f"Invalid cron expression '{cron_expr}' -- expected 5 fields.",
                details={"expression": cron_expr, "name": name},
            )

        full_name = f"{category}:{name}"
        task = ScheduledTask(
            name=full_name,
            category=category,
            cron_expr=cron_expr,
            metadata=metadata or {},
        )
        self._tasks[full_name] = task

        log_event(
            self._logger,
            "scheduler.task_added",
            task=full_name,
            cron=cron_expr,
        )
        return task

    def cancel_task(self, task_name: str) -> bool:
        """Remove a task from the schedule.

        Parameters
        ----------
        task_name:
            Fully-qualified task name to remove.

        Returns
        -------
        bool
            ``True`` if the task existed and was removed, ``False`` otherwise.
        """
        if task_name in self._tasks:
            del self._tasks[task_name]
            log_event(self._logger, "scheduler.task_cancelled", task=task_name)
            return True

        self._logger.warning("cancel_task: '%s' not found.", task_name)
        return False

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @property
    def task_count(self) -> int:
        """Return the number of currently-registered tasks."""
        return len(self._tasks)

    @property
    def all_tasks(self) -> List[ScheduledTask]:
        """Return a copy of all registered tasks."""
        return list(self._tasks.values())

    def __repr__(self) -> str:
        return f"Scheduler(tasks={len(self._tasks)}, config_dir={self._config_dir!r})"
