"""
orchestrator.state_machine
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Tracks system-level and per-agent states using a finite state machine with
guarded transitions.  Every transition is validated against an allowed-edges
table and recorded in an append-only history so the orchestrator (and ops
team) can audit exactly how the system moved through its lifecycle.

States
------
IDLE      -- System initialised but no agents are running.
RUNNING   -- At least one agent is actively executing.
PAUSED    -- All execution is suspended (manual or automatic).
ERROR     -- An unrecoverable error has been detected; human review required.
SHUTDOWN  -- Graceful shutdown in progress or completed.

Design references:
    - AI_RULES.md  Core Constraint #1, #4, #5
    - ARCHITECTURE.md  Section 3 (Orchestrator)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum, unique
from typing import Dict, List, Optional

from src.core.errors import InvalidStateTransitionError
from src.core.logger import get_logger, log_event

# ---------------------------------------------------------------------------
# State enumeration
# ---------------------------------------------------------------------------

@unique
class SystemState(str, Enum):
    """Finite set of states the orchestrator (or an individual agent) can be in."""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"
    SHUTDOWN = "shutdown"

    def __str__(self) -> str:
        return self.value


# ---------------------------------------------------------------------------
# Allowed transitions (directed edges)
# ---------------------------------------------------------------------------

_ALLOWED_TRANSITIONS: Dict[SystemState, frozenset[SystemState]] = {
    SystemState.IDLE: frozenset({SystemState.RUNNING, SystemState.SHUTDOWN}),
    SystemState.RUNNING: frozenset({
        SystemState.PAUSED,
        SystemState.ERROR,
        SystemState.SHUTDOWN,
        SystemState.IDLE,
    }),
    SystemState.PAUSED: frozenset({
        SystemState.RUNNING,
        SystemState.ERROR,
        SystemState.SHUTDOWN,
    }),
    SystemState.ERROR: frozenset({
        SystemState.IDLE,
        SystemState.SHUTDOWN,
    }),
    SystemState.SHUTDOWN: frozenset(),  # terminal -- no exits
}


# ---------------------------------------------------------------------------
# Transition record
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TransitionRecord:
    """Immutable record of a single state transition.

    Attributes
    ----------
    from_state:
        The state *before* the transition.
    to_state:
        The state *after* the transition.
    timestamp:
        UTC datetime when the transition occurred.
    reason:
        Human-readable explanation for why the transition was requested.
    entity:
        Identifier of the entity whose state changed (e.g. ``"system"``,
        ``"agent:research"``).
    """

    from_state: SystemState
    to_state: SystemState
    timestamp: datetime
    reason: str
    entity: str = "system"


# ---------------------------------------------------------------------------
# StateMachine
# ---------------------------------------------------------------------------

class StateMachine:
    """Finite state machine that tracks the orchestrator's lifecycle.

    The machine starts in :attr:`SystemState.IDLE` and only permits
    transitions listed in ``_ALLOWED_TRANSITIONS``.  Every successful
    transition is logged and appended to an internal history list for
    auditing (AI_RULES.md, Operational Rule #5).

    Parameters
    ----------
    entity:
        A label identifying *what* this machine tracks.  Defaults to
        ``"system"`` for the top-level orchestrator; use
        ``"agent:<name>"`` when tracking individual agent state.
    initial_state:
        Override the starting state.  Defaults to ``IDLE``.
    """

    def __init__(
        self,
        entity: str = "system",
        initial_state: SystemState = SystemState.IDLE,
    ) -> None:
        self._entity = entity
        self._state = initial_state
        self._history: List[TransitionRecord] = []
        self._logger: logging.Logger = get_logger(f"state_machine.{entity}")

        log_event(
            self._logger,
            "state_machine.init",
            entity=entity,
            initial_state=str(initial_state),
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def state(self) -> SystemState:
        """Return the current state (read-only property)."""
        return self._state

    def get_state(self) -> SystemState:
        """Return the current state.

        Returns
        -------
        SystemState
            The machine's current state.
        """
        return self._state

    def can_transition(self, target: SystemState) -> bool:
        """Check whether a transition from the current state to *target* is allowed.

        Parameters
        ----------
        target:
            The desired destination state.

        Returns
        -------
        bool
            ``True`` if the transition is valid, ``False`` otherwise.
        """
        return target in _ALLOWED_TRANSITIONS.get(self._state, frozenset())

    def transition(self, target: SystemState, *, reason: str = "") -> TransitionRecord:
        """Attempt to move from the current state to *target*.

        If the transition is not in the allowed-edges table an
        :class:`InvalidStateTransitionError` is raised and the state
        remains unchanged.

        Parameters
        ----------
        target:
            The desired destination state.
        reason:
            Human-readable explanation stored in the history record.

        Returns
        -------
        TransitionRecord
            An immutable record of the successful transition.

        Raises
        ------
        InvalidStateTransitionError
            If the transition is not permitted.
        """
        if not self.can_transition(target):
            msg = (
                f"[{self._entity}] Transition {self._state!s} -> {target!s} "
                f"is not allowed."
            )
            self._logger.warning(msg)
            raise InvalidStateTransitionError(
                msg,
                details={
                    "entity": self._entity,
                    "from_state": str(self._state),
                    "to_state": str(target),
                    "allowed": [str(s) for s in _ALLOWED_TRANSITIONS.get(self._state, frozenset())],
                },
            )

        previous = self._state
        self._state = target

        record = TransitionRecord(
            from_state=previous,
            to_state=target,
            timestamp=datetime.now(timezone.utc),
            reason=reason,
            entity=self._entity,
        )
        self._history.append(record)

        log_event(
            self._logger,
            "state_machine.transition",
            entity=self._entity,
            from_state=str(previous),
            to_state=str(target),
            reason=reason,
        )

        return record

    def get_history(
        self,
        *,
        limit: Optional[int] = None,
    ) -> List[TransitionRecord]:
        """Return the transition history, most-recent-first.

        Parameters
        ----------
        limit:
            If given, return at most this many records.

        Returns
        -------
        list[TransitionRecord]
            Transition records ordered newest-to-oldest.
        """
        ordered = list(reversed(self._history))
        if limit is not None:
            return ordered[:limit]
        return ordered

    def reset(self, *, reason: str = "manual reset") -> TransitionRecord:
        """Force the machine back to ``IDLE`` regardless of current state.

        This is an *escape hatch* for operator intervention and is always
        logged prominently.

        Parameters
        ----------
        reason:
            Explanation for the forced reset.

        Returns
        -------
        TransitionRecord
            Record of the forced transition.
        """
        previous = self._state
        self._state = SystemState.IDLE

        record = TransitionRecord(
            from_state=previous,
            to_state=SystemState.IDLE,
            timestamp=datetime.now(timezone.utc),
            reason=f"FORCED RESET: {reason}",
            entity=self._entity,
        )
        self._history.append(record)

        log_event(
            self._logger,
            "state_machine.forced_reset",
            entity=self._entity,
            from_state=str(previous),
            reason=reason,
            level=logging.WARNING,
        )

        return record

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"StateMachine(entity={self._entity!r}, "
            f"state={self._state!s}, "
            f"transitions={len(self._history)})"
        )
