"""
domains.seo.trend_predictor
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

OpenClaw Trend Explosion Predictor.

Detects profitable niches BEFORE they explode in search demand by
monitoring a 5-level signal pyramid (supply → industry → creator →
consumer → search) and scoring each niche for early publishing.

Implements the strategy from
``docs/seo/OPENCLAW_TREND_EXPLOSION_PREDICTOR.md``.

The predictor:
    1. Accepts raw signals from multiple monitoring sources
    2. Classifies each signal into one of 5 pyramid levels
    3. Applies the multi-signal confirmation rule
    4. Computes a weighted trend score per niche
    5. Generates the 6-page category explosion playbook
    6. Returns a prioritised niche activation queue

Design references:
    - docs/seo/OPENCLAW_TREND_EXPLOSION_PREDICTOR.md
    - src/domains/seo/query_capture.py  (AuthorityCluster)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, IntEnum, unique
from typing import Any, Dict, List, Optional, Sequence

from src.core.logger import get_logger, log_event

logger = get_logger("domains.seo.trend_predictor")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


@unique
class SignalLevel(IntEnum):
    """The 5-level trend signal pyramid.

    Lower level = earlier signal = higher strategic value.
    """

    SUPPLY = 1  # Manufacturer / distributor activity
    INDUSTRY = 2  # VC funding, startup launches, patents
    CREATOR = 3  # YouTube / TikTok / influencer coverage
    CONSUMER = 4  # Reddit / forums / discussion spikes
    SEARCH_VOLUME = 5  # Keyword tools, Google Trends (too late)


@unique
class SignalSource(str, Enum):
    """Specific source within a signal level."""

    # Level 1 — Supply
    AMAZON_NEW_SKU = "amazon_new_sku"
    MANUFACTURER_ANNOUNCEMENT = "manufacturer_announcement"
    CROWDFUNDING_LAUNCH = "crowdfunding_launch"
    DISTRIBUTOR_EXPANSION = "distributor_expansion"

    # Level 2 — Industry
    VC_FUNDING = "vc_funding"
    STARTUP_LAUNCH = "startup_launch"
    CONFERENCE_ANNOUNCEMENT = "conference_announcement"
    PATENT_FILING = "patent_filing"
    REGULATORY_APPROVAL = "regulatory_approval"

    # Level 3 — Creator
    YOUTUBE_COVERAGE = "youtube_coverage"
    TIKTOK_TREND = "tiktok_trend"
    INFLUENCER_SEEDING = "influencer_seeding"
    AFFILIATE_TESTING = "affiliate_testing"

    # Level 4 — Consumer
    REDDIT_SPIKE = "reddit_spike"
    FORUM_QUESTIONS = "forum_questions"
    DISCORD_MENTIONS = "discord_mentions"

    # Level 5 — Search
    KEYWORD_VOLUME_RISE = "keyword_volume_rise"
    GOOGLE_TRENDS_SPIKE = "google_trends_spike"

    # Manual
    MANUAL = "manual"


@unique
class NichePriority(str, Enum):
    """Niche value tier from the trend priority order."""

    PHYSICAL_HIGH_PRICE = "physical_high_price"
    SUBSCRIPTION_SOFTWARE = "subscription_software"
    EVOLVING_TECH = "evolving_tech"
    LIFESTYLE_BRANDED = "lifestyle_branded"
    PROFESSIONAL_EQUIPMENT = "professional_equipment"
    OTHER = "other"


# ---------------------------------------------------------------------------
# Signal level mapping
# ---------------------------------------------------------------------------

_SOURCE_TO_LEVEL: dict[SignalSource, SignalLevel] = {
    SignalSource.AMAZON_NEW_SKU: SignalLevel.SUPPLY,
    SignalSource.MANUFACTURER_ANNOUNCEMENT: SignalLevel.SUPPLY,
    SignalSource.CROWDFUNDING_LAUNCH: SignalLevel.SUPPLY,
    SignalSource.DISTRIBUTOR_EXPANSION: SignalLevel.SUPPLY,
    SignalSource.VC_FUNDING: SignalLevel.INDUSTRY,
    SignalSource.STARTUP_LAUNCH: SignalLevel.INDUSTRY,
    SignalSource.CONFERENCE_ANNOUNCEMENT: SignalLevel.INDUSTRY,
    SignalSource.PATENT_FILING: SignalLevel.INDUSTRY,
    SignalSource.REGULATORY_APPROVAL: SignalLevel.INDUSTRY,
    SignalSource.YOUTUBE_COVERAGE: SignalLevel.CREATOR,
    SignalSource.TIKTOK_TREND: SignalLevel.CREATOR,
    SignalSource.INFLUENCER_SEEDING: SignalLevel.CREATOR,
    SignalSource.AFFILIATE_TESTING: SignalLevel.CREATOR,
    SignalSource.REDDIT_SPIKE: SignalLevel.CONSUMER,
    SignalSource.FORUM_QUESTIONS: SignalLevel.CONSUMER,
    SignalSource.DISCORD_MENTIONS: SignalLevel.CONSUMER,
    SignalSource.KEYWORD_VOLUME_RISE: SignalLevel.SEARCH_VOLUME,
    SignalSource.GOOGLE_TRENDS_SPIKE: SignalLevel.SEARCH_VOLUME,
    SignalSource.MANUAL: SignalLevel.CONSUMER,
}


def get_signal_level(source: SignalSource) -> SignalLevel:
    """Return the pyramid level for a signal source."""
    return _SOURCE_TO_LEVEL.get(source, SignalLevel.SEARCH_VOLUME)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class TrendSignal:
    """A single trend signal detected from a monitoring source.

    Attributes
    ----------
    niche:
        The niche or product category this signal relates to.
    source:
        Where the signal was detected.
    strength:
        Signal strength (0.0-1.0). Higher = stronger indicator.
    detected_at:
        UTC timestamp of detection.
    description:
        Human-readable description of the signal.
    metadata:
        Additional context from the source.
    """

    niche: str
    source: SignalSource = SignalSource.MANUAL
    strength: float = 0.5
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def level(self) -> SignalLevel:
        """Return the pyramid level for this signal."""
        return get_signal_level(self.source)

    @property
    def level_name(self) -> str:
        """Human-readable level name."""
        return self.level.name.lower()


@dataclass
class NicheTrendReport:
    """Aggregated trend analysis for a single niche.

    Attributes
    ----------
    niche:
        The niche or product category.
    signals:
        All detected signals for this niche.
    trend_score:
        Weighted trend score (0-13 max based on spec weights).
    confirmed:
        Whether the multi-signal confirmation rule is met
        (any 2+ distinct signal categories active).
    should_activate:
        Whether the score meets the activation threshold (>=6).
    levels_detected:
        Set of pyramid levels that had signals.
    explosion_playbook:
        The 6-page content playbook for this niche.
    estimated_half_life_months:
        Estimated profitability window in months (6-18).
    priority:
        Niche value tier classification.
    """

    niche: str = ""
    signals: List[TrendSignal] = field(default_factory=list)
    trend_score: float = 0.0
    confirmed: bool = False
    should_activate: bool = False
    levels_detected: set[SignalLevel] = field(default_factory=set)
    explosion_playbook: List[str] = field(default_factory=list)
    estimated_half_life_months: int = 12
    priority: NichePriority = NichePriority.OTHER

    @property
    def signal_count(self) -> int:
        return len(self.signals)

    @property
    def earliest_signal_level(self) -> Optional[SignalLevel]:
        """Return the earliest (lowest) signal level detected."""
        if not self.levels_detected:
            return None
        return min(self.levels_detected)

    @property
    def is_early_mover_opportunity(self) -> bool:
        """True if signals are at Level 1-3 (before consumer/search)."""
        if not self.levels_detected:
            return False
        return min(self.levels_detected) <= SignalLevel.CREATOR


# ---------------------------------------------------------------------------
# Trend score weights (from spec)
# ---------------------------------------------------------------------------

_LEVEL_WEIGHTS: dict[SignalLevel, int] = {
    SignalLevel.SUPPLY: 4,
    SignalLevel.INDUSTRY: 3,
    SignalLevel.CREATOR: 3,
    SignalLevel.CONSUMER: 2,
    SignalLevel.SEARCH_VOLUME: 1,
}

ACTIVATION_THRESHOLD: int = 6
MULTI_SIGNAL_MINIMUM: int = 2


# ---------------------------------------------------------------------------
# Category explosion playbook
# ---------------------------------------------------------------------------

_EXPLOSION_PLAYBOOK_TEMPLATES: list[str] = [
    "Best {niche} — Complete Buying Guide",
    "Top 10 {niche} Compared — Which One to Buy",
    "{niche} for Beginners — Everything You Need to Know",
    "{niche} FAQ — Common Questions Answered",
    "Common {niche} Problems and How to Fix Them",
    "Best {niche} Alternatives — What Else to Consider",
]


def generate_explosion_playbook(niche: str) -> List[str]:
    """Generate the 6-page category explosion playbook for a niche.

    From the spec — when a niche is flagged, immediately publish:
    best guide + comparison + beginner guide + FAQ + troubleshooting +
    alternatives.

    Parameters
    ----------
    niche:
        The niche or product category name.

    Returns
    -------
    list[str]
        6 article titles forming the authority cluster.
    """
    return [t.format(niche=niche) for t in _EXPLOSION_PLAYBOOK_TEMPLATES]


# ---------------------------------------------------------------------------
# Multi-signal confirmation
# ---------------------------------------------------------------------------


def check_multi_signal_confirmation(
    signals: Sequence[TrendSignal],
) -> tuple[bool, set[SignalLevel]]:
    """Check the multi-signal confirmation rule.

    From the spec — flag niche explosion when ANY TWO of the following
    occur: manufacturer activity, funding surge, creator coverage, or
    discussion spike. Search volume alone is NOT sufficient.

    Parameters
    ----------
    signals:
        All signals detected for a single niche.

    Returns
    -------
    tuple[bool, set[SignalLevel]]
        (confirmed, set of levels detected). Confirmed is True if
        2+ distinct non-search levels have signals.
    """
    levels: set[SignalLevel] = set()
    for signal in signals:
        levels.add(signal.level)

    # Exclude search volume from the confirmation check — it's too late
    actionable_levels = levels - {SignalLevel.SEARCH_VOLUME}
    confirmed = len(actionable_levels) >= MULTI_SIGNAL_MINIMUM

    return confirmed, levels


# ---------------------------------------------------------------------------
# Trend score computation
# ---------------------------------------------------------------------------


def compute_trend_score(signals: Sequence[TrendSignal]) -> float:
    """Compute the weighted trend score for a niche.

    Weights from the spec::

        Supply signal weight = 4
        Funding/Industry signal weight = 3
        Creator signal weight = 3
        Consumer discussion weight = 2
        Search volume weight = 1

    Each level contributes its weight only once (strongest signal at
    that level, scaled by signal strength).

    Parameters
    ----------
    signals:
        All signals for a single niche.

    Returns
    -------
    float
        Trend score. Maximum possible = 13 (4+3+3+2+1).
    """
    # Best signal strength per level
    best_per_level: dict[SignalLevel, float] = {}
    for signal in signals:
        level = signal.level
        if level not in best_per_level or signal.strength > best_per_level[level]:
            best_per_level[level] = signal.strength

    score = 0.0
    for level, strength in best_per_level.items():
        weight = _LEVEL_WEIGHTS.get(level, 1)
        score += weight * strength

    return round(score, 1)


# ---------------------------------------------------------------------------
# Profitability filter
# ---------------------------------------------------------------------------

_PROFITABLE_SIGNALS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:buy|purchase|price|cost|deal|discount|sale)\b", re.IGNORECASE),
    re.compile(r"\b(?:review|comparison|vs|versus|alternative)\b", re.IGNORECASE),
    re.compile(r"\b(?:best|top|rated|recommended)\b", re.IGNORECASE),
]


def has_purchase_intent(niche: str, signals: Sequence[TrendSignal]) -> bool:
    """Check if a niche shows purchase intent signals.

    From the spec — a niche needs purchase intent, affiliate programs,
    multiple competing products, and buyer confusion.

    Parameters
    ----------
    niche:
        The niche name.
    signals:
        All signals for this niche.

    Returns
    -------
    bool
        True if the niche appears commercially viable.
    """
    # Check niche name and signal descriptions for purchase language
    all_text = niche.lower()
    for s in signals:
        all_text += " " + s.description.lower()

    for pattern in _PROFITABLE_SIGNALS:
        if pattern.search(all_text):
            return True

    # Supply/industry signals inherently imply commercial activity
    levels = {s.level for s in signals}
    if SignalLevel.SUPPLY in levels or SignalLevel.INDUSTRY in levels:
        return True

    return False


# ---------------------------------------------------------------------------
# Main analysis pipeline
# ---------------------------------------------------------------------------


def analyze_niche(
    niche: str,
    signals: Sequence[TrendSignal],
    *,
    priority: NichePriority = NichePriority.OTHER,
) -> NicheTrendReport:
    """Analyze a single niche using all its trend signals.

    Parameters
    ----------
    niche:
        The niche or product category.
    signals:
        All detected signals for this niche.
    priority:
        Manual niche value classification.

    Returns
    -------
    NicheTrendReport
        Full trend analysis with score, confirmation, and playbook.
    """
    confirmed, levels = check_multi_signal_confirmation(signals)
    score = compute_trend_score(signals)
    should_activate = score >= ACTIVATION_THRESHOLD and confirmed
    playbook = generate_explosion_playbook(niche) if should_activate else []

    report = NicheTrendReport(
        niche=niche,
        signals=list(signals),
        trend_score=score,
        confirmed=confirmed,
        should_activate=should_activate,
        levels_detected=levels,
        explosion_playbook=playbook,
        priority=priority,
    )

    log_event(
        logger,
        "trend_predictor.niche.analyzed",
        niche=niche,
        score=score,
        confirmed=confirmed,
        should_activate=should_activate,
        levels=len(levels),
    )

    return report


def predict_explosions(
    signals: Sequence[TrendSignal],
    *,
    niche_priorities: Optional[Dict[str, NichePriority]] = None,
    require_purchase_intent: bool = True,
) -> List[NicheTrendReport]:
    """Run the full Trend Explosion Predictor pipeline.

    1. Group signals by niche
    2. Analyze each niche (score + confirmation)
    3. Filter by purchase intent (optional)
    4. Generate explosion playbooks for activated niches
    5. Return sorted by trend score

    Parameters
    ----------
    signals:
        All detected trend signals across all niches.
    niche_priorities:
        Optional mapping of niche name -> priority tier.
    require_purchase_intent:
        If True, filter out niches without commercial viability.

    Returns
    -------
    list[NicheTrendReport]
        Niche reports sorted by trend score (highest first).
        Only activated niches are included.
    """
    priorities = niche_priorities or {}

    # Group signals by niche
    niche_signals: Dict[str, List[TrendSignal]] = {}
    for signal in signals:
        key = signal.niche.lower().strip()
        if key not in niche_signals:
            niche_signals[key] = []
        niche_signals[key].append(signal)

    reports: List[NicheTrendReport] = []
    for niche, niche_sigs in niche_signals.items():
        priority = priorities.get(niche, NichePriority.OTHER)
        report = analyze_niche(niche, niche_sigs, priority=priority)

        if not report.should_activate:
            continue

        if require_purchase_intent and not has_purchase_intent(niche, niche_sigs):
            continue

        reports.append(report)

    reports.sort(key=lambda r: r.trend_score, reverse=True)

    log_event(
        logger,
        "trend_predictor.pipeline.complete",
        total_signals=len(signals),
        niches_scanned=len(niche_signals),
        niches_activated=len(reports),
    )

    return reports
