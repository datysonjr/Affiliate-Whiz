"""
pipelines.optimization.prune
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Identify and prune underperforming affiliate content.  Content that
fails to generate meaningful traffic or revenue after a minimum age
threshold is moved to draft status (not deleted) to preserve the option
of refreshing it later.

Pruning thresholds and actions are configured in ``config/pipelines.yaml``
under ``optimization.steps[1]``.

Design references:
    - config/pipelines.yaml  ``optimization.steps[1]``  (min_age_days, min_clicks, action)
    - ARCHITECTURE.md  Section 3 (Optimization Pipeline)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.core.constants import ContentStatus
from src.core.errors import PipelineStepError
from src.core.logger import get_logger, log_event
from src.pipelines.optimization.measure import ContentMetrics

logger = get_logger("pipelines.optimization.prune")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PruneCandidate:
    """A content piece identified as a candidate for pruning.

    Attributes
    ----------
    post_id:
        Identifier of the underperforming post.
    title:
        Post title.
    url:
        Post URL.
    reason:
        Why this post was flagged for pruning.
    metrics:
        Performance metrics that triggered the flag.
    age_days:
        Number of days since publication.
    recommended_action:
        Suggested action: ``"draft"``, ``"noindex"``, ``"redirect"``,
        ``"refresh"``.
    """

    post_id: str
    title: str = ""
    url: str = ""
    reason: str = ""
    metrics: Optional[ContentMetrics] = None
    age_days: int = 0
    recommended_action: str = "draft"


@dataclass
class PruneResult:
    """Result of executing pruning actions on content.

    Attributes
    ----------
    action:
        The action that was applied.
    total:
        Number of posts targeted.
    succeeded:
        Number of posts successfully pruned.
    failed:
        Number of posts where pruning failed.
    details:
        Per-post outcome details.
    executed_at:
        UTC timestamp of execution.
    """

    action: str = "draft"
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    details: List[Dict[str, Any]] = field(default_factory=list)
    executed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Identification
# ---------------------------------------------------------------------------

def identify_prune_candidates(
    content_metrics: List[ContentMetrics],
    *,
    min_age_days: int = 60,
    min_clicks: int = 5,
    min_pageviews: int = 10,
    min_revenue: float = 0.0,
    action: str = "draft",
) -> List[PruneCandidate]:
    """Identify content that should be considered for pruning.

    Applies threshold checks to each content piece's metrics.  Content
    must be older than *min_age_days* and fail at least one performance
    threshold to be flagged.

    Parameters
    ----------
    content_metrics:
        List of :class:`ContentMetrics` for all published content.
    min_age_days:
        Minimum age in days before content is eligible for pruning.
        This prevents pruning of newly published content that has not
        had time to index and rank.
    min_clicks:
        Minimum affiliate link clicks in the measurement period.
    min_pageviews:
        Minimum pageviews in the measurement period.
    min_revenue:
        Minimum revenue generated in the measurement period.
    action:
        Default recommended action for flagged content.

    Returns
    -------
    list[PruneCandidate]
        Candidates sorted by severity (worst performers first).
    """
    log_event(
        logger,
        "prune.identify.start",
        total_content=len(content_metrics),
        min_age_days=min_age_days,
        min_clicks=min_clicks,
    )

    candidates: List[PruneCandidate] = []

    for metrics in content_metrics:
        # Calculate age (approximate from measurement period)
        age_days = metrics.period_days  # In production, compute from publish date

        # Skip content that is too young
        if age_days < min_age_days:
            continue

        reasons: List[str] = []

        if metrics.pageviews < min_pageviews:
            reasons.append(
                f"Low traffic: {metrics.pageviews} pageviews "
                f"(threshold: {min_pageviews})"
            )

        if metrics.clicks < min_clicks:
            reasons.append(
                f"Low engagement: {metrics.clicks} clicks "
                f"(threshold: {min_clicks})"
            )

        if min_revenue > 0 and metrics.revenue < min_revenue:
            reasons.append(
                f"Low revenue: ${metrics.revenue:.2f} "
                f"(threshold: ${min_revenue:.2f})"
            )

        if not reasons:
            continue

        # Determine recommended action based on severity
        recommended = _determine_prune_action(metrics, action)

        candidate = PruneCandidate(
            post_id=metrics.post_id,
            title=metrics.title,
            url=metrics.url,
            reason="; ".join(reasons),
            metrics=metrics,
            age_days=age_days,
            recommended_action=recommended,
        )
        candidates.append(candidate)

    # Sort by revenue (ascending) -- worst performers first
    candidates.sort(key=lambda c: (c.metrics.revenue if c.metrics else 0, c.metrics.pageviews if c.metrics else 0))

    log_event(
        logger,
        "prune.identify.ok",
        candidates_found=len(candidates),
        total_evaluated=len(content_metrics),
    )
    return candidates


def _determine_prune_action(
    metrics: ContentMetrics,
    default_action: str,
) -> str:
    """Determine the best pruning action based on metric severity.

    Parameters
    ----------
    metrics:
        The content's performance metrics.
    default_action:
        The default action from config.

    Returns
    -------
    str
        Recommended action: ``"draft"``, ``"noindex"``, ``"redirect"``,
        or ``"refresh"``.
    """
    # If the content has some traffic but no conversions, it might
    # benefit from a refresh rather than removal
    if metrics.pageviews > 50 and metrics.clicks == 0:
        return "refresh"

    # If there is some organic traffic, preserve the URL via noindex
    # to avoid losing any link equity
    if metrics.organic_traffic_pct > 0.3 and metrics.pageviews > 20:
        return "noindex"

    # For content with zero traffic, move to draft status
    if metrics.pageviews == 0:
        return "draft"

    return default_action


# ---------------------------------------------------------------------------
# Pruning execution
# ---------------------------------------------------------------------------

def prune_content(
    candidates: List[PruneCandidate],
    *,
    action_override: Optional[str] = None,
    dry_run: bool = False,
) -> PruneResult:
    """Execute pruning actions on the identified candidates.

    For each candidate, applies the recommended action (or the
    *action_override*).  Archives content before any destructive
    operation.

    Parameters
    ----------
    candidates:
        List of :class:`PruneCandidate` objects to process.
    action_override:
        If provided, overrides each candidate's recommended action.
    dry_run:
        If ``True``, log what would be done without executing.

    Returns
    -------
    PruneResult
        Summary of pruning operations.
    """
    log_event(
        logger,
        "prune.execute.start",
        candidates=len(candidates),
        dry_run=dry_run,
    )

    result = PruneResult(
        action=action_override or "mixed",
        total=len(candidates),
    )

    for candidate in candidates:
        action = action_override or candidate.recommended_action
        post_id = candidate.post_id

        if dry_run:
            result.details.append({
                "post_id": post_id,
                "title": candidate.title,
                "action": action,
                "success": True,
                "dry_run": True,
                "reason": candidate.reason,
            })
            result.succeeded += 1
            log_event(
                logger,
                "prune.dry_run",
                post_id=post_id,
                action=action,
                reason=candidate.reason,
            )
            continue

        try:
            # Archive before pruning
            archive_content([post_id])

            # Execute the action
            _execute_prune_action(post_id, action)

            result.details.append({
                "post_id": post_id,
                "title": candidate.title,
                "action": action,
                "success": True,
                "reason": candidate.reason,
            })
            result.succeeded += 1

        except Exception as exc:
            result.details.append({
                "post_id": post_id,
                "title": candidate.title,
                "action": action,
                "success": False,
                "error": str(exc),
                "reason": candidate.reason,
            })
            result.failed += 1
            logger.error("Failed to prune %s: %s", post_id, exc)

    log_event(
        logger,
        "prune.execute.ok",
        total=result.total,
        succeeded=result.succeeded,
        failed=result.failed,
    )
    return result


def _execute_prune_action(post_id: str, action: str) -> None:
    """Execute a single pruning action on a post.

    Stub for CMS integration.  In production, this calls the appropriate
    CMS API to change post status, add noindex, or create a redirect.

    Parameters
    ----------
    post_id:
        The post to modify.
    action:
        The action to take: ``"draft"``, ``"noindex"``, ``"redirect"``,
        ``"refresh"``.
    """
    action_handlers = {
        "draft": lambda pid: logger.info("Moving post %s to draft status", pid),
        "noindex": lambda pid: logger.info("Adding noindex to post %s", pid),
        "redirect": lambda pid: logger.info("Setting up redirect for post %s", pid),
        "refresh": lambda pid: logger.info("Queuing post %s for content refresh", pid),
    }

    handler = action_handlers.get(action)
    if handler is None:
        raise PipelineStepError(
            f"Unknown prune action: {action!r}",
            step_name="prune",
            details={"post_id": post_id, "action": action},
        )

    handler(post_id)


# ---------------------------------------------------------------------------
# Archival
# ---------------------------------------------------------------------------

def archive_content(
    post_ids: List[str],
    *,
    archive_store: Optional[Any] = None,
) -> Dict[str, bool]:
    """Archive content before pruning for potential future recovery.

    Saves a full snapshot of each post's content and metadata to
    long-term storage.  This ensures content can be restored if a
    pruning decision is later reversed.

    Parameters
    ----------
    post_ids:
        List of post identifiers to archive.
    archive_store:
        Optional storage backend.  If ``None``, archival is logged but
        no persistent storage occurs (stub mode).

    Returns
    -------
    dict[str, bool]
        Mapping of post_id to success status.
    """
    results: Dict[str, bool] = {}

    for post_id in post_ids:
        try:
            # Stub: in production, this fetches content from CMS and saves
            # to S3, GCS, or local archive storage
            logger.info("Archiving content for post %s", post_id)
            results[post_id] = True
        except Exception as exc:
            logger.error("Failed to archive post %s: %s", post_id, exc)
            results[post_id] = False

    log_event(
        logger,
        "prune.archive.ok",
        total=len(post_ids),
        archived=sum(1 for v in results.values() if v),
    )
    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def generate_prune_report(
    result: PruneResult,
    candidates: Optional[List[PruneCandidate]] = None,
) -> str:
    """Generate a human-readable report from pruning results.

    Produces a Markdown-formatted report suitable for logging, email
    notifications, or dashboard display.

    Parameters
    ----------
    result:
        The :class:`PruneResult` from the pruning operation.
    candidates:
        Optional original candidate list for additional context.

    Returns
    -------
    str
        Markdown-formatted report string.
    """
    lines = [
        f"# Content Pruning Report",
        "",
        f"**Date**: {result.executed_at.strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Action**: {result.action}",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total targeted | {result.total} |",
        f"| Succeeded | {result.succeeded} |",
        f"| Failed | {result.failed} |",
        f"| Success rate | {(result.succeeded / result.total * 100) if result.total > 0 else 0:.1f}% |",
        "",
    ]

    if result.details:
        lines.extend([
            "## Details",
            "",
            "| Post ID | Title | Action | Status | Reason |",
            "|---------|-------|--------|--------|--------|",
        ])
        for detail in result.details:
            status = "OK" if detail.get("success") else f"FAILED: {detail.get('error', 'unknown')}"
            dry = " (dry run)" if detail.get("dry_run") else ""
            lines.append(
                f"| {detail.get('post_id', '')} "
                f"| {detail.get('title', '')[:30]} "
                f"| {detail.get('action', '')} "
                f"| {status}{dry} "
                f"| {detail.get('reason', '')[:50]} |"
            )

    lines.extend([
        "",
        "## Follow-up Actions",
        "",
        "- Update sitemap to remove pruned URLs",
        "- Verify redirect rules are functioning correctly",
        "- Update internal links pointing to pruned pages",
        "- Monitor 404 errors for the next 7 days",
        "- Review pruned content in 30 days for potential restoration",
    ])

    report = "\n".join(lines)
    log_event(logger, "prune.report.generated", length=len(report))
    return report
