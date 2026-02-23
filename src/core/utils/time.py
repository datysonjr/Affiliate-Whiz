"""
core.utils.time
~~~~~~~~~~~~~~~

Time and scheduling utilities for the OpenClaw system.

Provides helpers for UTC timestamps, cron expression parsing, due-time
checks, human-friendly duration formatting, and interruptible sleep.

All datetime values in OpenClaw are UTC.  These utilities enforce that
convention so the rest of the codebase never deals with naive datetimes
or local timezone confusion.

Usage::

    from src.core.utils.time import now_utc, is_due, format_duration, sleep_until

    ts = now_utc()
    if is_due("*/5 * * * *", last_run=ts):
        ...
    print(format_duration(3661))  # "1h 1m 1s"
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone
from typing import Optional


# =====================================================================
# UTC helpers
# =====================================================================


def now_utc() -> datetime:
    """Return the current time as a timezone-aware UTC datetime.

    Returns
    -------
    datetime
        ``datetime.now(timezone.utc)`` -- always timezone-aware.

    Examples
    --------
    >>> ts = now_utc()
    >>> ts.tzinfo is not None
    True
    """
    return datetime.now(timezone.utc)


def utc_from_timestamp(ts: float) -> datetime:
    """Convert a POSIX timestamp to a timezone-aware UTC datetime.

    Parameters
    ----------
    ts:
        Seconds since the Unix epoch (e.g. from ``time.time()``).

    Returns
    -------
    datetime
        Timezone-aware UTC datetime.
    """
    return datetime.fromtimestamp(ts, tz=timezone.utc)


# =====================================================================
# Cron parsing (simplified)
# =====================================================================

# We support the standard five-field cron format:
#   minute  hour  day_of_month  month  day_of_week
# Each field may be: *, a number, or */N (step).

_CRON_FIELD_COUNT = 5
_CRON_FIELD_RANGES = [
    (0, 59),  # minute
    (0, 23),  # hour
    (1, 31),  # day of month
    (1, 12),  # month
    (0, 6),  # day of week (0 = Monday in our convention)
]


def _parse_cron_field(field: str, min_val: int, max_val: int) -> set[int]:
    """Parse a single cron field into the set of matching values.

    Supports: ``*``, ``N``, ``*/N``, ``N-M``, ``N,M,...``.

    Parameters
    ----------
    field:
        Raw cron field string.
    min_val:
        Minimum valid value for this field.
    max_val:
        Maximum valid value for this field.

    Returns
    -------
    set[int]
        All integer values that match the field expression.

    Raises
    ------
    ValueError
        If the field cannot be parsed.
    """
    all_values = set(range(min_val, max_val + 1))

    if field == "*":
        return all_values

    # Step: */N
    step_match = re.fullmatch(r"\*/(\d+)", field)
    if step_match:
        step = int(step_match.group(1))
        if step == 0:
            raise ValueError(f"Step value cannot be zero in cron field: {field}")
        return {v for v in all_values if (v - min_val) % step == 0}

    # Range: N-M
    range_match = re.fullmatch(r"(\d+)-(\d+)", field)
    if range_match:
        lo, hi = int(range_match.group(1)), int(range_match.group(2))
        if lo > hi:
            raise ValueError(f"Invalid range in cron field: {field}")
        return {v for v in range(lo, hi + 1) if min_val <= v <= max_val}

    # List: N,M,...
    if "," in field:
        result: set[int] = set()
        for part in field.split(","):
            result |= _parse_cron_field(part.strip(), min_val, max_val)
        return result

    # Single value
    try:
        val = int(field)
    except ValueError:
        raise ValueError(f"Cannot parse cron field: {field!r}") from None
    if not (min_val <= val <= max_val):
        raise ValueError(f"Cron field value {val} out of range [{min_val}, {max_val}]")
    return {val}


def parse_cron(expression: str) -> list[set[int]]:
    """Parse a five-field cron expression into value sets.

    Parameters
    ----------
    expression:
        Standard cron expression (e.g. ``"*/5 * * * *"``).

    Returns
    -------
    list[set[int]]
        Five sets, one per field, containing all matching integer values.

    Raises
    ------
    ValueError
        If the expression is malformed.

    Examples
    --------
    >>> fields = parse_cron("0 */2 * * 1-5")
    >>> 0 in fields[0]  # minute 0
    True
    >>> 3 in fields[1]  # hour 3 is not in */2 (0,2,4,...)
    False
    """
    parts = expression.strip().split()
    if len(parts) != _CRON_FIELD_COUNT:
        raise ValueError(
            f"Cron expression must have {_CRON_FIELD_COUNT} fields, "
            f"got {len(parts)}: {expression!r}"
        )

    return [
        _parse_cron_field(field, min_v, max_v)
        for field, (min_v, max_v) in zip(parts, _CRON_FIELD_RANGES)
    ]


def is_due(
    cron_expression: str,
    last_run: Optional[datetime] = None,
    now: Optional[datetime] = None,
) -> bool:
    """Check whether a cron schedule is due for execution.

    Parameters
    ----------
    cron_expression:
        Five-field cron expression.
    last_run:
        When the task last ran (UTC).  If ``None``, the task is always
        considered due (first run).
    now:
        Current time (UTC).  Defaults to :func:`now_utc`.

    Returns
    -------
    bool
        ``True`` if the current time matches the cron expression **and**
        the task has not already run during this matching minute.

    Examples
    --------
    >>> # Every 5 minutes, never run before
    >>> is_due("*/5 * * * *", last_run=None)
    True
    """
    if now is None:
        now = now_utc()

    fields = parse_cron(cron_expression)
    minute_set, hour_set, dom_set, month_set, dow_set = fields

    matches = (
        now.minute in minute_set
        and now.hour in hour_set
        and now.day in dom_set
        and now.month in month_set
        and now.weekday() in dow_set
    )

    if not matches:
        return False

    # If never run, it is due.
    if last_run is None:
        return True

    # Already ran during this matching minute?
    return last_run < now.replace(second=0, microsecond=0)


# =====================================================================
# Duration formatting
# =====================================================================


def format_duration(seconds: float) -> str:
    """Format a duration in seconds as a human-readable string.

    Parameters
    ----------
    seconds:
        Duration in seconds (may be fractional).

    Returns
    -------
    str
        Compact human-readable representation.

    Examples
    --------
    >>> format_duration(3661.5)
    '1h 1m 1s'
    >>> format_duration(45)
    '45s'
    >>> format_duration(0.123)
    '123ms'
    >>> format_duration(86400)
    '1d 0h 0m 0s'
    """
    if seconds < 0:
        return f"-{format_duration(-seconds)}"
    if seconds < 1:
        return f"{int(seconds * 1000)}ms"

    total = int(seconds)
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)

    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if days or hours:
        parts.append(f"{hours}h")
    if days or hours or minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")

    return " ".join(parts)


# =====================================================================
# Sleep utilities
# =====================================================================


def sleep_until(target: datetime) -> float:
    """Sleep until the specified UTC datetime, then return.

    Parameters
    ----------
    target:
        The UTC datetime to sleep until.  If in the past, returns
        immediately with a non-positive value.

    Returns
    -------
    float
        The number of seconds actually slept (may be zero or negative
        if *target* was in the past).

    Raises
    ------
    ValueError
        If *target* is a naive datetime (no timezone info).
    """
    if target.tzinfo is None:
        raise ValueError("target must be a timezone-aware datetime")

    delta = (target - now_utc()).total_seconds()
    if delta > 0:
        time.sleep(delta)
    return delta


async def async_sleep_until(target: datetime) -> float:
    """Async version of :func:`sleep_until`.

    Parameters
    ----------
    target:
        The UTC datetime to sleep until.

    Returns
    -------
    float
        The number of seconds actually slept.
    """
    if target.tzinfo is None:
        raise ValueError("target must be a timezone-aware datetime")

    delta = (target - now_utc()).total_seconds()
    if delta > 0:
        await asyncio.sleep(delta)
    return delta
