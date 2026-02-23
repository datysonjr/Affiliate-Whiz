"""
domains.analytics.events
~~~~~~~~~~~~~~~~~~~~~~~~~

Event tracking and querying for the OpenClaw analytics domain.

Provides the :class:`Event` dataclass for representing analytics events
and the :class:`EventTracker` class for recording, querying, and
aggregating events.  Events capture user interactions, affiliate clicks,
conversions, and system-level occurrences across all managed sites.

Design references:
    - ARCHITECTURE.md  Section 5 (Analytics Domain)
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from src.core.logger import get_logger, log_event

logger = get_logger("analytics.events")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Event:
    """A single analytics event.

    Attributes
    ----------
    event_id:
        Unique event identifier (auto-generated UUID if not provided).
    event_type:
        Event type key (e.g. ``"page_view"``, ``"affiliate_click"``,
        ``"conversion"``, ``"outbound_click"``).
    timestamp:
        UTC datetime when the event occurred.
    site_id:
        Identifier for the site that generated the event.
    page_url:
        URL of the page where the event occurred.
    user_id:
        Anonymous user identifier (cookie-based or fingerprint).
    session_id:
        Session identifier.
    referrer:
        HTTP Referer header value.
    channel:
        Traffic channel (``"organic"``, ``"direct"``, ``"referral"``,
        ``"social"``, ``"email"``).
    properties:
        Event-specific key-value properties (e.g. ``{"product_asin": "B08..."}``,
        ``{"affiliate_network": "amazon"}``).
    value:
        Numeric value associated with the event (e.g. conversion amount).
    metadata:
        Additional context data.
    """

    event_id: str = ""
    event_type: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    site_id: str = ""
    page_url: str = ""
    user_id: str = ""
    session_id: str = ""
    referrer: str = ""
    channel: str = ""
    properties: Dict[str, Any] = field(default_factory=dict)
    value: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Auto-generate event_id if not provided."""
        if not self.event_id:
            self.event_id = uuid.uuid4().hex[:16]


@dataclass
class AggregateResult:
    """Result of an event aggregation query.

    Attributes
    ----------
    group_key:
        The value of the field that events were grouped by.
    count:
        Number of events in this group.
    total_value:
        Sum of ``Event.value`` for events in this group.
    avg_value:
        Mean ``Event.value`` for events in this group.
    min_timestamp:
        Earliest event timestamp in the group.
    max_timestamp:
        Latest event timestamp in the group.
    """

    group_key: str
    count: int = 0
    total_value: float = 0.0
    avg_value: float = 0.0
    min_timestamp: Optional[datetime] = None
    max_timestamp: Optional[datetime] = None


# ---------------------------------------------------------------------------
# EventTracker
# ---------------------------------------------------------------------------

class EventTracker:
    """In-memory event tracking, querying, and aggregation engine.

    Provides a lightweight analytics backend for recording events and
    running queries.  In production this would be backed by a time-series
    database (e.g. ClickHouse, TimescaleDB), but the in-memory
    implementation is sufficient for development and testing.

    Parameters
    ----------
    max_events:
        Maximum number of events to retain in memory.  Oldest events
        are evicted when this limit is reached.
    """

    def __init__(self, max_events: int = 100_000) -> None:
        self._events: List[Event] = []
        self._max_events = max_events
        self._event_count: int = 0

        log_event(logger, "event_tracker.init", max_events=max_events)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def track(self, event: Event) -> Event:
        """Record a single analytics event.

        Parameters
        ----------
        event:
            The event to record.

        Returns
        -------
        Event
            The recorded event (with ``event_id`` populated).
        """
        self._events.append(event)
        self._event_count += 1

        # Evict oldest events if over capacity
        if len(self._events) > self._max_events:
            overflow = len(self._events) - self._max_events
            self._events = self._events[overflow:]

        logger.debug(
            "Tracked event %s: type=%s site=%s",
            event.event_id, event.event_type, event.site_id,
        )
        return event

    def track_batch(self, events: Sequence[Event]) -> int:
        """Record a batch of analytics events.

        Parameters
        ----------
        events:
            Events to record.

        Returns
        -------
        int
            Number of events successfully recorded.
        """
        count = 0
        for event in events:
            self.track(event)
            count += 1

        log_event(
            logger, "event_tracker.batch",
            batch_size=count, total=self._event_count,
        )
        return count

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def query(
        self,
        *,
        event_type: str = "",
        site_id: str = "",
        channel: str = "",
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        user_id: str = "",
        page_url_contains: str = "",
        limit: int = 0,
    ) -> List[Event]:
        """Query events with optional filters.

        All filter parameters are combined with AND logic.  Omitted
        filters match all events.

        Parameters
        ----------
        event_type:
            Filter by event type.
        site_id:
            Filter by site identifier.
        channel:
            Filter by traffic channel.
        start_time:
            Include events at or after this UTC datetime.
        end_time:
            Include events before this UTC datetime.
        user_id:
            Filter by user identifier.
        page_url_contains:
            Filter events whose page_url contains this substring.
        limit:
            Maximum number of results (0 for unlimited).

        Returns
        -------
        list[Event]
            Matching events sorted by timestamp (newest first).
        """
        results: List[Event] = []

        for event in reversed(self._events):
            if event_type and event.event_type != event_type:
                continue
            if site_id and event.site_id != site_id:
                continue
            if channel and event.channel != channel:
                continue
            if user_id and event.user_id != user_id:
                continue
            if start_time and event.timestamp < start_time:
                continue
            if end_time and event.timestamp >= end_time:
                continue
            if page_url_contains and page_url_contains not in event.page_url:
                continue

            results.append(event)

            if limit and len(results) >= limit:
                break

        logger.debug(
            "Query returned %d events (type=%s, site=%s, channel=%s)",
            len(results), event_type or "*", site_id or "*", channel or "*",
        )
        return results

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def aggregate(
        self,
        group_by: str,
        *,
        event_type: str = "",
        site_id: str = "",
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[AggregateResult]:
        """Aggregate events by a specified field.

        Parameters
        ----------
        group_by:
            Field name to group by.  Supported values: ``"event_type"``,
            ``"site_id"``, ``"channel"``, ``"page_url"``, ``"user_id"``.
        event_type:
            Optional pre-filter by event type.
        site_id:
            Optional pre-filter by site.
        start_time:
            Include events at or after this UTC datetime.
        end_time:
            Include events before this UTC datetime.

        Returns
        -------
        list[AggregateResult]
            Aggregated results sorted by count (highest first).

        Raises
        ------
        ValueError
            If ``group_by`` is not a recognised field.
        """
        valid_fields = {"event_type", "site_id", "channel", "page_url", "user_id"}
        if group_by not in valid_fields:
            raise ValueError(
                f"Cannot group by '{group_by}'. Valid fields: {sorted(valid_fields)}"
            )

        # Pre-filter events
        filtered = self.query(
            event_type=event_type,
            site_id=site_id,
            start_time=start_time,
            end_time=end_time,
        )

        # Group and aggregate
        groups: Dict[str, List[Event]] = defaultdict(list)
        for event in filtered:
            key = getattr(event, group_by, "")
            groups[key].append(event)

        results: List[AggregateResult] = []
        for key, events in groups.items():
            values = [e.value for e in events]
            timestamps = [e.timestamp for e in events if e.timestamp]

            results.append(AggregateResult(
                group_key=key,
                count=len(events),
                total_value=round(sum(values), 6),
                avg_value=round(sum(values) / len(values), 6) if values else 0.0,
                min_timestamp=min(timestamps) if timestamps else None,
                max_timestamp=max(timestamps) if timestamps else None,
            ))

        results.sort(key=lambda r: r.count, reverse=True)

        log_event(
            logger, "event_tracker.aggregate",
            group_by=group_by,
            input_events=len(filtered),
            output_groups=len(results),
        )

        return results

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def event_count(self) -> int:
        """Return the total number of events ever tracked."""
        return self._event_count

    @property
    def stored_count(self) -> int:
        """Return the number of events currently stored in memory."""
        return len(self._events)

    def clear(self) -> None:
        """Remove all stored events."""
        self._events.clear()
        logger.info("Event tracker cleared")

    def __repr__(self) -> str:
        return (
            f"EventTracker(stored={self.stored_count}, "
            f"total_tracked={self._event_count})"
        )
