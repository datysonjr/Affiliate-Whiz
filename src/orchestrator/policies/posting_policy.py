"""
orchestrator.policies.posting_policy
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Enforces posting frequency, anti-spam, and domain reputation rules.

Before any content is published the orchestrator checks this policy to
ensure:

    1. The per-site daily posting limit has not been exceeded.
    2. A minimum cooldown period has elapsed since the last post to the
       same site.
    3. The posting pattern does not exhibit spam-like characteristics.
    4. New domains follow a conservative ramp-up schedule.

Design references:
    - AI_RULES.md   Publishing Rules #1 -- #3
    - config/thresholds.yaml  (``spam_risk`` section)
    - config/sites.yaml       (per-site overrides)
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.core.constants import (
    DEFAULT_COOLDOWN_MINUTES,
    DEFAULT_MAX_POSTS_PER_DAY,
    DEFAULT_POSTING_CADENCE_PER_DAY,
)
from src.core.errors import PostingPolicyViolationError
from src.core.logger import get_logger, log_event


# ---------------------------------------------------------------------------
# Default thresholds (overridable via config)
# ---------------------------------------------------------------------------

_DEFAULT_MAX_SIMILAR_TITLES_PCT: float = 0.20
_DEFAULT_MAX_AFFILIATE_LINK_DENSITY: float = 0.05
_DEFAULT_NEW_DOMAIN_AGE_DAYS: int = 30
_DEFAULT_NEW_DOMAIN_MAX_POSTS_PER_DAY: int = 1


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PostingRecord:
    """Tracks posting history for a single site.

    Attributes
    ----------
    site_id:
        Identifier of the target site / domain.
    post_timestamps:
        UTC datetimes of every post made to this site (most-recent last).
    domain_age_days:
        How many days the domain has been active.  Used for reputation
        ramp-up.
    """

    site_id: str
    post_timestamps: List[datetime] = field(default_factory=list)
    domain_age_days: int = 0


@dataclass
class PostingVerdict:
    """Result of a posting-policy evaluation.

    Attributes
    ----------
    allowed:
        ``True`` if posting is permitted.
    reason:
        Human-readable explanation when ``allowed`` is ``False``.
    cooldown_remaining_s:
        Seconds until the next post is allowed (0 when posting is OK).
    daily_remaining:
        Number of posts still allowed today for the target site.
    details:
        Machine-readable context.
    """

    allowed: bool = True
    reason: str = ""
    cooldown_remaining_s: float = 0.0
    daily_remaining: int = 0
    details: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# PostingPolicy
# ---------------------------------------------------------------------------

class PostingPolicy:
    """Enforces posting frequency, anti-spam, and domain reputation rules.

    Parameters
    ----------
    config:
        Policy overrides.  Recognised keys:
            ``max_posts_per_day``, ``cooldown_minutes``,
            ``max_similar_titles_pct``, ``max_affiliate_link_density``,
            ``new_domain_age_days``, ``new_domain_max_posts_per_day``.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self._logger: logging.Logger = get_logger("policy.posting")
        cfg = config or {}

        self._max_posts_per_day: int = int(
            cfg.get("max_posts_per_day", DEFAULT_MAX_POSTS_PER_DAY)
        )
        self._cooldown_minutes: int = int(
            cfg.get("cooldown_minutes", DEFAULT_COOLDOWN_MINUTES)
        )
        self._max_similar_titles_pct: float = float(
            cfg.get("max_similar_titles_pct", _DEFAULT_MAX_SIMILAR_TITLES_PCT)
        )
        self._max_affiliate_link_density: float = float(
            cfg.get("max_affiliate_link_density", _DEFAULT_MAX_AFFILIATE_LINK_DENSITY)
        )
        self._new_domain_age_days: int = int(
            cfg.get("new_domain_age_days", _DEFAULT_NEW_DOMAIN_AGE_DAYS)
        )
        self._new_domain_max_posts: int = int(
            cfg.get("new_domain_max_posts_per_day", _DEFAULT_NEW_DOMAIN_MAX_POSTS_PER_DAY)
        )

        # In-memory posting history keyed by site_id.
        self._history: Dict[str, PostingRecord] = {}

        log_event(
            self._logger,
            "policy.posting.init",
            max_posts_per_day=self._max_posts_per_day,
            cooldown_minutes=self._cooldown_minutes,
        )

    # ------------------------------------------------------------------
    # History management
    # ------------------------------------------------------------------

    def record_post(self, site_id: str, *, posted_at: Optional[datetime] = None) -> None:
        """Record that a post was published to *site_id*.

        Parameters
        ----------
        site_id:
            Target site identifier.
        posted_at:
            UTC timestamp.  Defaults to now.
        """
        posted_at = posted_at or datetime.now(timezone.utc)
        record = self._history.setdefault(
            site_id, PostingRecord(site_id=site_id)
        )
        record.post_timestamps.append(posted_at)

    def set_domain_age(self, site_id: str, age_days: int) -> None:
        """Update the known domain age for *site_id*.

        Parameters
        ----------
        site_id:
            Target site identifier.
        age_days:
            Number of days the domain has been active.
        """
        record = self._history.setdefault(
            site_id, PostingRecord(site_id=site_id)
        )
        record.domain_age_days = age_days

    # ------------------------------------------------------------------
    # Core checks
    # ------------------------------------------------------------------

    def can_post(self, site_id: str) -> PostingVerdict:
        """Determine whether a new post is allowed for *site_id* right now.

        Evaluates all posting rules in sequence and returns the first
        blocking condition encountered, or an ALLOW verdict if all pass.

        Parameters
        ----------
        site_id:
            Target site identifier.

        Returns
        -------
        PostingVerdict
        """
        now = datetime.now(timezone.utc)
        record = self._history.get(site_id, PostingRecord(site_id=site_id))

        # 1. Cooldown
        cooldown_s = self._cooldown_minutes * 60
        cooldown_remaining = self._get_cooldown_remaining(record, now, cooldown_s)
        if cooldown_remaining > 0:
            verdict = PostingVerdict(
                allowed=False,
                reason=(
                    f"Cooldown active for '{site_id}': {cooldown_remaining:.0f}s remaining "
                    f"(minimum {self._cooldown_minutes}min between posts)."
                ),
                cooldown_remaining_s=cooldown_remaining,
                daily_remaining=self._daily_remaining(record, now),
                details={"check": "cooldown"},
            )
            log_event(
                self._logger,
                "policy.posting.blocked",
                site=site_id,
                reason="cooldown",
            )
            return verdict

        # 2. Daily limit
        daily_remaining = self._daily_remaining(record, now)
        if daily_remaining <= 0:
            verdict = PostingVerdict(
                allowed=False,
                reason=(
                    f"Daily posting limit reached for '{site_id}' "
                    f"({self._effective_max_posts(record)} posts/day)."
                ),
                daily_remaining=0,
                details={"check": "daily_limit"},
            )
            log_event(
                self._logger,
                "policy.posting.blocked",
                site=site_id,
                reason="daily_limit",
            )
            return verdict

        # 3. Domain reputation (conservative for new domains)
        if record.domain_age_days < self._new_domain_age_days:
            posts_today = self._posts_today(record, now)
            if posts_today >= self._new_domain_max_posts:
                verdict = PostingVerdict(
                    allowed=False,
                    reason=(
                        f"New domain ramp-up: '{site_id}' is {record.domain_age_days}d old "
                        f"(< {self._new_domain_age_days}d), limited to "
                        f"{self._new_domain_max_posts} posts/day."
                    ),
                    daily_remaining=0,
                    details={"check": "new_domain_ramp"},
                )
                log_event(
                    self._logger,
                    "policy.posting.blocked",
                    site=site_id,
                    reason="new_domain_ramp",
                )
                return verdict

        # All clear
        verdict = PostingVerdict(
            allowed=True,
            daily_remaining=daily_remaining,
            details={"check": "all_passed"},
        )
        log_event(
            self._logger,
            "policy.posting.allowed",
            site=site_id,
            daily_remaining=daily_remaining,
        )
        return verdict

    def get_cooldown(self, site_id: str) -> float:
        """Return seconds remaining in the cooldown window for *site_id*.

        Parameters
        ----------
        site_id:
            Target site identifier.

        Returns
        -------
        float
            Seconds until the next post is permitted.  ``0.0`` if no
            cooldown is active.
        """
        now = datetime.now(timezone.utc)
        record = self._history.get(site_id, PostingRecord(site_id=site_id))
        cooldown_s = self._cooldown_minutes * 60
        return max(0.0, self._get_cooldown_remaining(record, now, cooldown_s))

    def check_spam_risk(
        self,
        site_id: str,
        *,
        text: Optional[str] = None,
        title: Optional[str] = None,
        recent_titles: Optional[List[str]] = None,
        affiliate_link_count: int = 0,
    ) -> PostingVerdict:
        """Evaluate spam-risk signals for a pending post.

        Checks performed:
            1. Affiliate link density in content.
            2. Title similarity against recent posts.

        Parameters
        ----------
        site_id:
            Target site.
        text:
            Full content text (used for link-density check).
        title:
            Title of the post being evaluated.
        recent_titles:
            Titles of recently published posts on the same site.
        affiliate_link_count:
            Number of affiliate links in the content.

        Returns
        -------
        PostingVerdict
        """
        violations: List[str] = []
        details: Dict[str, Any] = {}

        # Affiliate link density
        if text and affiliate_link_count > 0:
            word_count = len(text.split())
            if word_count > 0:
                density = affiliate_link_count / word_count
                details["affiliate_link_density"] = round(density, 4)
                if density > self._max_affiliate_link_density:
                    violations.append(
                        f"Affiliate link density {density:.3f} exceeds max "
                        f"{self._max_affiliate_link_density:.3f}."
                    )

        # Title similarity
        if title and recent_titles:
            similar_count = self._count_similar_titles(title, recent_titles)
            similarity_pct = similar_count / len(recent_titles) if recent_titles else 0.0
            details["similar_titles_pct"] = round(similarity_pct, 3)
            if similarity_pct > self._max_similar_titles_pct:
                violations.append(
                    f"Title similarity {similarity_pct:.1%} exceeds max "
                    f"{self._max_similar_titles_pct:.1%} -- possible duplicate pattern."
                )

        if violations:
            verdict = PostingVerdict(
                allowed=False,
                reason="; ".join(violations),
                details={"check": "spam_risk", **details},
            )
            log_event(
                self._logger,
                "policy.posting.spam_risk",
                site=site_id,
                violations=len(violations),
            )
            return verdict

        return PostingVerdict(
            allowed=True,
            details={"check": "spam_risk_passed", **details},
        )

    def get_daily_remaining(self, site_id: str) -> int:
        """Return how many posts are still allowed today for *site_id*.

        Parameters
        ----------
        site_id:
            Target site identifier.

        Returns
        -------
        int
            Number of posts remaining.  May be zero or negative if the
            limit has been exceeded.
        """
        now = datetime.now(timezone.utc)
        record = self._history.get(site_id, PostingRecord(site_id=site_id))
        return self._daily_remaining(record, now)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _posts_today(self, record: PostingRecord, now: datetime) -> int:
        """Count posts made to this site on the same UTC date as *now*."""
        today = now.date()
        return sum(1 for ts in record.post_timestamps if ts.date() == today)

    def _effective_max_posts(self, record: PostingRecord) -> int:
        """Return the effective daily post limit considering domain age."""
        if record.domain_age_days < self._new_domain_age_days:
            return self._new_domain_max_posts
        return self._max_posts_per_day

    def _daily_remaining(self, record: PostingRecord, now: datetime) -> int:
        """Return posts remaining today."""
        used = self._posts_today(record, now)
        limit = self._effective_max_posts(record)
        return max(0, limit - used)

    def _get_cooldown_remaining(
        self, record: PostingRecord, now: datetime, cooldown_s: float
    ) -> float:
        """Return seconds remaining in the cooldown, or 0 if none."""
        if not record.post_timestamps:
            return 0.0
        last_post = record.post_timestamps[-1]
        elapsed = (now - last_post).total_seconds()
        return max(0.0, cooldown_s - elapsed)

    @staticmethod
    def _count_similar_titles(title: str, recent_titles: List[str]) -> int:
        """Count how many recent titles share significant word overlap with *title*.

        Uses a simple Jaccard-style word overlap: two titles are considered
        similar if they share more than 60 % of their words.
        """
        title_words = set(title.lower().split())
        if not title_words:
            return 0

        similar = 0
        for other in recent_titles:
            other_words = set(other.lower().split())
            if not other_words:
                continue
            union = title_words | other_words
            intersection = title_words & other_words
            jaccard = len(intersection) / len(union) if union else 0.0
            if jaccard > 0.6:
                similar += 1
        return similar

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"PostingPolicy("
            f"max_posts_per_day={self._max_posts_per_day}, "
            f"cooldown_min={self._cooldown_minutes}, "
            f"sites_tracked={len(self._history)})"
        )
