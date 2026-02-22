"""
pipelines.content.fact_check
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Verify factual claims in article drafts before publication.  Checks
product details, pricing accuracy, and flags unverifiable claims to
prevent misleading content from going live.

When ``block_on_failure`` is set in ``config/pipelines.yaml``
(``content.steps[3]``), articles that fail fact-checking are held in
draft status until issues are resolved.

Design references:
    - config/pipelines.yaml  ``content.steps[3]``  (enabled, block_on_failure)
    - ARCHITECTURE.md  Section 3 (Content Pipeline)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, unique
from typing import Any, Dict, List, Optional

from src.core.errors import ContentValidationError, PipelineStepError
from src.core.logger import get_logger, log_event

logger = get_logger("pipelines.content.fact_check")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

@unique
class ClaimSeverity(str, Enum):
    """Severity level of a flagged claim."""

    INFO = "info"          # Minor observation, not blocking
    WARNING = "warning"    # Should be reviewed before publish
    ERROR = "error"        # Must be fixed before publish


@unique
class ClaimStatus(str, Enum):
    """Verification status of a claim."""

    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    INACCURATE = "inaccurate"
    OUTDATED = "outdated"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FactCheckResult:
    """Result of checking a single claim.

    Attributes
    ----------
    claim_text:
        The extracted claim from the article.
    status:
        Verification result.
    severity:
        How serious the issue is (INFO, WARNING, ERROR).
    source:
        Where the claim was verified against (offer data, external API, etc.).
    details:
        Explanation of the finding.
    suggestion:
        Recommended fix if the claim is inaccurate or unverifiable.
    """

    claim_text: str
    status: ClaimStatus = ClaimStatus.UNVERIFIED
    severity: ClaimSeverity = ClaimSeverity.INFO
    source: str = ""
    details: str = ""
    suggestion: str = ""


@dataclass
class FactCheckReport:
    """Aggregate fact-check report for an entire article.

    Attributes
    ----------
    article_title:
        Title of the checked article.
    total_claims:
        Number of claims extracted and checked.
    verified_count:
        Claims confirmed as accurate.
    unverified_count:
        Claims that could not be verified either way.
    inaccurate_count:
        Claims found to be factually wrong.
    results:
        Individual :class:`FactCheckResult` for each claim.
    passed:
        Whether the article passes fact-checking (no ERROR-severity issues).
    checked_at:
        UTC timestamp of the check.
    """

    article_title: str = ""
    total_claims: int = 0
    verified_count: int = 0
    unverified_count: int = 0
    inaccurate_count: int = 0
    results: List[FactCheckResult] = field(default_factory=list)
    passed: bool = True
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Claim extraction
# ---------------------------------------------------------------------------

# Patterns that often indicate factual claims in affiliate content
_PRICE_PATTERN = re.compile(
    r'\$[\d,]+(?:\.\d{2})?(?:\s*(?:per|/)\s*(?:month|year|mo|yr))?',
    re.IGNORECASE,
)
_PERCENTAGE_PATTERN = re.compile(r'\d+(?:\.\d+)?\s*%')
_NUMERIC_CLAIM_PATTERN = re.compile(
    r'(?:up to|over|more than|less than|approximately|about|around)\s+\d+',
    re.IGNORECASE,
)
_GUARANTEE_PATTERN = re.compile(
    r'(?:guarantee|warranty|money.?back|refund|free trial|risk.?free)',
    re.IGNORECASE,
)


def _extract_claims(text: str) -> List[str]:
    """Extract sentences containing factual claims from article text.

    Identifies sentences that contain prices, percentages, numeric
    assertions, or guarantee language.

    Parameters
    ----------
    text:
        The full article text.

    Returns
    -------
    list[str]
        Sentences containing potential factual claims.
    """
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    claims: List[str] = []

    for sentence in sentences:
        if any(
            pattern.search(sentence)
            for pattern in [
                _PRICE_PATTERN,
                _PERCENTAGE_PATTERN,
                _NUMERIC_CLAIM_PATTERN,
                _GUARANTEE_PATTERN,
            ]
        ):
            claims.append(sentence.strip())

    return claims


# ---------------------------------------------------------------------------
# Verification functions
# ---------------------------------------------------------------------------

def verify_product_details(
    claim: str,
    offer_data: Dict[str, Any],
) -> FactCheckResult:
    """Verify a claim against the known offer data.

    Cross-references extracted claims with the normalized offer dict to
    confirm product names, merchant names, and basic attributes.

    Parameters
    ----------
    claim:
        A sentence containing a factual assertion.
    offer_data:
        Normalized offer dict with ground-truth data.

    Returns
    -------
    FactCheckResult
        Verification result for this claim.
    """
    product_name = offer_data.get("name", "").lower()
    merchant = offer_data.get("merchant", "").lower()
    claim_lower = claim.lower()

    # Check if the claim references the correct product/merchant
    if product_name and product_name in claim_lower:
        return FactCheckResult(
            claim_text=claim,
            status=ClaimStatus.VERIFIED,
            severity=ClaimSeverity.INFO,
            source="offer_data",
            details=f"Product name '{offer_data.get('name')}' matches offer record.",
        )

    if merchant and merchant in claim_lower:
        return FactCheckResult(
            claim_text=claim,
            status=ClaimStatus.VERIFIED,
            severity=ClaimSeverity.INFO,
            source="offer_data",
            details=f"Merchant '{offer_data.get('merchant')}' matches offer record.",
        )

    return FactCheckResult(
        claim_text=claim,
        status=ClaimStatus.UNVERIFIED,
        severity=ClaimSeverity.INFO,
        source="offer_data",
        details="Claim references entities not directly verifiable against offer data.",
    )


def check_price_accuracy(
    claim: str,
    offer_data: Dict[str, Any],
    *,
    tolerance_pct: float = 0.10,
) -> FactCheckResult:
    """Check if price claims in the article match the offer data.

    Extracts dollar amounts from the claim and compares them against the
    known average order value, flagging discrepancies beyond the tolerance.

    Parameters
    ----------
    claim:
        A sentence containing a price reference.
    offer_data:
        Normalized offer dict with ``avg_order_value``.
    tolerance_pct:
        Acceptable percentage deviation (default 10%).

    Returns
    -------
    FactCheckResult
        Price accuracy result.
    """
    aov = offer_data.get("avg_order_value", 0.0)
    if aov <= 0:
        return FactCheckResult(
            claim_text=claim,
            status=ClaimStatus.UNVERIFIED,
            severity=ClaimSeverity.INFO,
            source="offer_data",
            details="No reference price available in offer data.",
        )

    # Extract dollar amounts from the claim
    price_matches = _PRICE_PATTERN.findall(claim)
    if not price_matches:
        return FactCheckResult(
            claim_text=claim,
            status=ClaimStatus.UNVERIFIED,
            severity=ClaimSeverity.INFO,
            source="price_check",
            details="No price amount detected in this claim.",
        )

    for price_str in price_matches:
        cleaned = re.sub(r'[^\d.]', '', price_str.split("/")[0].split("per")[0])
        try:
            claimed_price = float(cleaned)
        except ValueError:
            continue

        deviation = abs(claimed_price - aov) / aov if aov > 0 else 0
        if deviation <= tolerance_pct:
            return FactCheckResult(
                claim_text=claim,
                status=ClaimStatus.VERIFIED,
                severity=ClaimSeverity.INFO,
                source="price_check",
                details=(
                    f"Claimed price ${claimed_price:.2f} is within "
                    f"{tolerance_pct*100:.0f}% of reference AOV ${aov:.2f}."
                ),
            )
        else:
            return FactCheckResult(
                claim_text=claim,
                status=ClaimStatus.INACCURATE,
                severity=ClaimSeverity.ERROR,
                source="price_check",
                details=(
                    f"Claimed price ${claimed_price:.2f} deviates "
                    f"{deviation*100:.1f}% from reference AOV ${aov:.2f}."
                ),
                suggestion=(
                    f"Update the price to reflect the current value of "
                    f"approximately ${aov:.2f}, or add a disclaimer that "
                    f"prices may vary."
                ),
            )

    return FactCheckResult(
        claim_text=claim,
        status=ClaimStatus.UNVERIFIED,
        severity=ClaimSeverity.INFO,
        source="price_check",
        details="Could not parse a numeric price from the claim.",
    )


def flag_unverifiable_claims(
    claim: str,
    offer_data: Dict[str, Any],
) -> FactCheckResult:
    """Flag claims that cannot be verified against available data.

    Identifies superlative language, unsubstantiated statistics, and
    guarantee claims that may require external verification or sourcing.

    Parameters
    ----------
    claim:
        A sentence to evaluate.
    offer_data:
        Normalized offer dict (used for context).

    Returns
    -------
    FactCheckResult
        Flagging result with suggestions for improvement.
    """
    claim_lower = claim.lower()

    # Check for superlative/absolute claims
    superlatives = [
        "best", "worst", "fastest", "cheapest", "most popular",
        "number one", "#1", "guaranteed", "proven", "clinically",
    ]
    for word in superlatives:
        if word in claim_lower:
            return FactCheckResult(
                claim_text=claim,
                status=ClaimStatus.UNVERIFIED,
                severity=ClaimSeverity.WARNING,
                source="claim_analysis",
                details=f"Contains superlative/absolute language: '{word}'.",
                suggestion=(
                    f"Qualify the claim with 'one of the', 'among the', or "
                    f"cite a specific source for the '{word}' assertion."
                ),
            )

    # Check for unattributed statistics
    if _PERCENTAGE_PATTERN.search(claim) or _NUMERIC_CLAIM_PATTERN.search(claim):
        # See if the claim includes attribution
        attribution_markers = ["according to", "based on", "reported by", "study", "survey", "data from"]
        has_attribution = any(marker in claim_lower for marker in attribution_markers)
        if not has_attribution:
            return FactCheckResult(
                claim_text=claim,
                status=ClaimStatus.UNVERIFIED,
                severity=ClaimSeverity.WARNING,
                source="claim_analysis",
                details="Contains numeric claim without attribution.",
                suggestion="Add a source citation or qualify with 'approximately' / 'estimated'.",
            )

    # Check for guarantee/warranty claims
    if _GUARANTEE_PATTERN.search(claim):
        merchant = offer_data.get("merchant", "")
        return FactCheckResult(
            claim_text=claim,
            status=ClaimStatus.UNVERIFIED,
            severity=ClaimSeverity.WARNING,
            source="claim_analysis",
            details="Contains guarantee/warranty language that should be verified with the merchant.",
            suggestion=f"Verify this claim directly with {merchant}'s official terms and conditions.",
        )

    return FactCheckResult(
        claim_text=claim,
        status=ClaimStatus.VERIFIED,
        severity=ClaimSeverity.INFO,
        source="claim_analysis",
        details="No problematic patterns detected.",
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def fact_check_claims(
    article_text: str,
    article_title: str,
    offer_data: Dict[str, Any],
    *,
    block_on_failure: bool = True,
) -> FactCheckReport:
    """Run full fact-checking pipeline on an article's text content.

    Extracts factual claims, verifies product details, checks price
    accuracy, and flags unverifiable assertions.  Returns a comprehensive
    report with pass/fail determination.

    Parameters
    ----------
    article_text:
        The full article text (all sections concatenated).
    article_title:
        Article title for the report.
    offer_data:
        Normalized offer dict as ground truth.
    block_on_failure:
        If ``True`` and any ERROR-severity issues are found, the report
        ``passed`` field is set to ``False``.

    Returns
    -------
    FactCheckReport
        Aggregate report with individual claim results.

    Raises
    ------
    ContentValidationError
        If *block_on_failure* is ``True`` and critical issues are found.
    """
    log_event(logger, "fact_check.start", title=article_title)

    claims = _extract_claims(article_text)
    results: List[FactCheckResult] = []
    verified = 0
    unverified = 0
    inaccurate = 0

    for claim in claims:
        # Run each claim through all verification checks
        price_result = check_price_accuracy(claim, offer_data)
        product_result = verify_product_details(claim, offer_data)
        flag_result = flag_unverifiable_claims(claim, offer_data)

        # Use the most severe result
        worst = _most_severe(price_result, product_result, flag_result)
        results.append(worst)

        if worst.status == ClaimStatus.VERIFIED:
            verified += 1
        elif worst.status == ClaimStatus.INACCURATE:
            inaccurate += 1
        else:
            unverified += 1

    has_errors = any(r.severity == ClaimSeverity.ERROR for r in results)
    passed = not has_errors

    report = FactCheckReport(
        article_title=article_title,
        total_claims=len(claims),
        verified_count=verified,
        unverified_count=unverified,
        inaccurate_count=inaccurate,
        results=results,
        passed=passed,
    )

    log_event(
        logger,
        "fact_check.complete",
        title=article_title,
        total_claims=len(claims),
        verified=verified,
        unverified=unverified,
        inaccurate=inaccurate,
        passed=passed,
    )

    if block_on_failure and not passed:
        error_claims = [r for r in results if r.severity == ClaimSeverity.ERROR]
        raise ContentValidationError(
            f"Fact-check failed for '{article_title}': "
            f"{len(error_claims)} critical issue(s) found",
            details={
                "article_title": article_title,
                "errors": [
                    {"claim": r.claim_text, "details": r.details, "suggestion": r.suggestion}
                    for r in error_claims
                ],
            },
        )

    return report


def _most_severe(
    *results: FactCheckResult,
) -> FactCheckResult:
    """Return the result with the highest severity from a set of checks.

    Parameters
    ----------
    *results:
        Variable number of :class:`FactCheckResult` instances.

    Returns
    -------
    FactCheckResult
        The result with the worst severity.
    """
    severity_order = {
        ClaimSeverity.ERROR: 3,
        ClaimSeverity.WARNING: 2,
        ClaimSeverity.INFO: 1,
    }
    return max(results, key=lambda r: severity_order.get(r.severity, 0))
