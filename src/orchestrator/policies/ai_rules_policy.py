"""
orchestrator.policies.ai_rules_policy
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Runtime enforcement of the rules codified in ``AI_RULES.md``.

This policy is consulted **before** any content is published or any
agent performs a side-effectful action.  It validates:

    - **Content quality** -- minimum word count, quality score, duplicate check.
    - **FTC compliance** -- affiliate disclosures are present.
    - **No black-hat SEO** -- keyword density within limits, no cloaking signals.
    - **Claim filtering** -- health, financial, and legal claims flagged for review.

The policy returns structured verdicts so the orchestrator can decide
whether to proceed, block, or request human review.

Design references:
    - AI_RULES.md  (Content Rules #1 -- #5, LLM Usage Rules #4)
    - config/thresholds.yaml  (``performance`` section)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum, unique
from typing import Any, Dict, List, Optional, Set

from core.constants import (
    DEFAULT_KEYWORD_DENSITY,
    DEFAULT_MIN_WORD_COUNT,
    DEFAULT_QUALITY_THRESHOLD,
)
from core.errors import ContentPolicyViolationError
from core.logger import get_logger, log_event


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

@unique
class PolicyVerdict(str, Enum):
    """Outcome of a policy check."""

    ALLOW = "allow"
    BLOCK = "block"
    REVIEW = "review"  # human review required

    def __str__(self) -> str:
        return self.value


@dataclass
class PolicyResult:
    """Structured result of a single policy evaluation.

    Attributes
    ----------
    verdict:
        Whether the action is allowed, blocked, or requires review.
    violations:
        List of human-readable violation descriptions.
    details:
        Machine-readable context for each check performed.
    """

    verdict: PolicyVerdict = PolicyVerdict.ALLOW
    violations: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_allowed(self) -> bool:
        """Convenience: ``True`` when the verdict is ALLOW."""
        return self.verdict == PolicyVerdict.ALLOW


# ---------------------------------------------------------------------------
# Common patterns
# ---------------------------------------------------------------------------

# Regex patterns that indicate potential black-hat SEO.
_BLACKHAT_PATTERNS: List[re.Pattern[str]] = [
    re.compile(r"display\s*:\s*none", re.IGNORECASE),
    re.compile(r"visibility\s*:\s*hidden", re.IGNORECASE),
    re.compile(r"font-size\s*:\s*0", re.IGNORECASE),
    re.compile(r"color\s*:\s*(?:#fff(?:fff)?|white)\s*;\s*background\s*:\s*(?:#fff(?:fff)?|white)", re.IGNORECASE),
]

# Disclosure phrases that satisfy FTC requirements.
_FTC_DISCLOSURE_PHRASES: List[str] = [
    "affiliate link",
    "affiliate commission",
    "we may earn",
    "paid partnership",
    "sponsored",
    "commission at no extra cost",
    "advertising disclosure",
    "material connection",
]

# Sensitive claim categories that require review.
_SENSITIVE_CLAIM_PATTERNS: Dict[str, re.Pattern[str]] = {
    "health": re.compile(
        r"\b(cure[sd]?|treat[sd]?|heal[sd]?|prevent[sd]?|diagnos[ei]s?|miracle|clinically proven)\b",
        re.IGNORECASE,
    ),
    "financial": re.compile(
        r"\b(guaranteed? returns?|risk[- ]?free|get rich|passive income guaranteed|no[- ]?risk)\b",
        re.IGNORECASE,
    ),
    "legal": re.compile(
        r"\b(legal advice|not? liable|lawsuit|sue|attorney[- ]?client)\b",
        re.IGNORECASE,
    ),
}


# ---------------------------------------------------------------------------
# AIRulesPolicy
# ---------------------------------------------------------------------------

class AIRulesPolicy:
    """Enforces AI_RULES.md at runtime before content is published or claims are made.

    Parameters
    ----------
    config:
        Policy-specific overrides (e.g. from ``config/thresholds.yaml``).
        Recognised keys: ``min_word_count``, ``min_quality_score``,
        ``max_keyword_density``.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self._logger: logging.Logger = get_logger("policy.ai_rules")
        cfg = config or {}

        self._min_word_count: int = int(
            cfg.get("min_word_count", DEFAULT_MIN_WORD_COUNT)
        )
        self._min_quality_score: float = float(
            cfg.get("min_quality_score", DEFAULT_QUALITY_THRESHOLD)
        )
        self._max_keyword_density: float = float(
            cfg.get("max_keyword_density", DEFAULT_KEYWORD_DENSITY)
        )

        log_event(
            self._logger,
            "policy.ai_rules.init",
            min_word_count=self._min_word_count,
            min_quality_score=self._min_quality_score,
            max_keyword_density=self._max_keyword_density,
        )

    # ------------------------------------------------------------------
    # Content checks
    # ------------------------------------------------------------------

    def check_content(
        self,
        text: str,
        *,
        quality_score: Optional[float] = None,
        target_keyword: Optional[str] = None,
    ) -> PolicyResult:
        """Validate a content piece against AI_RULES.md content rules.

        Checks performed:
            1. Minimum word count.
            2. Quality score threshold.
            3. Keyword density within acceptable range.
            4. No black-hat SEO patterns.
            5. No duplicate-content signal (placeholder -- external de-dup
               service integration is future work).

        Parameters
        ----------
        text:
            The full text of the content piece.
        quality_score:
            Pre-computed quality score on a 0-1 scale.  ``None`` skips the
            quality gate.
        target_keyword:
            Primary SEO keyword.  ``None`` skips the density check.

        Returns
        -------
        PolicyResult
        """
        violations: List[str] = []
        details: Dict[str, Any] = {}

        # 1. Word count
        word_count = len(text.split())
        details["word_count"] = word_count
        if word_count < self._min_word_count:
            violations.append(
                f"Word count {word_count} is below minimum {self._min_word_count}."
            )

        # 2. Quality score
        if quality_score is not None:
            details["quality_score"] = quality_score
            if quality_score < self._min_quality_score:
                violations.append(
                    f"Quality score {quality_score:.2f} is below threshold "
                    f"{self._min_quality_score:.2f}."
                )

        # 3. Keyword density
        if target_keyword and word_count > 0:
            kw_lower = target_keyword.lower()
            text_lower = text.lower()
            kw_count = text_lower.count(kw_lower)
            density = kw_count / word_count
            details["keyword_density"] = round(density, 4)
            if density > self._max_keyword_density:
                violations.append(
                    f"Keyword density {density:.3f} exceeds max "
                    f"{self._max_keyword_density:.3f} (possible keyword stuffing)."
                )

        # 4. Black-hat SEO patterns
        blackhat_hits: List[str] = []
        for pattern in _BLACKHAT_PATTERNS:
            if pattern.search(text):
                blackhat_hits.append(pattern.pattern)
        if blackhat_hits:
            details["blackhat_patterns"] = blackhat_hits
            violations.append(
                f"Black-hat SEO patterns detected: {blackhat_hits}."
            )

        # Build verdict
        verdict = PolicyVerdict.ALLOW if not violations else PolicyVerdict.BLOCK
        result = PolicyResult(verdict=verdict, violations=violations, details=details)

        log_event(
            self._logger,
            "policy.ai_rules.check_content",
            verdict=str(verdict),
            violation_count=len(violations),
        )
        return result

    # ------------------------------------------------------------------
    # Publish-action gate
    # ------------------------------------------------------------------

    def check_publish_action(self, text: str) -> PolicyResult:
        """Verify that content has proper FTC affiliate disclosures before publishing.

        Parameters
        ----------
        text:
            The full text (including any disclosure sections) of the content.

        Returns
        -------
        PolicyResult
        """
        violations: List[str] = []
        details: Dict[str, Any] = {}

        text_lower = text.lower()
        found_disclosures: List[str] = [
            phrase for phrase in _FTC_DISCLOSURE_PHRASES if phrase in text_lower
        ]
        details["disclosures_found"] = found_disclosures

        if not found_disclosures:
            violations.append(
                "No FTC affiliate disclosure found.  Content must include a "
                "clear disclosure before publishing (AI_RULES.md, Content Rule #2)."
            )

        verdict = PolicyVerdict.ALLOW if not violations else PolicyVerdict.BLOCK
        result = PolicyResult(verdict=verdict, violations=violations, details=details)

        log_event(
            self._logger,
            "policy.ai_rules.check_publish",
            verdict=str(verdict),
            disclosures=len(found_disclosures),
        )
        return result

    # ------------------------------------------------------------------
    # Claim check
    # ------------------------------------------------------------------

    def check_claim(self, text: str) -> PolicyResult:
        """Scan text for sensitive claims (health, financial, legal) that require review.

        Claims are not automatically blocked -- they are flagged for human
        review per AI_RULES.md Risk Management #2.

        Parameters
        ----------
        text:
            Content text to scan.

        Returns
        -------
        PolicyResult
            Verdict is ``REVIEW`` if sensitive claims are detected, ``ALLOW``
            otherwise.
        """
        violations: List[str] = []
        flagged_categories: Dict[str, List[str]] = {}

        for category, pattern in _SENSITIVE_CLAIM_PATTERNS.items():
            matches = pattern.findall(text)
            if matches:
                unique_matches = sorted(set(m.lower() for m in matches))
                flagged_categories[category] = unique_matches
                violations.append(
                    f"Sensitive {category} claim(s) detected: {unique_matches}. "
                    f"Human review required."
                )

        details: Dict[str, Any] = {"flagged_categories": flagged_categories}

        if violations:
            verdict = PolicyVerdict.REVIEW
        else:
            verdict = PolicyVerdict.ALLOW

        result = PolicyResult(verdict=verdict, violations=violations, details=details)

        log_event(
            self._logger,
            "policy.ai_rules.check_claim",
            verdict=str(verdict),
            categories=list(flagged_categories.keys()),
        )
        return result

    # ------------------------------------------------------------------
    # Composite gate
    # ------------------------------------------------------------------

    def is_allowed(
        self,
        text: str,
        *,
        quality_score: Optional[float] = None,
        target_keyword: Optional[str] = None,
        check_claims: bool = True,
        check_disclosure: bool = True,
    ) -> PolicyResult:
        """Run all applicable checks and return a single combined verdict.

        This is the recommended top-level entry-point for pre-publish
        validation.

        Parameters
        ----------
        text:
            Full content text.
        quality_score:
            Optional pre-computed quality score (0-1).
        target_keyword:
            Primary SEO keyword for density analysis.
        check_claims:
            Whether to run sensitive-claim scanning.
        check_disclosure:
            Whether to verify FTC disclosures.

        Returns
        -------
        PolicyResult
            Combined result.  The verdict is the *most restrictive* across
            all individual checks (BLOCK > REVIEW > ALLOW).
        """
        all_violations: List[str] = []
        all_details: Dict[str, Any] = {}

        # Content quality / SEO
        content_result = self.check_content(
            text, quality_score=quality_score, target_keyword=target_keyword
        )
        all_violations.extend(content_result.violations)
        all_details["content"] = content_result.details

        # FTC disclosure
        if check_disclosure:
            disclosure_result = self.check_publish_action(text)
            all_violations.extend(disclosure_result.violations)
            all_details["disclosure"] = disclosure_result.details

        # Sensitive claims
        if check_claims:
            claim_result = self.check_claim(text)
            all_violations.extend(claim_result.violations)
            all_details["claims"] = claim_result.details

        # Determine most restrictive verdict
        if any(v.startswith("Word count") or v.startswith("Quality score")
               or v.startswith("Keyword density") or v.startswith("Black-hat")
               or v.startswith("No FTC") for v in all_violations):
            verdict = PolicyVerdict.BLOCK
        elif any("review required" in v.lower() for v in all_violations):
            verdict = PolicyVerdict.REVIEW
        else:
            verdict = PolicyVerdict.ALLOW

        result = PolicyResult(
            verdict=verdict, violations=all_violations, details=all_details
        )

        log_event(
            self._logger,
            "policy.ai_rules.is_allowed",
            verdict=str(verdict),
            total_violations=len(all_violations),
        )

        if verdict == PolicyVerdict.BLOCK:
            self._logger.warning(
                "Content BLOCKED by AI rules policy: %s", all_violations
            )

        return result

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"AIRulesPolicy("
            f"min_words={self._min_word_count}, "
            f"min_quality={self._min_quality_score}, "
            f"max_kw_density={self._max_keyword_density})"
        )
