"""
orchestrator.policies.risk_policy
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Enforces risk rules for domains, claims, compliance, and blacklists.

Every action that touches external systems (publishing, affiliate-link
insertion, network API calls) is routed through this policy first.  It
evaluates the risk level and either allows the action, blocks it, or
escalates for human review.

Design references:
    - AI_RULES.md  Risk Management #1 -- #5
    - config/thresholds.yaml
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum, unique
from typing import Any, Dict, FrozenSet, List, Optional, Set

from src.core.constants import RiskLevel
from src.core.errors import RiskPolicyViolationError
from src.core.logger import get_logger, log_event


# ---------------------------------------------------------------------------
# Risk assessment result
# ---------------------------------------------------------------------------

@dataclass
class RiskAssessment:
    """Structured result of a risk evaluation.

    Attributes
    ----------
    level:
        Computed risk level.
    allowed:
        ``True`` if the action may proceed.
    reasons:
        Human-readable reasons explaining the assessment.
    details:
        Machine-readable context.
    """

    level: RiskLevel = RiskLevel.LOW
    allowed: bool = True
    reasons: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Default blacklists
# ---------------------------------------------------------------------------

# Niches that are never promoted.
_DEFAULT_BLACKLISTED_NICHES: FrozenSet[str] = frozenset({
    "gambling",
    "tobacco",
    "weapons",
    "counterfeit",
    "illegal_substances",
    "adult_explicit",
})

# Merchants/networks that have been banned (placeholder -- loaded from DB/config
# in production).
_DEFAULT_BLACKLISTED_MERCHANTS: FrozenSet[str] = frozenset()

# Domain patterns that must never appear as affiliate targets.
_DEFAULT_BLACKLISTED_DOMAIN_PATTERNS: List[re.Pattern[str]] = [
    re.compile(r".*\.ru$", re.IGNORECASE),
    re.compile(r".*\.cn$", re.IGNORECASE),
]

# Terms of Service keywords that indicate restricted programmes.
_TOS_RESTRICTED_KEYWORDS: FrozenSet[str] = frozenset({
    "incentivized traffic",
    "cookie stuffing",
    "trademark bidding",
    "forced click",
    "pop-under",
})


# ---------------------------------------------------------------------------
# RiskPolicy
# ---------------------------------------------------------------------------

class RiskPolicy:
    """Evaluate and enforce risk rules for the OpenClaw system.

    Parameters
    ----------
    config:
        Policy overrides.  Recognised keys:
            ``blacklisted_niches``, ``blacklisted_merchants``,
            ``max_risk_level`` (the highest level that is auto-allowed;
            defaults to ``"medium"``).
    """

    # Risk levels ordered from safest to most dangerous.
    _RISK_ORDERING: Dict[RiskLevel, int] = {
        RiskLevel.LOW: 0,
        RiskLevel.MEDIUM: 1,
        RiskLevel.HIGH: 2,
        RiskLevel.CRITICAL: 3,
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self._logger: logging.Logger = get_logger("policy.risk")
        cfg = config or {}

        # Blacklists (mutable copies so they can be updated at runtime).
        raw_niches = cfg.get("blacklisted_niches", None)
        self._blacklisted_niches: Set[str] = (
            set(raw_niches) if raw_niches else set(_DEFAULT_BLACKLISTED_NICHES)
        )

        raw_merchants = cfg.get("blacklisted_merchants", None)
        self._blacklisted_merchants: Set[str] = (
            set(raw_merchants) if raw_merchants else set(_DEFAULT_BLACKLISTED_MERCHANTS)
        )

        self._blacklisted_domain_patterns: List[re.Pattern[str]] = list(
            _DEFAULT_BLACKLISTED_DOMAIN_PATTERNS
        )

        # The highest risk level that is auto-allowed without human review.
        max_level_str = cfg.get("max_risk_level", "medium")
        self._max_auto_allow: RiskLevel = RiskLevel(max_level_str)

        log_event(
            self._logger,
            "policy.risk.init",
            blacklisted_niches=len(self._blacklisted_niches),
            blacklisted_merchants=len(self._blacklisted_merchants),
            max_auto_allow=str(self._max_auto_allow),
        )

    # ------------------------------------------------------------------
    # Blacklist checks
    # ------------------------------------------------------------------

    def is_blacklisted(
        self,
        *,
        niche: Optional[str] = None,
        merchant: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> bool:
        """Return ``True`` if any of the provided identifiers are blacklisted.

        Parameters
        ----------
        niche:
            Niche category to check.
        merchant:
            Merchant or network name.
        domain:
            Target domain URL or hostname.

        Returns
        -------
        bool
        """
        if niche and niche.lower() in self._blacklisted_niches:
            log_event(
                self._logger,
                "policy.risk.blacklisted",
                type="niche",
                value=niche,
            )
            return True

        if merchant and merchant.lower() in self._blacklisted_merchants:
            log_event(
                self._logger,
                "policy.risk.blacklisted",
                type="merchant",
                value=merchant,
            )
            return True

        if domain:
            for pattern in self._blacklisted_domain_patterns:
                if pattern.search(domain):
                    log_event(
                        self._logger,
                        "policy.risk.blacklisted",
                        type="domain",
                        value=domain,
                        pattern=pattern.pattern,
                    )
                    return True

        return False

    # ------------------------------------------------------------------
    # Compliance check
    # ------------------------------------------------------------------

    def check_compliance(
        self,
        *,
        network_name: Optional[str] = None,
        tos_text: Optional[str] = None,
        action_description: str = "",
    ) -> RiskAssessment:
        """Verify that a planned action does not violate network TOS.

        Scans *tos_text* (or the action description) for restricted
        keywords that would indicate a TOS violation.

        Parameters
        ----------
        network_name:
            Name of the affiliate network (for logging).
        tos_text:
            The full text of the network's terms-of-service, if available.
        action_description:
            A short description of the action being evaluated.

        Returns
        -------
        RiskAssessment
        """
        text_to_scan = (tos_text or "") + " " + action_description
        text_lower = text_to_scan.lower()

        violations: List[str] = []
        flagged_keywords: List[str] = []

        for keyword in _TOS_RESTRICTED_KEYWORDS:
            if keyword in text_lower:
                flagged_keywords.append(keyword)
                violations.append(
                    f"TOS-restricted keyword detected: '{keyword}'."
                )

        level = RiskLevel.LOW if not violations else RiskLevel.HIGH
        allowed = self._level_within_auto_allow(level)

        assessment = RiskAssessment(
            level=level,
            allowed=allowed,
            reasons=violations,
            details={
                "network": network_name,
                "flagged_keywords": flagged_keywords,
            },
        )

        log_event(
            self._logger,
            "policy.risk.compliance",
            network=network_name,
            risk_level=str(level),
            violations=len(violations),
        )
        return assessment

    # ------------------------------------------------------------------
    # Risk level assessment
    # ------------------------------------------------------------------

    def get_risk_level(
        self,
        *,
        niche: Optional[str] = None,
        merchant: Optional[str] = None,
        domain: Optional[str] = None,
        agent_risk: Optional[str] = None,
        has_sensitive_claims: bool = False,
    ) -> RiskLevel:
        """Compute the aggregate risk level for a given action context.

        The returned level is the *maximum* across all contributing
        factors.

        Parameters
        ----------
        niche:
            Niche category.
        merchant:
            Merchant or network name.
        domain:
            Target domain.
        agent_risk:
            The agent's configured risk level string (from ``agents.yaml``).
        has_sensitive_claims:
            Whether the content contains health/financial/legal claims.

        Returns
        -------
        RiskLevel
        """
        levels: List[RiskLevel] = []

        # Blacklist => CRITICAL
        if self.is_blacklisted(niche=niche, merchant=merchant, domain=domain):
            levels.append(RiskLevel.CRITICAL)

        # Sensitive claims => HIGH
        if has_sensitive_claims:
            levels.append(RiskLevel.HIGH)

        # Agent's configured risk
        if agent_risk:
            try:
                levels.append(RiskLevel(agent_risk))
            except ValueError:
                self._logger.warning(
                    "Unknown agent risk level '%s' -- treating as MEDIUM.", agent_risk
                )
                levels.append(RiskLevel.MEDIUM)

        if not levels:
            return RiskLevel.LOW

        # Return the highest risk.
        return max(levels, key=lambda rl: self._RISK_ORDERING.get(rl, 0))

    # ------------------------------------------------------------------
    # Composite assessment
    # ------------------------------------------------------------------

    def assess_risk(
        self,
        *,
        niche: Optional[str] = None,
        merchant: Optional[str] = None,
        domain: Optional[str] = None,
        agent_risk: Optional[str] = None,
        has_sensitive_claims: bool = False,
        network_name: Optional[str] = None,
        tos_text: Optional[str] = None,
        action_description: str = "",
    ) -> RiskAssessment:
        """Perform a full risk assessment combining blacklist, compliance, and claim checks.

        This is the recommended top-level entry-point.

        Parameters
        ----------
        niche:
            Niche category.
        merchant:
            Merchant or network name.
        domain:
            Target domain.
        agent_risk:
            Agent's configured risk level.
        has_sensitive_claims:
            Whether content contains sensitive claims.
        network_name:
            Affiliate network name.
        tos_text:
            Network terms-of-service text.
        action_description:
            Description of the action being evaluated.

        Returns
        -------
        RiskAssessment
        """
        reasons: List[str] = []
        details: Dict[str, Any] = {}

        # 1. Blacklist
        if self.is_blacklisted(niche=niche, merchant=merchant, domain=domain):
            reasons.append(
                f"Blacklisted entity detected (niche={niche}, "
                f"merchant={merchant}, domain={domain})."
            )
            details["blacklisted"] = True
        else:
            details["blacklisted"] = False

        # 2. Compliance
        compliance = self.check_compliance(
            network_name=network_name,
            tos_text=tos_text,
            action_description=action_description,
        )
        reasons.extend(compliance.reasons)
        details["compliance"] = compliance.details

        # 3. Sensitive claims
        if has_sensitive_claims:
            reasons.append(
                "Content contains sensitive claims (health/financial/legal) "
                "-- elevated risk."
            )
            details["sensitive_claims"] = True
        else:
            details["sensitive_claims"] = False

        # 4. Aggregate level
        level = self.get_risk_level(
            niche=niche,
            merchant=merchant,
            domain=domain,
            agent_risk=agent_risk,
            has_sensitive_claims=has_sensitive_claims,
        )
        allowed = self._level_within_auto_allow(level)

        if not allowed:
            reasons.append(
                f"Risk level {level.value} exceeds auto-allow threshold "
                f"{self._max_auto_allow.value}."
            )

        assessment = RiskAssessment(
            level=level,
            allowed=allowed,
            reasons=reasons,
            details=details,
        )

        log_event(
            self._logger,
            "policy.risk.assessed",
            risk_level=str(level),
            allowed=allowed,
            reason_count=len(reasons),
        )

        if not allowed:
            self._logger.warning(
                "Action BLOCKED by risk policy (level=%s): %s",
                level.value,
                reasons,
            )

        return assessment

    # ------------------------------------------------------------------
    # Blacklist management (runtime updates)
    # ------------------------------------------------------------------

    def add_blacklisted_niche(self, niche: str) -> None:
        """Add a niche to the blacklist at runtime.

        Parameters
        ----------
        niche:
            Niche category string to blacklist.
        """
        self._blacklisted_niches.add(niche.lower())
        log_event(
            self._logger, "policy.risk.blacklist_add", type="niche", value=niche
        )

    def add_blacklisted_merchant(self, merchant: str) -> None:
        """Add a merchant to the blacklist at runtime.

        Parameters
        ----------
        merchant:
            Merchant name to blacklist.
        """
        self._blacklisted_merchants.add(merchant.lower())
        log_event(
            self._logger, "policy.risk.blacklist_add", type="merchant", value=merchant
        )

    def remove_blacklisted_niche(self, niche: str) -> bool:
        """Remove a niche from the blacklist.

        Parameters
        ----------
        niche:
            Niche category string to remove.

        Returns
        -------
        bool
            ``True`` if the niche was present and removed.
        """
        lowered = niche.lower()
        if lowered in self._blacklisted_niches:
            self._blacklisted_niches.discard(lowered)
            log_event(
                self._logger,
                "policy.risk.blacklist_remove",
                type="niche",
                value=niche,
            )
            return True
        return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _level_within_auto_allow(self, level: RiskLevel) -> bool:
        """Return ``True`` if *level* does not exceed the auto-allow ceiling."""
        return self._RISK_ORDERING.get(level, 99) <= self._RISK_ORDERING.get(
            self._max_auto_allow, 1
        )

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"RiskPolicy("
            f"max_auto_allow={self._max_auto_allow.value}, "
            f"blacklisted_niches={len(self._blacklisted_niches)}, "
            f"blacklisted_merchants={len(self._blacklisted_merchants)})"
        )
