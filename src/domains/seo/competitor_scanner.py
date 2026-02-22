"""
domains.seo.competitor_scanner
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

OpenClaw Competitor Weakness Scanner.

Automatically detects weak competitor pages that can be outranked quickly
by analysing SERP results for exploitable weaknesses across five
dimensions: thin content, outdated content, poor internal linking, weak
domain authority, and bad UX structure.

Implements the strategy from
``docs/seo/COMPETITOR_WEAKNESS_SCANNER.md``.

The scanner:
    1. Accepts SERP result data for a target keyword
    2. Evaluates each ranking page across 5 weakness dimensions
    3. Computes a per-page weakness score
    4. Aggregates into a SERP-level weakness total
    5. Recommends cluster-based attack strategy for vulnerable SERPs

Design references:
    - docs/seo/COMPETITOR_WEAKNESS_SCANNER.md
    - src/domains/seo/serp.py  (SERPResult, SERPAnalysis)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, unique
from typing import Any, Dict, List, Optional, Sequence

from src.core.logger import get_logger, log_event

logger = get_logger("domains.seo.competitor_scanner")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

@unique
class WeaknessType(str, Enum):
    """The 5 weakness dimensions from the spec."""

    THIN_CONTENT = "thin_content"
    OUTDATED = "outdated"
    POOR_LINKING = "poor_linking"
    WEAK_DOMAIN = "weak_domain"
    BAD_UX = "bad_ux"


@unique
class AttackPriority(str, Enum):
    """How urgently a SERP should be targeted."""

    IMMEDIATE = "immediate"     # weakness_total >= 70
    HIGH = "high"               # weakness_total >= 50
    MODERATE = "moderate"       # weakness_total >= 30
    LOW = "low"                 # weakness_total < 30


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

THIN_CONTENT_WORD_THRESHOLD = 1000
THIN_CONTENT_HEADING_THRESHOLD = 3
OUTDATED_YEAR_THRESHOLD = 1       # years behind current
WEAK_DOMAIN_DA_THRESHOLD = 30
ATTACKABLE_WEAKNESS_THRESHOLD = 50

CURRENT_YEAR = datetime.now(timezone.utc).year


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CompetitorPage:
    """A single competitor page extracted from SERP analysis.

    Attributes
    ----------
    url:
        Page URL.
    position:
        SERP position (1 = top).
    word_count:
        Estimated word count.
    heading_count:
        Number of headings (H2-H4) detected.
    last_updated_year:
        Year the content was last updated (0 if unknown).
    internal_link_count:
        Number of internal links detected on the page.
    domain_authority:
        Domain authority score (0-100).
    has_comparison_table:
        Whether the page has a structured comparison table.
    has_faq_section:
        Whether the page has a FAQ section.
    has_excessive_ads:
        Whether the page has excessive ad placements.
    page_load_score:
        Page speed score (0-100, higher = faster).
    metadata:
        Additional data from the analysis source.
    """

    url: str
    position: int = 0
    word_count: int = 0
    heading_count: int = 0
    last_updated_year: int = 0
    internal_link_count: int = 0
    domain_authority: int = 0
    has_comparison_table: bool = True
    has_faq_section: bool = True
    has_excessive_ads: bool = False
    page_load_score: int = 80
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WeaknessSignal:
    """A detected weakness in a competitor page.

    Attributes
    ----------
    weakness_type:
        Which dimension this weakness falls under.
    score:
        Weakness score for this dimension (0-20, higher = weaker).
    description:
        Human-readable explanation of the weakness.
    """

    weakness_type: WeaknessType
    score: float = 0.0
    description: str = ""


@dataclass
class PageWeaknessReport:
    """Full weakness analysis for a single competitor page.

    Attributes
    ----------
    page:
        The competitor page analysed.
    weaknesses:
        All detected weakness signals.
    total_score:
        Sum of all weakness scores (0-100).
    """

    page: CompetitorPage
    weaknesses: List[WeaknessSignal] = field(default_factory=list)
    total_score: float = 0.0

    @property
    def primary_weakness(self) -> Optional[WeaknessType]:
        """Return the highest-scoring weakness type."""
        if not self.weaknesses:
            return None
        return max(self.weaknesses, key=lambda w: w.score).weakness_type


@dataclass
class SERPWeaknessReport:
    """Aggregated weakness analysis for an entire SERP.

    Attributes
    ----------
    keyword:
        The target keyword.
    page_reports:
        Per-page weakness reports for all analysed competitors.
    weakness_total:
        Average weakness score across all pages (0-100).
    is_attackable:
        Whether the SERP meets the weakness threshold.
    attack_priority:
        Recommended urgency for targeting this SERP.
    attack_strategy:
        Recommended content cluster to deploy.
    """

    keyword: str = ""
    page_reports: List[PageWeaknessReport] = field(default_factory=list)
    weakness_total: float = 0.0
    is_attackable: bool = False
    attack_priority: AttackPriority = AttackPriority.LOW
    attack_strategy: List[str] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.page_reports)

    @property
    def weakest_page(self) -> Optional[PageWeaknessReport]:
        """Return the page with the highest weakness score."""
        if not self.page_reports:
            return None
        return max(self.page_reports, key=lambda r: r.total_score)


# ---------------------------------------------------------------------------
# Individual weakness detectors
# ---------------------------------------------------------------------------

def detect_thin_content(page: CompetitorPage) -> WeaknessSignal:
    """Detect thin content weakness.

    From the spec — thin pages (<1000 words, few headings, minimal
    structure) are easiest to beat.

    Score: 0-20 based on how thin the content is.
    """
    score = 0.0
    reasons = []

    if page.word_count < THIN_CONTENT_WORD_THRESHOLD:
        # Scale: 0 words = 12pts, 999 words = ~0pts
        score += max(12 * (1 - page.word_count / THIN_CONTENT_WORD_THRESHOLD), 0)
        reasons.append(f"{page.word_count} words (under {THIN_CONTENT_WORD_THRESHOLD})")

    if page.heading_count < THIN_CONTENT_HEADING_THRESHOLD:
        score += max(8 * (1 - page.heading_count / THIN_CONTENT_HEADING_THRESHOLD), 0)
        reasons.append(f"only {page.heading_count} headings")

    description = f"Thin content: {', '.join(reasons)}" if reasons else ""
    return WeaknessSignal(
        weakness_type=WeaknessType.THIN_CONTENT,
        score=round(min(score, 20), 1),
        description=description,
    )


def detect_outdated(page: CompetitorPage) -> WeaknessSignal:
    """Detect outdated content weakness.

    From the spec — year older than current, old product models,
    broken links, missing newer alternatives.

    Score: 0-20 based on how outdated.
    """
    score = 0.0
    reasons = []

    if page.last_updated_year > 0:
        years_behind = CURRENT_YEAR - page.last_updated_year
        if years_behind >= OUTDATED_YEAR_THRESHOLD:
            score += min(years_behind * 5, 20)
            reasons.append(f"last updated {page.last_updated_year} ({years_behind}y behind)")
    else:
        # Unknown update date is mildly suspicious
        score += 5
        reasons.append("no visible update date")

    description = f"Outdated: {', '.join(reasons)}" if reasons else ""
    return WeaknessSignal(
        weakness_type=WeaknessType.OUTDATED,
        score=round(min(score, 20), 1),
        description=description,
    )


def detect_poor_linking(page: CompetitorPage) -> WeaknessSignal:
    """Detect poor internal linking weakness.

    From the spec — article rarely linked internally, no visible
    site cluster support, orphan-like page.

    Score: 0-20 based on linking weakness.
    """
    score = 0.0
    reasons = []

    if page.internal_link_count == 0:
        score += 20
        reasons.append("no internal links (orphan page)")
    elif page.internal_link_count < 3:
        score += 14
        reasons.append(f"only {page.internal_link_count} internal links")
    elif page.internal_link_count < 5:
        score += 8
        reasons.append(f"only {page.internal_link_count} internal links (weak cluster)")

    description = f"Poor linking: {', '.join(reasons)}" if reasons else ""
    return WeaknessSignal(
        weakness_type=WeaknessType.POOR_LINKING,
        score=round(min(score, 20), 1),
        description=description,
    )


def detect_weak_domain(page: CompetitorPage) -> WeaknessSignal:
    """Detect weak domain authority.

    From the spec — small niche blogs, hobbyist sites, minimal
    backlinks, low editorial depth.

    Score: 0-20 based on domain weakness.
    """
    score = 0.0
    reasons = []

    if page.domain_authority < WEAK_DOMAIN_DA_THRESHOLD:
        # DA 0 = 20pts, DA 29 = ~1pt
        score += max(20 * (1 - page.domain_authority / WEAK_DOMAIN_DA_THRESHOLD), 0)
        reasons.append(f"DA {page.domain_authority} (under {WEAK_DOMAIN_DA_THRESHOLD})")

    description = f"Weak domain: {', '.join(reasons)}" if reasons else ""
    return WeaknessSignal(
        weakness_type=WeaknessType.WEAK_DOMAIN,
        score=round(min(score, 20), 1),
        description=description,
    )


def detect_bad_ux(page: CompetitorPage) -> WeaknessSignal:
    """Detect bad UX structure.

    From the spec — no comparison table, no FAQ, cluttered layout,
    excessive ads, slow page load.

    Score: 0-20 based on UX problems.
    """
    score = 0.0
    reasons = []

    if not page.has_comparison_table:
        score += 5
        reasons.append("no comparison table")

    if not page.has_faq_section:
        score += 5
        reasons.append("no FAQ section")

    if page.has_excessive_ads:
        score += 5
        reasons.append("excessive ads")

    if page.page_load_score < 50:
        score += 5
        reasons.append(f"slow load (score {page.page_load_score})")

    description = f"Bad UX: {', '.join(reasons)}" if reasons else ""
    return WeaknessSignal(
        weakness_type=WeaknessType.BAD_UX,
        score=round(min(score, 20), 1),
        description=description,
    )


# ---------------------------------------------------------------------------
# Page-level analysis
# ---------------------------------------------------------------------------

def score_competitor_page(page: CompetitorPage) -> PageWeaknessReport:
    """Analyse a single competitor page across all 5 weakness dimensions.

    Parameters
    ----------
    page:
        The competitor page to analyse.

    Returns
    -------
    PageWeaknessReport
        Full weakness report with per-dimension scores.
    """
    detectors = [
        detect_thin_content,
        detect_outdated,
        detect_poor_linking,
        detect_weak_domain,
        detect_bad_ux,
    ]

    weaknesses = []
    for detector in detectors:
        signal = detector(page)
        if signal.score > 0:
            weaknesses.append(signal)

    total = sum(w.score for w in weaknesses)

    return PageWeaknessReport(
        page=page,
        weaknesses=weaknesses,
        total_score=round(min(total, 100), 1),
    )


# ---------------------------------------------------------------------------
# Attack strategy generation
# ---------------------------------------------------------------------------

_ATTACK_CLUSTER_TEMPLATES: list[str] = [
    "Best {keyword} — Complete Buying Guide",
    "{keyword} Comparison — Top Models Reviewed",
    "{keyword} for Beginners — What You Need to Know",
    "{keyword} FAQ — Your Questions Answered",
    "Common {keyword} Problems and Solutions",
]


def generate_attack_strategy(keyword: str) -> List[str]:
    """Generate the cluster attack strategy for a vulnerable SERP.

    From the spec — when a weak SERP is found, build a full cluster
    (not a single page), interlink immediately, and publish support
    pages within the same week.

    Parameters
    ----------
    keyword:
        The target keyword.

    Returns
    -------
    list[str]
        5 article titles forming the attack cluster.
    """
    return [t.format(keyword=keyword) for t in _ATTACK_CLUSTER_TEMPLATES]


def classify_attack_priority(weakness_total: float) -> AttackPriority:
    """Classify the urgency of attacking a SERP based on weakness score."""
    if weakness_total >= 70:
        return AttackPriority.IMMEDIATE
    if weakness_total >= 50:
        return AttackPriority.HIGH
    if weakness_total >= 30:
        return AttackPriority.MODERATE
    return AttackPriority.LOW


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def scan_serp_weaknesses(
    keyword: str,
    competitors: Sequence[CompetitorPage],
    *,
    threshold: float = ATTACKABLE_WEAKNESS_THRESHOLD,
) -> SERPWeaknessReport:
    """Run the full Competitor Weakness Scanner pipeline for a keyword.

    1. Score each competitor page across 5 weakness dimensions
    2. Compute SERP-level weakness total (average of page scores)
    3. Determine if the SERP is attackable
    4. Generate cluster attack strategy if attackable

    Parameters
    ----------
    keyword:
        The target keyword.
    competitors:
        Competitor pages from the SERP (typically top 10).
    threshold:
        Minimum weakness total to flag as attackable.

    Returns
    -------
    SERPWeaknessReport
        Full SERP weakness analysis with attack recommendations.
    """
    page_reports = [score_competitor_page(page) for page in competitors]

    if page_reports:
        weakness_total = sum(r.total_score for r in page_reports) / len(page_reports)
    else:
        weakness_total = 0.0

    weakness_total = round(weakness_total, 1)
    is_attackable = weakness_total >= threshold
    priority = classify_attack_priority(weakness_total)
    strategy = generate_attack_strategy(keyword) if is_attackable else []

    report = SERPWeaknessReport(
        keyword=keyword,
        page_reports=page_reports,
        weakness_total=weakness_total,
        is_attackable=is_attackable,
        attack_priority=priority,
        attack_strategy=strategy,
    )

    log_event(
        logger,
        "competitor_scanner.serp.scanned",
        keyword=keyword,
        pages=len(page_reports),
        weakness_total=weakness_total,
        is_attackable=is_attackable,
        priority=priority.value,
    )

    return report


def scan_multiple_serps(
    serp_data: Dict[str, Sequence[CompetitorPage]],
    *,
    threshold: float = ATTACKABLE_WEAKNESS_THRESHOLD,
) -> List[SERPWeaknessReport]:
    """Scan multiple SERPs and return only attackable ones, sorted by weakness.

    Parameters
    ----------
    serp_data:
        Mapping of keyword -> list of competitor pages.
    threshold:
        Minimum weakness total to include in results.

    Returns
    -------
    list[SERPWeaknessReport]
        Attackable SERPs sorted by weakness total (highest first).
    """
    reports = []
    for keyword, competitors in serp_data.items():
        report = scan_serp_weaknesses(keyword, competitors, threshold=threshold)
        if report.is_attackable:
            reports.append(report)

    reports.sort(key=lambda r: r.weakness_total, reverse=True)

    log_event(
        logger,
        "competitor_scanner.batch.complete",
        serps_scanned=len(serp_data),
        serps_attackable=len(reports),
    )

    return reports
