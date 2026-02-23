"""
core.queue
~~~~~~~~~~

In-process task queue with a swappable backend interface.

Provides a simple thread-safe queue for local development that can be
replaced with Redis/RQ/Celery for production use.  The orchestrator
enqueues tasks; the main loop dequeues and dispatches them.

Usage::

    from src.core.queue import task_queue

    task_queue.enqueue("research", priority=1)
    task = task_queue.dequeue()  # blocks until available or timeout
"""

from __future__ import annotations

import queue
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Task descriptor
# ---------------------------------------------------------------------------


@dataclass
class QueuedTask:
    """A task waiting in the queue for execution.

    Attributes
    ----------
    task_id:
        Unique identifier for this task instance.
    agent_name:
        Name of the agent that should handle this task.
    priority:
        Lower numbers execute first (0 = highest priority).
    payload:
        Arbitrary data passed to the agent.
    enqueued_at:
        UTC timestamp when the task was enqueued.
    """

    task_id: str
    agent_name: str
    priority: int = 5
    payload: Dict[str, Any] = field(default_factory=dict)
    enqueued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __lt__(self, other: "QueuedTask") -> bool:
        """Priority queue ordering: lower priority number = higher priority."""
        return self.priority < other.priority


# ---------------------------------------------------------------------------
# Abstract queue interface (swap to Redis/Celery by implementing this)
# ---------------------------------------------------------------------------


class BaseTaskQueue(ABC):
    """Abstract interface for task queues.

    Implement this to swap the in-process queue for Redis, RQ, Celery, etc.
    """

    @abstractmethod
    def enqueue(self, task: QueuedTask) -> None:
        """Add a task to the queue."""

    @abstractmethod
    def dequeue(self, timeout: float = 1.0) -> Optional[QueuedTask]:
        """Remove and return the next task, or None if timeout expires."""

    @abstractmethod
    def size(self) -> int:
        """Return the number of tasks currently in the queue."""

    @abstractmethod
    def clear(self) -> int:
        """Remove all tasks from the queue. Return count removed."""

    @abstractmethod
    def peek(self) -> List[QueuedTask]:
        """Return all tasks without removing them (for status display)."""


# ---------------------------------------------------------------------------
# In-process priority queue implementation
# ---------------------------------------------------------------------------


class InProcessQueue(BaseTaskQueue):
    """Thread-safe in-process priority queue.

    Uses Python's ``queue.PriorityQueue`` internally.  Suitable for
    single-machine local development.  Swap to ``RedisQueue`` or
    ``CeleryQueue`` for production multi-node deployments.
    """

    def __init__(self) -> None:
        self._queue: queue.PriorityQueue[QueuedTask] = queue.PriorityQueue()
        self._lock = threading.Lock()
        self._all_tasks: List[QueuedTask] = []
        self._enqueue_count: int = 0
        self._dequeue_count: int = 0

    def enqueue(self, task: QueuedTask) -> None:
        """Add a task to the priority queue."""
        with self._lock:
            self._queue.put(task)
            self._all_tasks.append(task)
            self._enqueue_count += 1

    def dequeue(self, timeout: float = 1.0) -> Optional[QueuedTask]:
        """Remove and return the highest-priority task.

        Returns ``None`` if the queue is empty after *timeout* seconds.
        """
        try:
            task = self._queue.get(timeout=timeout)
            with self._lock:
                self._dequeue_count += 1
                if task in self._all_tasks:
                    self._all_tasks.remove(task)
            return task
        except queue.Empty:
            return None

    def size(self) -> int:
        """Return the approximate number of queued tasks."""
        return self._queue.qsize()

    def clear(self) -> int:
        """Remove all tasks. Return count removed."""
        count = 0
        with self._lock:
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                    count += 1
                except queue.Empty:
                    break
            self._all_tasks.clear()
        return count

    def peek(self) -> List[QueuedTask]:
        """Return a snapshot of all queued tasks (sorted by priority)."""
        with self._lock:
            return sorted(list(self._all_tasks))

    @property
    def stats(self) -> Dict[str, int]:
        """Return queue statistics."""
        return {
            "queued": self.size(),
            "total_enqueued": self._enqueue_count,
            "total_dequeued": self._dequeue_count,
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
task_queue: BaseTaskQueue = InProcessQueue()
