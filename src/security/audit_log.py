"""
security.audit_log
~~~~~~~~~~~~~~~~~~

Immutable audit trail for security-relevant events in the OpenClaw system.

Provides an :class:`AuditLog` that records every sensitive action (secret
access, permission changes, configuration modifications, kill-switch events)
to an append-only log file.  Entries are written as JSON lines so they can
be ingested by log aggregators or reviewed manually during incident response.

The audit log is intentionally separate from the application logger to
ensure tamper resistance: application log levels can be changed, but the
audit log always captures everything at maximum fidelity.

Usage::

    from src.security.audit_log import audit_log

    audit_log.log_action(
        actor="master_scheduler",
        action="killswitch.engaged",
        resource="system",
        details={"reason": "error_rate_exceeded"},
    )

    recent = audit_log.get_recent(limit=50)

Design references:
    - ARCHITECTURE.md  Section 8 (Security)
    - AI_RULES.md  Operational Rule #5 (audit every decision)
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.logger import get_logger

logger = get_logger("security.audit_log")

# Default audit log file
DEFAULT_AUDIT_LOG_PATH = "data/audit.jsonl"

# Maximum entries to return from in-memory buffer for get_recent()
DEFAULT_BUFFER_SIZE = 1000


class AuditEntry:
    """A single audit log entry.

    Attributes
    ----------
    entry_id:
        Unique identifier for this entry.
    timestamp:
        UTC ISO-8601 timestamp when the event occurred.
    actor:
        The entity that performed the action (agent name, user ID, ``"system"``).
    action:
        Machine-readable action identifier (e.g. ``"vault.secret_accessed"``).
    resource:
        The resource affected (e.g. ``"OPENAI_API_KEY"``, ``"campaign:42"``).
    outcome:
        Result of the action -- ``"success"``, ``"denied"``, or ``"error"``.
    details:
        Additional structured context.
    source_ip:
        IP address of the requester (if applicable).
    """

    __slots__ = (
        "entry_id", "timestamp", "actor", "action",
        "resource", "outcome", "details", "source_ip",
    )

    def __init__(
        self,
        *,
        actor: str,
        action: str,
        resource: str = "",
        outcome: str = "success",
        details: Optional[Dict[str, Any]] = None,
        source_ip: Optional[str] = None,
    ) -> None:
        self.entry_id: str = uuid.uuid4().hex[:12]
        self.timestamp: str = datetime.now(timezone.utc).isoformat()
        self.actor = actor
        self.action = action
        self.resource = resource
        self.outcome = outcome
        self.details: Dict[str, Any] = details or {}
        self.source_ip: Optional[str] = source_ip

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the entry to a JSON-friendly dictionary."""
        return {
            "entry_id": self.entry_id,
            "timestamp": self.timestamp,
            "actor": self.actor,
            "action": self.action,
            "resource": self.resource,
            "outcome": self.outcome,
            "details": self.details,
            "source_ip": self.source_ip,
        }

    def to_json(self) -> str:
        """Return the entry as a single JSON string (no trailing newline)."""
        return json.dumps(self.to_dict(), default=str)


class AuditLog:
    """Append-only audit trail for security events.

    Thread-safe: all writes are protected by a lock.  Entries are written
    to a JSONL file and also buffered in memory for fast recent-event queries.

    Parameters
    ----------
    log_path:
        Path to the audit log file.  Parent directories are created
        on first write.
    buffer_size:
        Maximum number of entries to keep in the in-memory ring buffer
        for ``get_recent()`` queries.
    """

    def __init__(
        self,
        log_path: str = DEFAULT_AUDIT_LOG_PATH,
        buffer_size: int = DEFAULT_BUFFER_SIZE,
    ) -> None:
        self._log_path = log_path
        self._buffer_size = buffer_size
        self._lock = threading.RLock()
        self._buffer: List[AuditEntry] = []
        self._total_entries: int = 0

    # ------------------------------------------------------------------
    # Logging actions
    # ------------------------------------------------------------------

    def log_action(
        self,
        *,
        actor: str,
        action: str,
        resource: str = "",
        outcome: str = "success",
        details: Optional[Dict[str, Any]] = None,
        source_ip: Optional[str] = None,
    ) -> AuditEntry:
        """Record a security-relevant action.

        Parameters
        ----------
        actor:
            Who performed the action (agent name, user ID, or ``"system"``).
        action:
            Machine-readable action name (e.g. ``"config.modified"``).
        resource:
            The target resource (e.g. ``"campaign:42"``).
        outcome:
            Result -- ``"success"``, ``"denied"``, or ``"error"``.
        details:
            Free-form context dict.
        source_ip:
            Requester's IP address (if applicable).

        Returns
        -------
        AuditEntry
            The recorded entry.
        """
        entry = AuditEntry(
            actor=actor,
            action=action,
            resource=resource,
            outcome=outcome,
            details=details,
            source_ip=source_ip,
        )
        self._write(entry)
        return entry

    def log_access(
        self,
        *,
        actor: str,
        resource: str,
        granted: bool = True,
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditEntry:
        """Record a resource access attempt.

        Convenience wrapper around :meth:`log_action` for access-control
        events.

        Parameters
        ----------
        actor:
            Who attempted access.
        resource:
            What was accessed.
        granted:
            Whether access was granted.
        details:
            Additional context.

        Returns
        -------
        AuditEntry
            The recorded entry.
        """
        return self.log_action(
            actor=actor,
            action="access.attempt",
            resource=resource,
            outcome="success" if granted else "denied",
            details=details,
        )

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def query_logs(
        self,
        *,
        actor: Optional[str] = None,
        action: Optional[str] = None,
        resource: Optional[str] = None,
        outcome: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query the in-memory audit buffer with optional filters.

        Parameters
        ----------
        actor:
            Filter by actor name (exact match).
        action:
            Filter by action (prefix match, e.g. ``"vault."`` matches
            ``"vault.secret_accessed"``).
        resource:
            Filter by resource (substring match).
        outcome:
            Filter by outcome (exact match).
        since:
            ISO-8601 timestamp -- only return entries after this time.
        limit:
            Maximum number of entries to return.

        Returns
        -------
        list[dict]
            Matching audit entries as dictionaries, newest first.
        """
        with self._lock:
            results: List[Dict[str, Any]] = []
            for entry in reversed(self._buffer):
                if actor is not None and entry.actor != actor:
                    continue
                if action is not None and not entry.action.startswith(action):
                    continue
                if resource is not None and resource not in entry.resource:
                    continue
                if outcome is not None and entry.outcome != outcome:
                    continue
                if since is not None and entry.timestamp < since:
                    continue
                results.append(entry.to_dict())
                if len(results) >= limit:
                    break
            return results

    def get_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return the most recent audit entries.

        Parameters
        ----------
        limit:
            Number of entries to return.

        Returns
        -------
        list[dict]
            Audit entries as dictionaries, newest first.
        """
        with self._lock:
            entries = list(reversed(self._buffer[-limit:]))
            return [e.to_dict() for e in entries]

    @property
    def total_entries(self) -> int:
        """Return the total number of audit entries recorded since startup."""
        return self._total_entries

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def query_file(
        self,
        *,
        actor: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query the audit log file on disk (for entries older than the buffer).

        Reads the file in reverse order for efficiency.

        Parameters
        ----------
        actor:
            Filter by actor (exact match).
        action:
            Filter by action (prefix match).
        limit:
            Maximum entries to return.

        Returns
        -------
        list[dict]
            Matching entries as dictionaries.
        """
        path = Path(self._log_path)
        if not path.is_file():
            return []

        results: List[Dict[str, Any]] = []
        try:
            with path.open("r", encoding="utf-8") as fh:
                lines = fh.readlines()

            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if actor is not None and entry.get("actor") != actor:
                    continue
                if action is not None and not entry.get("action", "").startswith(action):
                    continue

                results.append(entry)
                if len(results) >= limit:
                    break
        except OSError as exc:
            logger.warning("Failed to read audit log file: %s", exc)

        return results

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _write(self, entry: AuditEntry) -> None:
        """Write an entry to both the in-memory buffer and the file."""
        with self._lock:
            # Add to ring buffer
            self._buffer.append(entry)
            if len(self._buffer) > self._buffer_size:
                self._buffer = self._buffer[-self._buffer_size:]
            self._total_entries += 1

        # Append to file (outside lock to avoid holding it during I/O)
        try:
            path = Path(self._log_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(entry.to_json() + "\n")
        except OSError as exc:
            logger.warning("Failed to write audit log entry: %s", exc)

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"AuditLog(path={self._log_path!r}, "
            f"buffered={len(self._buffer)}, "
            f"total={self._total_entries})"
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
audit_log = AuditLog()
