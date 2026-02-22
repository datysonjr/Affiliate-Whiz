"""
pipelines.optimization.prune
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Identify and remove or demote underperforming content.  Pruning improves
overall site quality, concentrates link equity, and frees resources for
scaling winning content.

Pruning thresholds are configured via ``config/pipelines.yaml`` under
``optimization.steps[1]`` (min_age_days, min_clicks, action).

Design references:
    - config/pipelines.yaml  ``optimization.steps[1]``
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
    """A content piece flagged for potential pruning.

    Attributes
    ----------
    post_id:
        Internal identifier of the post.
    title:
        Article title.
    url:
        Live URL of the post.
    reason:
        Why this post was flagged (e.g. "below_min_clicks",
        "low_revenue", "thin_content").
    metrics:
        The :class:`ContentMetrics` that triggered the flag.
    recommended_action:
        Suggested action: ``"draft"`` (unpublish), ``"noindex"``,
        ``"redirect"``, ``"merge"``, ``"refresh"``, or ``"delete"``.
    severity:
        How underperforming the content is: ``"low"``, ``"medium"``,
        ``"high"``.
    """

    post_id: str
    title: str = ""
    url: str = ""
    reason: str = ""
    metrics: Optional[ContentMetrics] = None
    recommended_action: str = "draft"
    severity: str = "low"


@dataclass
class PruneResult:
    """Result of a pruning operation on a single post.

    Attributes
    ----------
    post_id:
        Identifier of the pruned post.
    action_taken:
        What was done (e.g. ``"moved_to_draft"``).
    success:
        Whether the action succeeded.
    error:
        Error message if the action failed.
    archived:
        Whether the content was archived before pruning.
    """

    post_id: str
    action_taken: str = ""
    success: bool = False
    error: str = ""
    archived: bool = False


@dataclass
class PruneReport:
    """Aggregate report from a pruning run.

    Attributes
    ----------
    total_candidates:
        Number of posts identified for pruning.
    pruned_count:
        Number of posts actually pruned.
    skipped_count:
        Number of candidates that were skipped.
    failed_count:
        Number of candidates where pruning failed.
    results:
        Per-post :class:`PruneResult` entries.
    action:
        The pruning action that was applied.
    report_text:
        Human-readable Markdown summary.
    generated_at:
        UTC timestamp.
    """

    total_candidates: int = 0
    pruned_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    results: List[PruneResult] = field(default_factory=list)
    action: str = "draft"
    report_text: str = ""
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Candidate identification
# ---------------------------------------------------------------------------

def identify_prune_candidates(
    content_metrics: List[ContentMetrics],
    *,
    min_age_days: int = 60,
    min_clicks: int = 5,
    min_pageviews: int = 10,
    min_revenue: float = 0.0,
    max_bounce_rate: float = 0.95,
) -> List[PruneCandidate]:
    """Identify content that should be considered for pruning.

    Evaluates each content piece against performance thresholds.  Only
    content older than *min_age_days* is considered (new content needs
    time to rank).

    Parameters
    ----------
    content_metrics:
        List of :class:`ContentMetrics` for all published content.
    min_age_days:
        Minimum days since publication before content is eligible for
        pruning.
    min_clicks:
        Posts with fewer clicks than this are flagged.
    min_pageviews:
        Posts with fewer pageviews than this are flagged.
    min_revenue:
        Posts generating less revenue than this are flagged.
    max_bounce_rate:
        Posts with a bounce rate above this are flagged.

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
    )

    candidates: List[PruneCandidate] = []

    for metrics in content_metrics:
        # Skip content that is too new
        if metrics.age_days < min_age_days:
            continue

        reasons: List[str] = []
        severity_score = 0

        # Check clicks
        if metrics.clicks < min_clicks:
            reasons.append(f"below_min_clicks ({metrics.clicks} < {min_clicks})")
            severity_score += 2

        # Check pageviews
        if metrics.pageviews < min_pageviews:
            reasons.append(f"below_min_pageviews ({metrics.pageviews} < {min_pageviews})")
            severity_score += 2

        # Check revenue
        if metrics.revenue < min_revenue:
            reasons.append(f"below_min_revenue (${metrics.revenue:.2f} < ${min_revenue:.2f})")
            severity_score += 1

        # Check bounce rate
        if metrics.bounce_rate > max_bounce_rate:
            reasons.append(f"high_bounce_rate ({metrics.bounce_rate:.2%} > {max_bounce_rate:.2%})")
            severity_score += 1

        # Check negative ROI
        if metrics.roi < 0 and metrics.roi != -1.0:
            reasons.append(f"negative_roi ({metrics.roi:.2f})")
            severity_score += 2

        if not reasons:
            continue

        # Determine severity
        if severity_score >= 5:
            severity = "high"
        elif severity_score >= 3:
            severity = "medium"
        else:
            severity = "low"

        # Determine recommended action based on severity
        if severity == "high":
            recommended_action = "draft"
        elif severity == "medium" and metrics.pageviews > 0:
            recommended_action = "refresh"
        else:
            recommended_action = "noindex"

        candidates.append(
            PruneCandidate(
                post_id=metrics.post_id,
                title=metrics.title,
                url=metrics.url,
                reason="; ".join(reasons),
                metrics=metrics,
                recommended_action=recommended_action,
                severity=severity,
            )
        )

    # Sort by severity (high first), then by lowest pageviews
    severity_order = {"high": 0, "medium": 1, "low": 2}
    candidates.sort(
        key=lambda c: (severity_order.get(c.severity, 3), c.metrics.pageviews if c.metrics else 0)
    )

    log_event(
        logger,
        "prune.identify.ok",
        candidates_found=len(candidates),
        high=sum(1 for c in candidates if c.severity == "high"),
        medium=sum(1 for c in candidates if c.severity == "medium"),
        low=sum(1 for c in candidates if c.severity == "low"),
    )
    return candidates


# ---------------------------------------------------------------------------
# Pruning execution
# ---------------------------------------------------------------------------

def prune_content(
    candidates: List[PruneCandidate],
    *,
    action: str = "draft",
    dry_run: bool = False,
) -> List[PruneResult]:
    """Execute pruning on the identified candidates.

    Applies the specified action to each candidate.  In ``dry_run``
    mode, no changes are made but the planned actions are logged.

    Parameters
    ----------
    candidates:
        List of :class:`PruneCandidate` to prune.
    action:
        The pruning action to apply: ``"draft"`` (move to draft status),
        ``"noindex"``, ``"redirect"``, ``"delete"``.
    dry_run:
        If ``True``, log planned actions without executing them.

    Returns
    -------
    list[PruneResult]
        Per-candidate results.
    """
    log_event(
        logger,
        "prune.execute.start",
        candidates=len(candidates),
        action=action,
        dry_run=dry_run,
    )

    valid_actions = {"draft", "noindex", "redirect", "delete", "merge", "refresh"}
    if action not in valid_actions:
        raise PipelineStepError(
            f"Invalid prune action: {action!r}. Must be one of {valid_actions}",
            step_name="prune",
        )

    results: List[PruneResult] = []

    for candidate in candidates:
        if dry_run:
            results.append(
                PruneResult(
                    post_id=candidate.post_id,
                    action_taken=f"dry_run:{action}",
                    success=True,
                    archived=False,
                )
            )
            logger.info(
                "[DRY RUN] Would %s post '%s' (%s) -- reason: %s",
                action,
                candidate.title,
                candidate.post_id,
                candidate.reason,
            )
            continue

        # Archive before pruning
        archived = archive_content(candidate.post_id, candidate.title, candidate.url)

        # Apply the action
        try:
            _apply_prune_action(candidate.post_id, action)
            results.append(
                PruneResult(
                    post_id=candidate.post_id,
                    action_taken=action,
                    success=True,
                    archived=archived,
                )
            )
            log_event(
                logger,
                "prune.post.ok",
                post_id=candidate.post_id,
                action=action,
            )
        except Exception as exc:
            results.append(
                PruneResult(
                    post_id=candidate.post_id,
                    action_taken=action,
                    success=False,
                    error=str(exc),
                    archived=archived,
                )
            )
            logger.error(
                "Failed to %s post '%s': %s",
                action,
                candidate.post_id,
                exc,
            )

    log_event(
        logger,
        "prune.execute.ok",
        total=len(results),
        succeeded=sum(1 for r in results if r.success),
        failed=sum(1 for r in results if not r.success),
    )
    return results


def _apply_prune_action(post_id: str, action: str) -> None:
    """Apply a specific prune action to a post.

    Stub for CMS integration.  In production, this calls the
    appropriate CMS API to update or remove the post.

    Parameters
    ----------
    post_id:
        The post to act on.
    action:
        The action to apply.
    """
    action_descriptions = {
        "draft": f"Moving post {post_id} to draft status",
        "noindex": f"Adding noindex to post {post_id}",
        "redirect": f"Setting up 301 redirect for post {post_id}",
        "delete": f"Deleting post {post_id}",
        "merge": f"Merging post {post_id} into target",
        "refresh": f"Queuing post {post_id} for content refresh",
    }
    logger.info(action_descriptions.get(action, f"Applying {action} to {post_id}"))


# ---------------------------------------------------------------------------
# Archival
# ---------------------------------------------------------------------------

def archive_content(
    post_id: str,
    title: str = "",
    url: str = "",
) -> bool:
    """Archive a post's content before pruning.

    Saves a snapshot of the post content, metadata, and affiliate links
    to storage so the content can be recovered if the pruning decision
    is later reversed.

    Parameters
    ----------
    post_id:
        The post identifier.
    title:
        Article title (for the archive record).
    url:
        Live URL (for the archive record).

    Returns
    -------
    bool
        ``True`` if archiving succeeded.
    """
    archive_record = {
        "post_id": post_id,
        "title": title,
        "url": url,
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "status": "archived",
    }

    # Stub: in production, this writes to a database or object storage
    logger.info("Archived post %s (%s) for recovery", post_id, title)
    log_event(logger, "prune.archive.ok", post_id=post_id)
    return True


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_prune_report(
    candidates: List[PruneCandidate],
    results: List[PruneResult],
    *,
    action: str = "draft",
) -> PruneReport:
    """Generate a comprehensive pruning report.

    Combines candidate analysis with execution results into a
    :class:`PruneReport` with a human-readable Markdown summary.

    Parameters
    ----------
    candidates:
        The prune candidates that were identified.
    results:
        The execution results from :func:`prune_content`.
    action:
        The pruning action that was applied.

    Returns
    -------
    PruneReport
        Complete report with statistics and Markdown text.
    """
    pruned = sum(1 for r in results if r.success)
    failed = sum(1 for r in results if not r.success)
    skipped = len(candidates) - len(results)

    # Build Markdown report
    lines = [
        f"# Content Pruning Report",
        f"",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"",
        f"## Summary",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Candidates identified | {len(candidates)} |",
        f"| Successfully pruned | {pruned} |",
        f"| Failed | {failed} |",
        f"| Skipped | {skipped} |",
        f"| Action applied | {action} |",
        f"",
        f"## Candidate Breakdown by Severity",
        f"",
        f"| Severity | Count |",
        f"|----------|-------|",
        f"| High | {sum(1 for c in candidates if c.severity == 'high')} |",
        f"| Medium | {sum(1 for c in candidates if c.severity == 'medium')} |",
        f"| Low | {sum(1 for c in candidates if c.severity == 'low')} |",
        f"",
    ]

    if candidates:
        lines.extend([
            f"## Details",
            f"",
            f"| Post | Reason | Severity | Action | Result |",
            f"|------|--------|----------|--------|--------|",
        ])
        results_by_id = {r.post_id: r for r in results}
        for candidate in candidates:
            result = results_by_id.get(candidate.post_id)
            status = "OK" if result and result.success else ("FAILED" if result else "SKIPPED")
            title_short = candidate.title[:40] + "..." if len(candidate.title) > 40 else candidate.title
            reason_short = candidate.reason[:50] + "..." if len(candidate.reason) > 50 else candidate.reason
            lines.append(
                f"| {title_short} | {reason_short} | {candidate.severity} | "
                f"{candidate.recommended_action} | {status} |"
            )

    lines.extend([
        f"",
        f"## Follow-up Actions",
        f"",
        f"- Update sitemap to remove pruned URLs",
        f"- Verify redirect rules are functioning correctly",
        f"- Update internal links pointing to pruned pages",
        f"- Monitor 404 errors over the next 7 days",
        f"- Review analytics for traffic impact after 14 days",
    ])

    report_text = "\n".join(lines)

    report = PruneReport(
        total_candidates=len(candidates),
        pruned_count=pruned,
        skipped_count=skipped,
        failed_count=failed,
        results=results,
        action=action,
        report_text=report_text,
    )

    log_event(
        logger,
        "prune.report.generated",
        candidates=len(candidates),
        pruned=pruned,
        failed=failed,
    )
    return report
