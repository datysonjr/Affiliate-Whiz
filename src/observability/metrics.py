"""
observability.metrics
~~~~~~~~~~~~~~~~~~~~~

In-memory metrics collection for the OpenClaw system.

Provides a :class:`MetricsCollector` that accumulates counters, gauges,
histograms, and timers in memory and periodically flushes them to persistent
storage (SQLite or a file).  This lightweight approach avoids external
dependencies (Prometheus, StatsD) while still giving the admin dashboard and
alert rules enough data to make operational decisions.

Metric types
------------
* **Counter** -- monotonically increasing value (e.g. ``posts_published``).
* **Gauge** -- point-in-time value that can go up or down (e.g. ``queue_depth``).
* **Histogram** -- distribution of observed values (e.g. ``response_time_ms``).
* **Timer** -- convenience wrapper around histogram for duration tracking.

Usage::

    from src.observability.metrics import metrics

    metrics.increment("posts.published")
    metrics.gauge("queue.content_depth", 42)

    with metrics.timer("pipeline.offer_discovery.duration_ms"):
        run_discovery()

    metrics.flush()

Design references:
    - ARCHITECTURE.md  Section 7 (Observability)
    - AI_RULES.md  Operational Rule #5 (audit every decision)
"""

from __future__ import annotations

import json
import statistics
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List

from src.core.logger import get_logger, log_event

logger = get_logger("observability.metrics")

# Default flush target
DEFAULT_METRICS_FILE = "data/metrics.jsonl"


class MetricsCollector:
    """In-memory metrics store with periodic flush to persistent storage.

    Thread-safe: all internal state is protected by a reentrant lock so
    metrics can be recorded from any thread (agents, pipeline workers, etc.).

    Parameters
    ----------
    flush_interval:
        Minimum seconds between automatic flushes.  Set to ``0`` to
        disable auto-flush (manual ``flush()`` only).
    storage_path:
        File path for the JSON-lines flush target.  Parent directories
        are created automatically on first flush.
    """

    def __init__(
        self,
        flush_interval: float = 60.0,
        storage_path: str = DEFAULT_METRICS_FILE,
    ) -> None:
        self._flush_interval = flush_interval
        self._storage_path = storage_path
        self._lock = threading.RLock()

        # Metric stores
        self._counters: Dict[str, float] = {}
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = {}

        # Flush bookkeeping
        self._last_flush: float = time.monotonic()
        self._flush_count: int = 0

    # ------------------------------------------------------------------
    # Counter operations
    # ------------------------------------------------------------------

    def increment(self, name: str, value: float = 1.0) -> None:
        """Increment a counter metric.

        Counters are monotonically increasing values reset only on flush.

        Parameters
        ----------
        name:
            Dot-separated metric name (e.g. ``"posts.published"``).
        value:
            Amount to add (default 1).
        """
        with self._lock:
            self._counters[name] = self._counters.get(name, 0.0) + value
        self._maybe_auto_flush()

    # ------------------------------------------------------------------
    # Gauge operations
    # ------------------------------------------------------------------

    def gauge(self, name: str, value: float) -> None:
        """Set a gauge metric to an absolute value.

        Gauges represent point-in-time measurements that can increase or
        decrease (e.g. queue depth, active connections).

        Parameters
        ----------
        name:
            Dot-separated metric name.
        value:
            Current value of the gauge.
        """
        with self._lock:
            self._gauges[name] = value
        self._maybe_auto_flush()

    # ------------------------------------------------------------------
    # Histogram operations
    # ------------------------------------------------------------------

    def histogram(self, name: str, value: float) -> None:
        """Record an observation in a histogram.

        Histograms track the distribution of values (e.g. response times,
        content word counts).  On flush, summary statistics (min, max,
        mean, median, p95, p99, count) are computed.

        Parameters
        ----------
        name:
            Dot-separated metric name.
        value:
            Observed value to record.
        """
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = []
            self._histograms[name].append(value)
        self._maybe_auto_flush()

    # ------------------------------------------------------------------
    # Timer (convenience)
    # ------------------------------------------------------------------

    @contextmanager
    def timer(self, name: str) -> Generator[None, None, None]:
        """Context manager that records elapsed time as a histogram value.

        The duration is measured in milliseconds.

        Parameters
        ----------
        name:
            Metric name for the histogram entry.

        Example
        -------
        ::

            with metrics.timer("pipeline.content.duration_ms"):
                generate_article()
        """
        start = time.monotonic()
        try:
            yield
        finally:
            elapsed_ms = (time.monotonic() - start) * 1000.0
            self.histogram(name, elapsed_ms)

    # ------------------------------------------------------------------
    # Snapshot / read
    # ------------------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        """Return a point-in-time copy of all metrics.

        Returns
        -------
        dict
            Dictionary with keys ``counters``, ``gauges``, and
            ``histograms``.  Histogram values are summarized into
            statistics (min, max, mean, median, p95, p99, count).
        """
        with self._lock:
            counters = dict(self._counters)
            gauges = dict(self._gauges)
            histograms: Dict[str, Dict[str, float]] = {}
            for name, values in self._histograms.items():
                histograms[name] = self._summarize(values)

        return {
            "counters": counters,
            "gauges": gauges,
            "histograms": histograms,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "flush_count": self._flush_count,
        }

    @staticmethod
    def _summarize(values: List[float]) -> Dict[str, float]:
        """Compute summary statistics for a list of observations.

        Parameters
        ----------
        values:
            Raw observed values.

        Returns
        -------
        dict
            Dictionary with ``min``, ``max``, ``mean``, ``median``,
            ``p95``, ``p99``, and ``count``.
        """
        if not values:
            return {
                "min": 0.0, "max": 0.0, "mean": 0.0,
                "median": 0.0, "p95": 0.0, "p99": 0.0, "count": 0,
            }

        sorted_vals = sorted(values)
        n = len(sorted_vals)

        def percentile(pct: float) -> float:
            idx = int(pct / 100.0 * (n - 1))
            return sorted_vals[min(idx, n - 1)]

        return {
            "min": sorted_vals[0],
            "max": sorted_vals[-1],
            "mean": round(statistics.mean(sorted_vals), 4),
            "median": round(statistics.median(sorted_vals), 4),
            "p95": round(percentile(95), 4),
            "p99": round(percentile(99), 4),
            "count": n,
        }

    # ------------------------------------------------------------------
    # Flush
    # ------------------------------------------------------------------

    def flush(self) -> Dict[str, Any]:
        """Write current metrics to storage and reset histograms.

        Counters are preserved (they are cumulative).  Gauges reflect
        the most recent value.  Histogram observations are cleared after
        flushing so each period captures only new observations.

        Returns
        -------
        dict
            The snapshot that was flushed.
        """
        snapshot = self.snapshot()

        # Write to JSONL file
        try:
            path = Path(self._storage_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(snapshot, default=str) + "\n")
        except OSError as exc:
            logger.warning("Failed to flush metrics to %s: %s", self._storage_path, exc)

        # Reset histograms (counters and gauges persist)
        with self._lock:
            self._histograms.clear()
            self._last_flush = time.monotonic()
            self._flush_count += 1

        log_event(
            logger, "metrics.flushed",
            counters=len(snapshot["counters"]),
            gauges=len(snapshot["gauges"]),
            histograms=len(snapshot["histograms"]),
        )
        return snapshot

    def reset(self) -> None:
        """Clear all metrics (counters, gauges, and histograms)."""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()
        log_event(logger, "metrics.reset")

    def _maybe_auto_flush(self) -> None:
        """Flush automatically if the flush interval has elapsed."""
        if self._flush_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_flush
        if elapsed >= self._flush_interval:
            self.flush()

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"MetricsCollector("
            f"counters={len(self._counters)}, "
            f"gauges={len(self._gauges)}, "
            f"histograms={len(self._histograms)}, "
            f"flushes={self._flush_count})"
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
metrics = MetricsCollector()
