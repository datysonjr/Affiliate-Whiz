"""
observability.tracing
~~~~~~~~~~~~~~~~~~~~~

Lightweight request tracing for debugging pipeline execution in OpenClaw.

Provides a :class:`Tracer` that creates hierarchical spans representing
units of work (agent runs, pipeline steps, API calls).  Each span captures
start/end timestamps, tags, and an optional status so operators can
reconstruct the full execution path of any request.

This is intentionally simpler than OpenTelemetry -- it stores traces
in-memory (with an optional dump-to-file) and is designed for a
single-process system running on two Mac Minis, not a distributed cluster.

Usage::

    from src.observability.tracing import tracer

    span_id = tracer.start_span("pipeline.content", tags={"site": "example.com"})
    try:
        generate_content()
        tracer.add_tag(span_id, "word_count", 1500)
    finally:
        tracer.end_span(span_id)

    trace = tracer.get_trace(span_id)

Design references:
    - ARCHITECTURE.md  Section 7 (Observability)
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.logger import get_logger, log_event

logger = get_logger("observability.tracing")

# Default trace storage path
DEFAULT_TRACE_FILE = "data/traces.jsonl"

# Maximum number of completed traces to keep in memory
DEFAULT_MAX_TRACES = 1000


@dataclass
class Span:
    """A single unit of work within a trace.

    Attributes
    ----------
    span_id:
        Unique identifier for this span.
    name:
        Human-readable name describing the operation
        (e.g. ``"pipeline.content.generate"``).
    parent_id:
        Span ID of the parent span, or ``None`` for root spans.
    trace_id:
        Identifier grouping related spans into a single trace.
    start_time:
        Monotonic clock timestamp when the span started.
    end_time:
        Monotonic clock timestamp when the span ended (``None`` if active).
    start_wall:
        UTC wall-clock time when the span started (for human display).
    end_wall:
        UTC wall-clock time when the span ended.
    tags:
        Key-value metadata attached to the span.
    status:
        Span outcome -- ``ok``, ``error``, or ``running``.
    children:
        List of child span IDs.
    """

    span_id: str = ""
    name: str = ""
    parent_id: Optional[str] = None
    trace_id: str = ""
    start_time: float = 0.0
    end_time: Optional[float] = None
    start_wall: str = ""
    end_wall: Optional[str] = None
    tags: Dict[str, Any] = field(default_factory=dict)
    status: str = "running"
    children: List[str] = field(default_factory=list)

    @property
    def duration_ms(self) -> Optional[float]:
        """Return the span duration in milliseconds, or ``None`` if still running."""
        if self.end_time is None:
            return None
        return round((self.end_time - self.start_time) * 1000.0, 3)

    @property
    def is_active(self) -> bool:
        """Return ``True`` if the span has not been ended."""
        return self.end_time is None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the span to a JSON-friendly dictionary."""
        return {
            "span_id": self.span_id,
            "name": self.name,
            "parent_id": self.parent_id,
            "trace_id": self.trace_id,
            "start_wall": self.start_wall,
            "end_wall": self.end_wall,
            "duration_ms": self.duration_ms,
            "tags": self.tags,
            "status": self.status,
            "children": self.children,
        }


class Tracer:
    """Lightweight in-memory trace collector.

    Thread-safe: all span operations are protected by a lock.

    Parameters
    ----------
    max_traces:
        Maximum number of completed traces to keep in memory.
        Oldest traces are evicted when this limit is exceeded.
    storage_path:
        Optional file path to persist completed traces as JSON lines.
    """

    def __init__(
        self,
        max_traces: int = DEFAULT_MAX_TRACES,
        storage_path: Optional[str] = DEFAULT_TRACE_FILE,
    ) -> None:
        self._max_traces = max_traces
        self._storage_path = storage_path
        self._lock = threading.RLock()

        # Active and completed spans indexed by span_id
        self._spans: Dict[str, Span] = {}

        # Trace index: trace_id -> list of span_ids
        self._traces: Dict[str, List[str]] = {}

        # Completed trace IDs in insertion order (for eviction)
        self._completed_traces: List[str] = []

    # ------------------------------------------------------------------
    # Span lifecycle
    # ------------------------------------------------------------------

    def start_span(
        self,
        name: str,
        *,
        parent_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        tags: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Start a new span and return its ID.

        Parameters
        ----------
        name:
            Human-readable name for the span (e.g. ``"agent.research.run"``).
        parent_id:
            ID of the parent span.  If provided, this span becomes a child
            of the parent and inherits its ``trace_id``.
        trace_id:
            Explicit trace ID.  If ``None`` and no parent is given, a new
            trace ID is generated.
        tags:
            Initial key-value tags to attach to the span.

        Returns
        -------
        str
            The unique span ID.
        """
        span_id = uuid.uuid4().hex[:16]
        now_mono = time.monotonic()
        now_wall = datetime.now(timezone.utc).isoformat()

        with self._lock:
            # Resolve trace_id from parent or generate new
            if trace_id is None and parent_id is not None:
                parent_span = self._spans.get(parent_id)
                if parent_span is not None:
                    trace_id = parent_span.trace_id
                    parent_span.children.append(span_id)

            if trace_id is None:
                trace_id = uuid.uuid4().hex[:16]

            span = Span(
                span_id=span_id,
                name=name,
                parent_id=parent_id,
                trace_id=trace_id,
                start_time=now_mono,
                start_wall=now_wall,
                tags=dict(tags) if tags else {},
                status="running",
            )

            self._spans[span_id] = span

            # Register in trace index
            if trace_id not in self._traces:
                self._traces[trace_id] = []
            self._traces[trace_id].append(span_id)

        log_event(
            logger, "span.started",
            span_id=span_id, name=name, trace_id=trace_id,
        )
        return span_id

    def end_span(
        self,
        span_id: str,
        *,
        status: str = "ok",
    ) -> Optional[Span]:
        """End an active span and record its duration.

        Parameters
        ----------
        span_id:
            The span to end.
        status:
            Final status -- ``"ok"`` or ``"error"``.

        Returns
        -------
        Span or None
            The completed span, or ``None`` if the span ID was not found.
        """
        now_mono = time.monotonic()
        now_wall = datetime.now(timezone.utc).isoformat()

        with self._lock:
            span = self._spans.get(span_id)
            if span is None:
                logger.warning("Attempted to end unknown span: %s", span_id)
                return None

            span.end_time = now_mono
            span.end_wall = now_wall
            span.status = status

            # Check if this completes the entire trace
            trace_id = span.trace_id
            trace_spans = self._traces.get(trace_id, [])
            all_done = all(
                not self._spans[sid].is_active
                for sid in trace_spans
                if sid in self._spans
            )

            if all_done:
                self._on_trace_completed(trace_id)

        log_event(
            logger, "span.ended",
            span_id=span_id, status=status,
            duration_ms=span.duration_ms,
        )
        return span

    def _on_trace_completed(self, trace_id: str) -> None:
        """Handle a fully completed trace: persist and manage eviction.

        Must be called while holding ``self._lock``.
        """
        self._completed_traces.append(trace_id)

        # Persist to file if configured
        if self._storage_path:
            self._persist_trace(trace_id)

        # Evict oldest traces if over capacity
        while len(self._completed_traces) > self._max_traces:
            old_trace_id = self._completed_traces.pop(0)
            old_span_ids = self._traces.pop(old_trace_id, [])
            for sid in old_span_ids:
                self._spans.pop(sid, None)

    def _persist_trace(self, trace_id: str) -> None:
        """Write a completed trace to the JSONL storage file."""
        trace_data = self._build_trace_dict(trace_id)
        if trace_data is None:
            return

        try:
            path = Path(self._storage_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(trace_data, default=str) + "\n")
        except OSError as exc:
            logger.warning(
                "Failed to persist trace %s: %s", trace_id, exc
            )

    # ------------------------------------------------------------------
    # Tag operations
    # ------------------------------------------------------------------

    def add_tag(self, span_id: str, key: str, value: Any) -> None:
        """Add a key-value tag to an active span.

        Parameters
        ----------
        span_id:
            The span to tag.
        key:
            Tag key (e.g. ``"word_count"``, ``"error_message"``).
        value:
            Tag value (must be JSON-serializable).
        """
        with self._lock:
            span = self._spans.get(span_id)
            if span is None:
                logger.warning("Attempted to tag unknown span: %s", span_id)
                return
            span.tags[key] = value

    def add_tags(self, span_id: str, tags: Dict[str, Any]) -> None:
        """Add multiple tags to a span at once.

        Parameters
        ----------
        span_id:
            The span to tag.
        tags:
            Dictionary of tags to merge.
        """
        with self._lock:
            span = self._spans.get(span_id)
            if span is None:
                return
            span.tags.update(tags)

    # ------------------------------------------------------------------
    # Query operations
    # ------------------------------------------------------------------

    def get_span(self, span_id: str) -> Optional[Dict[str, Any]]:
        """Return a single span as a dictionary.

        Parameters
        ----------
        span_id:
            The span to retrieve.

        Returns
        -------
        dict or None
            Serialized span data, or ``None`` if not found.
        """
        with self._lock:
            span = self._spans.get(span_id)
            if span is None:
                return None
            return span.to_dict()

    def get_trace(self, span_or_trace_id: str) -> Optional[Dict[str, Any]]:
        """Return a full trace containing all spans.

        Accepts either a span ID (to find its parent trace) or a trace ID
        directly.

        Parameters
        ----------
        span_or_trace_id:
            Span ID or trace ID.

        Returns
        -------
        dict or None
            Dictionary with ``trace_id``, ``spans``, ``duration_ms``, and
            ``status`` fields.  ``None`` if not found.
        """
        with self._lock:
            # Check if it's a trace_id directly
            if span_or_trace_id in self._traces:
                return self._build_trace_dict(span_or_trace_id)

            # Otherwise try as a span_id
            span = self._spans.get(span_or_trace_id)
            if span is None:
                return None
            return self._build_trace_dict(span.trace_id)

    def _build_trace_dict(self, trace_id: str) -> Optional[Dict[str, Any]]:
        """Build a trace dictionary from all spans in a trace.

        Must be called while holding ``self._lock`` or from a safe context.
        """
        span_ids = self._traces.get(trace_id)
        if not span_ids:
            return None

        spans = []
        total_duration = 0.0
        has_error = False

        for sid in span_ids:
            span = self._spans.get(sid)
            if span is None:
                continue
            spans.append(span.to_dict())
            if span.duration_ms is not None:
                total_duration = max(total_duration, span.duration_ms)
            if span.status == "error":
                has_error = True

        return {
            "trace_id": trace_id,
            "spans": spans,
            "span_count": len(spans),
            "duration_ms": round(total_duration, 3),
            "status": "error" if has_error else "ok",
        }

    def list_active_spans(self) -> List[Dict[str, Any]]:
        """Return all currently active (unfinished) spans.

        Returns
        -------
        list[dict]
            List of serialized active spans.
        """
        with self._lock:
            return [
                span.to_dict()
                for span in self._spans.values()
                if span.is_active
            ]

    def list_recent_traces(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return the most recently completed traces.

        Parameters
        ----------
        limit:
            Maximum number of traces to return.

        Returns
        -------
        list[dict]
            Serialized traces, most recent first.
        """
        with self._lock:
            recent_ids = list(reversed(self._completed_traces[-limit:]))
            traces = []
            for trace_id in recent_ids:
                trace = self._build_trace_dict(trace_id)
                if trace is not None:
                    traces.append(trace)
            return traces

    # ------------------------------------------------------------------
    # Management
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Remove all spans and traces from memory."""
        with self._lock:
            self._spans.clear()
            self._traces.clear()
            self._completed_traces.clear()
        log_event(logger, "tracer.cleared")

    @property
    def active_span_count(self) -> int:
        """Return the number of currently active spans."""
        with self._lock:
            return sum(1 for s in self._spans.values() if s.is_active)

    @property
    def total_span_count(self) -> int:
        """Return the total number of spans in memory."""
        with self._lock:
            return len(self._spans)

    def __repr__(self) -> str:
        return (
            f"Tracer(active={self.active_span_count}, "
            f"total={self.total_span_count}, "
            f"traces={len(self._completed_traces)})"
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
tracer = Tracer()
