"""
domains.seo.keyword
~~~~~~~~~~~~~~~~~~~~

Keyword research data model and utilities for the OpenClaw SEO domain.

Provides the :class:`KeywordData` model and helper functions to group,
expand, and prioritise keyword lists for content planning.  The functions
work on plain data structures and are designed to be called from the
research agent or content pipeline without external API dependencies.

Design references:
    - ARCHITECTURE.md  Section 3 (Content Pipeline -- Keyword Research)
    - core/constants.py  DEFAULT_KEYWORD_DENSITY
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, unique
from typing import Any, Dict, List, Optional, Sequence

from src.core.logger import get_logger

logger = get_logger("seo.keyword")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


@unique
class SearchIntent(str, Enum):
    """Classification of the searcher's intent behind a keyword.

    Used to match keywords with appropriate content types:
    - INFORMATIONAL keywords -> blog posts, guides
    - COMMERCIAL keywords -> comparison articles, roundups
    - TRANSACTIONAL keywords -> product reviews with affiliate links
    - NAVIGATIONAL keywords -> generally avoided for affiliate content
    """

    INFORMATIONAL = "informational"
    COMMERCIAL = "commercial"
    TRANSACTIONAL = "transactional"
    NAVIGATIONAL = "navigational"


# ---------------------------------------------------------------------------
# KeywordData
# ---------------------------------------------------------------------------


@dataclass
class KeywordData:
    """Data model for a single keyword with SEO metrics.

    Attributes
    ----------
    keyword:
        The keyword phrase (e.g. ``"best standing desk 2025"``).
    volume:
        Estimated monthly search volume.
    difficulty:
        SEO difficulty score (0--100, higher = harder to rank).
    cpc:
        Cost-per-click in USD from paid search data.
    intent:
        Classified search intent.
    priority_score:
        Composite priority score computed by :func:`prioritize_keywords`.
    parent_topic:
        Broader topic this keyword belongs to (if grouped).
    serp_features:
        List of SERP features observed (e.g. ``"featured_snippet"``,
        ``"people_also_ask"``).
    trend:
        Trend direction: ``"rising"``, ``"stable"``, or ``"declining"``.
    metadata:
        Additional keyword-level data from the source tool.
    """

    keyword: str
    volume: int = 0
    difficulty: int = 0
    cpc: float = 0.0
    intent: SearchIntent = SearchIntent.INFORMATIONAL
    priority_score: float = 0.0
    parent_topic: str = ""
    serp_features: List[str] = field(default_factory=list)
    trend: str = "stable"
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def word_count(self) -> int:
        """Return the number of words in the keyword phrase."""
        return len(self.keyword.split())

    @property
    def is_long_tail(self) -> bool:
        """Return ``True`` if the keyword is long-tail (3+ words)."""
        return self.word_count >= 3

    @property
    def opportunity_score(self) -> float:
        """Compute a quick opportunity score: high volume + low difficulty.

        Returns
        -------
        float
            Score in the range [0, 100].  Higher is better.
        """
        if self.volume <= 0:
            return 0.0
        # Log-scaled volume (caps extreme values) vs. inverse difficulty
        vol_score = min(math.log10(max(self.volume, 1)) * 15, 50)
        diff_score = max(50 - self.difficulty * 0.5, 0)
        return round(vol_score + diff_score, 2)


# ---------------------------------------------------------------------------
# Keyword grouping
# ---------------------------------------------------------------------------


def group_keywords(
    keywords: Sequence[KeywordData],
    *,
    method: str = "stem",
) -> Dict[str, List[KeywordData]]:
    """Group keywords by semantic similarity using a lightweight approach.

    Groups related keywords together so they can be targeted by a single
    piece of content rather than creating competing articles.

    Parameters
    ----------
    keywords:
        Flat list of keyword data objects.
    method:
        Grouping method.  ``"stem"`` groups by shared root words (default).
        ``"head_term"`` groups by the first two words.

    Returns
    -------
    dict[str, list[KeywordData]]
        Mapping of group label -> list of keywords in that group.

    Examples
    --------
    >>> kws = [KeywordData("best standing desk"), KeywordData("best standing desk for home")]
    >>> groups = group_keywords(kws)
    >>> len(groups)
    1
    """
    groups: Dict[str, List[KeywordData]] = defaultdict(list)

    if method == "head_term":
        for kw in keywords:
            words = kw.keyword.lower().split()
            head = " ".join(words[:2]) if len(words) >= 2 else kw.keyword.lower()
            groups[head].append(kw)
    else:
        # Stem-based: extract significant root words and group by overlap
        for kw in keywords:
            root = _extract_root(kw.keyword)
            groups[root].append(kw)

    # Merge very small groups into an "other" bucket
    MIN_GROUP_SIZE = 1
    final: Dict[str, List[KeywordData]] = {}
    for label, members in groups.items():
        if len(members) >= MIN_GROUP_SIZE:
            final[label] = members

    logger.debug(
        "Grouped %d keywords into %d groups (method=%s)",
        len(keywords),
        len(final),
        method,
    )
    return final


def _extract_root(phrase: str) -> str:
    """Extract a root grouping key from a keyword phrase.

    Strips common modifiers (best, top, review, cheap, etc.) and stop
    words to find the core topic.

    Parameters
    ----------
    phrase:
        Keyword phrase.

    Returns
    -------
    str
        Simplified root key for grouping.
    """
    stop_words = {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "for",
        "of",
        "in",
        "on",
        "to",
        "and",
        "or",
        "with",
        "vs",
        "versus",
    }
    modifiers = {
        "best",
        "top",
        "cheap",
        "affordable",
        "review",
        "reviews",
        "guide",
        "how",
        "what",
        "why",
        "buy",
        "compare",
        "comparison",
        "rated",
        "recommended",
        "ultimate",
        "complete",
    }

    words = phrase.lower().split()
    core = [w for w in words if w not in stop_words and w not in modifiers]

    # Remove trailing year patterns (2024, 2025, etc.)
    core = [w for w in core if not re.match(r"^\d{4}$", w)]

    if not core:
        return phrase.lower()

    # Sort to make grouping key order-independent
    return " ".join(sorted(core))


# ---------------------------------------------------------------------------
# Keyword expansion
# ---------------------------------------------------------------------------


def expand_keywords(
    seed_keywords: Sequence[str],
    *,
    modifiers: Optional[List[str]] = None,
    include_questions: bool = True,
) -> List[str]:
    """Expand a list of seed keywords with common modifiers and question forms.

    This is a local expansion that does not call any external API.  It
    generates candidate keyword phrases by combining seeds with modifiers
    and question patterns that are common in affiliate content niches.

    Parameters
    ----------
    seed_keywords:
        Base keyword phrases to expand.
    modifiers:
        Custom modifiers to append/prepend.  If ``None``, a default set
        of affiliate-relevant modifiers is used.
    include_questions:
        If ``True``, generate question-form keywords (e.g. ``"what is
        the best ..."``).

    Returns
    -------
    list[str]
        Expanded keyword list (deduplicated, original seeds included).

    Examples
    --------
    >>> expanded = expand_keywords(["standing desk"])
    >>> "best standing desk" in expanded
    True
    >>> "standing desk review" in expanded
    True
    """
    default_modifiers = [
        "best",
        "top",
        "review",
        "cheap",
        "affordable",
        "vs",
        "comparison",
        "alternative",
        "guide",
        "for home",
        "for office",
        "under 500",
        "under 1000",
        "worth it",
    ]
    mods = modifiers or default_modifiers

    question_prefixes = [
        "what is the best",
        "how to choose",
        "is it worth buying",
        "which is better",
    ]

    expanded: set[str] = set()

    for seed in seed_keywords:
        seed_lower = seed.strip().lower()
        expanded.add(seed_lower)

        for mod in mods:
            expanded.add(f"{mod} {seed_lower}")
            expanded.add(f"{seed_lower} {mod}")

        if include_questions:
            for prefix in question_prefixes:
                expanded.add(f"{prefix} {seed_lower}")

    result = sorted(expanded)
    logger.debug("Expanded %d seeds into %d keywords", len(seed_keywords), len(result))
    return result


# ---------------------------------------------------------------------------
# Keyword prioritisation
# ---------------------------------------------------------------------------


def prioritize_keywords(
    keywords: Sequence[KeywordData],
    *,
    volume_weight: float = 0.35,
    difficulty_weight: float = 0.30,
    cpc_weight: float = 0.20,
    intent_weight: float = 0.15,
) -> List[KeywordData]:
    """Score and rank keywords by their potential value for affiliate content.

    Each keyword receives a :attr:`KeywordData.priority_score` (0--100)
    based on a weighted combination of volume, difficulty (inverse),
    CPC, and intent alignment.  The returned list is sorted by score
    in descending order.

    Parameters
    ----------
    keywords:
        Keywords to prioritise.
    volume_weight:
        Weight for normalised search volume (higher volume = better).
    difficulty_weight:
        Weight for inverse difficulty (lower difficulty = better).
    cpc_weight:
        Weight for normalised CPC (higher CPC = more commercial value).
    intent_weight:
        Weight for intent alignment (transactional/commercial = better).

    Returns
    -------
    list[KeywordData]
        Keywords sorted by priority score (highest first), with
        ``priority_score`` populated on each instance.
    """
    if not keywords:
        return []

    # Compute normalisation bounds
    max_vol = max(kw.volume for kw in keywords) or 1
    max_cpc = max(kw.cpc for kw in keywords) or 1.0

    intent_scores = {
        SearchIntent.TRANSACTIONAL: 100,
        SearchIntent.COMMERCIAL: 80,
        SearchIntent.INFORMATIONAL: 50,
        SearchIntent.NAVIGATIONAL: 20,
    }

    result: List[KeywordData] = []
    for kw in keywords:
        vol_norm = (kw.volume / max_vol) * 100
        diff_norm = max(100 - kw.difficulty, 0)
        cpc_norm = (kw.cpc / max_cpc) * 100
        intent_norm = intent_scores.get(kw.intent, 50)

        score = (
            vol_norm * volume_weight
            + diff_norm * difficulty_weight
            + cpc_norm * cpc_weight
            + intent_norm * intent_weight
        )
        kw.priority_score = round(min(max(score, 0), 100), 2)
        result.append(kw)

    result.sort(key=lambda k: k.priority_score, reverse=True)

    logger.info(
        "Prioritised %d keywords. Top: %s (score=%.1f), Bottom: %s (score=%.1f)",
        len(result),
        result[0].keyword if result else "N/A",
        result[0].priority_score if result else 0,
        result[-1].keyword if result else "N/A",
        result[-1].priority_score if result else 0,
    )
    return result
