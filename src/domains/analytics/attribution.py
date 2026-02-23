"""
domains.analytics.attribution
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Attribution modelling for affiliate conversion tracking.

Provides multiple attribution models (last-click, first-click, linear,
time-decay) that distribute credit across touchpoints in a user's
conversion path.  These models help determine which content pieces and
affiliate links contribute most to revenue.

Design references:
    - ARCHITECTURE.md  Section 5 (Analytics Domain)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from src.core.logger import get_logger

logger = get_logger("analytics.attribution")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class Touchpoint:
    """A single touchpoint in a user's conversion path.

    Attributes
    ----------
    channel:
        Traffic channel (e.g. ``"organic"``, ``"email"``, ``"social"``).
    source:
        Traffic source (e.g. ``"google"``, ``"newsletter"``, ``"twitter"``).
    page_url:
        URL of the page the user visited.
    timestamp:
        UTC datetime of the interaction.
    event_type:
        Type of interaction (``"click"``, ``"view"``, ``"conversion"``).
    metadata:
        Additional event-level data.
    """

    channel: str
    source: str = ""
    page_url: str = ""
    timestamp: Optional[datetime] = None
    event_type: str = "click"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AttributionResult:
    """Result of applying an attribution model to a conversion path.

    Attributes
    ----------
    model:
        Name of the attribution model used.
    conversion_id:
        Identifier for the conversion being attributed.
    touchpoint_credits:
        List of dicts, each containing ``"touchpoint"`` (index),
        ``"channel"``, ``"source"``, ``"credit"`` (0.0--1.0), and
        ``"page_url"`` keys.
    total_value:
        Total conversion value being distributed.
    conversion_time:
        UTC timestamp of the conversion event.
    path_length:
        Number of touchpoints in the conversion path.
    time_to_conversion:
        Time from first touchpoint to conversion in seconds.
    metadata:
        Additional result-level data.
    """

    model: str
    conversion_id: str = ""
    touchpoint_credits: List[Dict[str, Any]] = field(default_factory=list)
    total_value: float = 0.0
    conversion_time: Optional[datetime] = None
    path_length: int = 0
    time_to_conversion: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Attribution models
# ---------------------------------------------------------------------------


def last_click(
    touchpoints: Sequence[Touchpoint],
    conversion_value: float = 1.0,
    conversion_id: str = "",
) -> AttributionResult:
    """Last-click attribution: assign 100% credit to the final touchpoint.

    This is the simplest and most common model.  All conversion credit
    goes to the last interaction before the conversion.

    Parameters
    ----------
    touchpoints:
        Ordered list of touchpoints (earliest first).
    conversion_value:
        Total value of the conversion to distribute.
    conversion_id:
        Identifier for the conversion event.

    Returns
    -------
    AttributionResult
        Attribution result with all credit on the last touchpoint.
    """
    if not touchpoints:
        logger.warning("last_click called with empty touchpoint list")
        return AttributionResult(model="last_click", conversion_id=conversion_id)

    sorted_tps = sorted(
        touchpoints,
        key=lambda tp: tp.timestamp or datetime.min.replace(tzinfo=timezone.utc),
    )

    credits: List[Dict[str, Any]] = []
    for i, tp in enumerate(sorted_tps):
        credit = conversion_value if i == len(sorted_tps) - 1 else 0.0
        credits.append(
            {
                "touchpoint": i,
                "channel": tp.channel,
                "source": tp.source,
                "page_url": tp.page_url,
                "credit": round(credit, 6),
            }
        )

    time_to_conv = _compute_time_to_conversion(sorted_tps)

    logger.debug(
        "last_click: %d touchpoints, credit to '%s' via '%s'",
        len(sorted_tps),
        sorted_tps[-1].channel,
        sorted_tps[-1].source,
    )

    return AttributionResult(
        model="last_click",
        conversion_id=conversion_id,
        touchpoint_credits=credits,
        total_value=conversion_value,
        conversion_time=sorted_tps[-1].timestamp,
        path_length=len(sorted_tps),
        time_to_conversion=time_to_conv,
    )


def first_click(
    touchpoints: Sequence[Touchpoint],
    conversion_value: float = 1.0,
    conversion_id: str = "",
) -> AttributionResult:
    """First-click attribution: assign 100% credit to the first touchpoint.

    Useful for understanding which channels initiate the conversion path
    and drive top-of-funnel awareness.

    Parameters
    ----------
    touchpoints:
        Ordered list of touchpoints (earliest first).
    conversion_value:
        Total value of the conversion to distribute.
    conversion_id:
        Identifier for the conversion event.

    Returns
    -------
    AttributionResult
        Attribution result with all credit on the first touchpoint.
    """
    if not touchpoints:
        logger.warning("first_click called with empty touchpoint list")
        return AttributionResult(model="first_click", conversion_id=conversion_id)

    sorted_tps = sorted(
        touchpoints,
        key=lambda tp: tp.timestamp or datetime.min.replace(tzinfo=timezone.utc),
    )

    credits: List[Dict[str, Any]] = []
    for i, tp in enumerate(sorted_tps):
        credit = conversion_value if i == 0 else 0.0
        credits.append(
            {
                "touchpoint": i,
                "channel": tp.channel,
                "source": tp.source,
                "page_url": tp.page_url,
                "credit": round(credit, 6),
            }
        )

    time_to_conv = _compute_time_to_conversion(sorted_tps)

    logger.debug(
        "first_click: %d touchpoints, credit to '%s' via '%s'",
        len(sorted_tps),
        sorted_tps[0].channel,
        sorted_tps[0].source,
    )

    return AttributionResult(
        model="first_click",
        conversion_id=conversion_id,
        touchpoint_credits=credits,
        total_value=conversion_value,
        conversion_time=sorted_tps[-1].timestamp,
        path_length=len(sorted_tps),
        time_to_conversion=time_to_conv,
    )


def linear(
    touchpoints: Sequence[Touchpoint],
    conversion_value: float = 1.0,
    conversion_id: str = "",
) -> AttributionResult:
    """Linear attribution: distribute credit equally across all touchpoints.

    Each touchpoint in the conversion path receives an equal share of
    the total conversion value.  Useful when every interaction is
    considered equally important.

    Parameters
    ----------
    touchpoints:
        Ordered list of touchpoints (earliest first).
    conversion_value:
        Total value of the conversion to distribute.
    conversion_id:
        Identifier for the conversion event.

    Returns
    -------
    AttributionResult
        Attribution result with equal credit on every touchpoint.
    """
    if not touchpoints:
        logger.warning("linear called with empty touchpoint list")
        return AttributionResult(model="linear", conversion_id=conversion_id)

    sorted_tps = sorted(
        touchpoints,
        key=lambda tp: tp.timestamp or datetime.min.replace(tzinfo=timezone.utc),
    )

    n = len(sorted_tps)
    equal_credit = conversion_value / n

    credits: List[Dict[str, Any]] = []
    for i, tp in enumerate(sorted_tps):
        credits.append(
            {
                "touchpoint": i,
                "channel": tp.channel,
                "source": tp.source,
                "page_url": tp.page_url,
                "credit": round(equal_credit, 6),
            }
        )

    time_to_conv = _compute_time_to_conversion(sorted_tps)

    logger.debug(
        "linear: %d touchpoints, %.4f credit each",
        n,
        equal_credit,
    )

    return AttributionResult(
        model="linear",
        conversion_id=conversion_id,
        touchpoint_credits=credits,
        total_value=conversion_value,
        conversion_time=sorted_tps[-1].timestamp,
        path_length=n,
        time_to_conversion=time_to_conv,
    )


def time_decay(
    touchpoints: Sequence[Touchpoint],
    conversion_value: float = 1.0,
    conversion_id: str = "",
    *,
    half_life_days: float = 7.0,
) -> AttributionResult:
    """Time-decay attribution: weight credit toward more recent touchpoints.

    Uses an exponential decay function so that touchpoints closer to the
    conversion receive more credit.  The ``half_life_days`` parameter
    controls how quickly credit decays as you move back in time.

    Parameters
    ----------
    touchpoints:
        Ordered list of touchpoints (earliest first).
    conversion_value:
        Total value of the conversion to distribute.
    conversion_id:
        Identifier for the conversion event.
    half_life_days:
        Number of days for the credit to decay by half.  Lower values
        give even more credit to recent touchpoints.

    Returns
    -------
    AttributionResult
        Attribution result with time-weighted credit distribution.
    """
    if not touchpoints:
        logger.warning("time_decay called with empty touchpoint list")
        return AttributionResult(model="time_decay", conversion_id=conversion_id)

    sorted_tps = sorted(
        touchpoints,
        key=lambda tp: tp.timestamp or datetime.min.replace(tzinfo=timezone.utc),
    )

    conversion_ts = sorted_tps[-1].timestamp or datetime.now(timezone.utc)
    half_life_seconds = half_life_days * 86400.0
    decay_constant = math.log(2) / half_life_seconds if half_life_seconds > 0 else 0

    # Compute raw weights based on time distance from conversion
    raw_weights: List[float] = []
    for tp in sorted_tps:
        tp_time = tp.timestamp or conversion_ts
        seconds_before = max((conversion_ts - tp_time).total_seconds(), 0)
        weight = math.exp(-decay_constant * seconds_before)
        raw_weights.append(weight)

    # Normalise so weights sum to conversion_value
    total_weight = sum(raw_weights) or 1.0

    credits: List[Dict[str, Any]] = []
    for i, (tp, weight) in enumerate(zip(sorted_tps, raw_weights)):
        credit = (weight / total_weight) * conversion_value
        credits.append(
            {
                "touchpoint": i,
                "channel": tp.channel,
                "source": tp.source,
                "page_url": tp.page_url,
                "credit": round(credit, 6),
            }
        )

    time_to_conv = _compute_time_to_conversion(sorted_tps)

    logger.debug(
        "time_decay: %d touchpoints, half_life=%.1f days, "
        "max_credit=%.4f, min_credit=%.4f",
        len(sorted_tps),
        half_life_days,
        max(c["credit"] for c in credits),
        min(c["credit"] for c in credits),
    )

    return AttributionResult(
        model="time_decay",
        conversion_id=conversion_id,
        touchpoint_credits=credits,
        total_value=conversion_value,
        conversion_time=conversion_ts,
        path_length=len(sorted_tps),
        time_to_conversion=time_to_conv,
        metadata={"half_life_days": half_life_days},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_time_to_conversion(sorted_touchpoints: List[Touchpoint]) -> float:
    """Calculate the time from first touchpoint to last in seconds.

    Parameters
    ----------
    sorted_touchpoints:
        Touchpoints sorted by timestamp (earliest first).

    Returns
    -------
    float
        Seconds between first and last touchpoint.
    """
    if len(sorted_touchpoints) < 2:
        return 0.0

    first_ts = sorted_touchpoints[0].timestamp
    last_ts = sorted_touchpoints[-1].timestamp
    if first_ts and last_ts:
        return max((last_ts - first_ts).total_seconds(), 0.0)
    return 0.0
