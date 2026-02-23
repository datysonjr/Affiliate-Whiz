"""
agents.publishing_agent
~~~~~~~~~~~~~~~~~~~~~~~

The PublishingAgent manages CMS publishing workflows.  It selects content
that has passed quality review, validates posting policies (cadence limits,
cooldown windows), formats articles for the target CMS, and publishes them.

Design references:
    - ARCHITECTURE.md  Section 2 (Agent Architecture)
    - config/agents.yaml    (publishing settings)
    - config/sites.yaml     (CMS connection details)
    - config/schedules.yaml (posting cadence rules)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.agents.base_agent import BaseAgent
from src.core.constants import (
    AgentName,
    ContentStatus,
    DEFAULT_COOLDOWN_MINUTES,
    DEFAULT_MAX_POSTS_PER_DAY,
    DEFAULT_POSTING_CADENCE_PER_DAY,
)
from src.core.logger import log_event

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class PublishCandidate:
    """A content piece that is eligible for publishing.

    Attributes:
        content_id:   Unique identifier of the content piece.
        title:        Article title.
        html_body:    The fully prepared HTML body.
        slug:         URL slug for the published page.
        niche:        Niche this content belongs to.
        target_site:  CMS / site identifier to publish to.
        status:       Current content lifecycle status.
        priority:     Scheduling priority (lower is more urgent).
    """

    content_id: str
    title: str
    html_body: str = ""
    slug: str = ""
    niche: str = ""
    target_site: str = "default"
    status: ContentStatus = ContentStatus.APPROVED
    priority: int = 100


@dataclass
class PublishResult:
    """Outcome of publishing a single piece of content.

    Attributes:
        content_id:    ID of the published content.
        published_url: Live URL (empty if publishing failed).
        cms_post_id:   Post ID returned by the CMS API.
        success:       Whether the publish was successful.
        error:         Error message if publishing failed.
        published_at:  UTC timestamp of publication.
    """

    content_id: str
    published_url: str = ""
    cms_post_id: str = ""
    success: bool = False
    error: str = ""
    published_at: Optional[datetime] = None


@dataclass
class PublishPlan:
    """Output of the planning phase -- content items to publish this cycle.

    Attributes:
        candidates:        Ordered list of candidates to publish.
        max_posts:         Maximum posts allowed this cycle.
        cooldown_minutes:  Minimum minutes between successive posts.
        plan_time:         When the plan was generated.
    """

    candidates: List[PublishCandidate] = field(default_factory=list)
    max_posts: int = DEFAULT_MAX_POSTS_PER_DAY
    cooldown_minutes: int = DEFAULT_COOLDOWN_MINUTES
    plan_time: Optional[datetime] = None


@dataclass
class PublishExecutionResult:
    """Aggregated results from the publishing cycle.

    Attributes:
        results:   Individual publish outcomes (keyed by content_id).
        skipped:   Content IDs that were skipped due to policy.
        errors:    General errors encountered during the cycle.
    """

    results: Dict[str, PublishResult] = field(default_factory=dict)
    skipped: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent implementation
# ---------------------------------------------------------------------------


class PublishingAgent(BaseAgent):
    """Manages the CMS publishing pipeline for approved content.

    The publishing agent runs on a schedule (typically several times per day)
    and picks up content that has been approved by the content generation
    agent's quality checks.  It enforces posting cadence limits to avoid
    flooding the site and formats content for the target CMS before pushing
    it live.

    Configuration keys (from ``config/agents.yaml`` under ``publishing``):
        enabled:              bool  -- whether this agent is active.
        max_posts_per_day:    int   -- hard cap on daily posts.
        cadence_per_day:      int   -- desired posts per day.
        cooldown_minutes:     int   -- minimum gap between successive posts.
        target_site:          str   -- default CMS site identifier.
        cms_api_base_url:     str   -- CMS REST API base URL.
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        super().__init__(name=str(AgentName.PUBLISHING), config=config)
        self._max_posts_per_day: int = config.get(
            "max_posts_per_day", DEFAULT_MAX_POSTS_PER_DAY
        )
        self._cadence_per_day: int = config.get(
            "cadence_per_day", DEFAULT_POSTING_CADENCE_PER_DAY
        )
        self._cooldown_minutes: int = config.get(
            "cooldown_minutes", DEFAULT_COOLDOWN_MINUTES
        )
        self._target_site: str = config.get("target_site", "default")
        self._cms_api_base_url: str = config.get(
            "cms_api_base_url", "http://localhost:8080/wp-json/wp/v2"
        )
        self._posts_today: int = 0
        self._last_publish_time: Optional[datetime] = None

    # ------------------------------------------------------------------
    # BaseAgent lifecycle
    # ------------------------------------------------------------------

    def plan(self) -> PublishPlan:
        """Select approved content that is ready for publishing.

        Queries the data store for content with status ``APPROVED``, orders
        by priority and creation time, and caps the batch to daily limits.

        Returns:
            A :class:`PublishPlan` with candidates for this cycle.
        """
        log_event(
            self.logger,
            "publishing.plan.start",
            posts_today=self._posts_today,
            max_per_day=self._max_posts_per_day,
        )

        remaining_budget = max(0, self._max_posts_per_day - self._posts_today)

        # In production, this queries the DB for APPROVED content.
        # Placeholder: return an empty candidate list until DB integration.
        candidates: List[PublishCandidate] = []

        plan = PublishPlan(
            candidates=candidates[:remaining_budget],
            max_posts=remaining_budget,
            cooldown_minutes=self._cooldown_minutes,
            plan_time=datetime.now(timezone.utc),
        )

        log_event(
            self.logger,
            "publishing.plan.complete",
            candidates=len(plan.candidates),
            remaining_budget=remaining_budget,
        )
        return plan

    def execute(self, plan: PublishPlan) -> PublishExecutionResult:
        """Run the publishing pipeline for each candidate.

        For each candidate the pipeline:
        1. Checks posting policy (cooldown, daily cap).
        2. Formats content for the target CMS.
        3. Pushes to the CMS API.
        4. Verifies the published URL.

        Parameters:
            plan: The :class:`PublishPlan` from planning.

        Returns:
            A :class:`PublishExecutionResult` with per-item outcomes.
        """
        result = PublishExecutionResult()

        for candidate in plan.candidates:
            log_event(
                self.logger,
                "publishing.pipeline.start",
                content_id=candidate.content_id,
                title=candidate.title,
            )

            # --- Policy check ---
            policy_ok, policy_reason = self._check_posting_policy(plan)
            if not policy_ok:
                result.skipped.append(candidate.content_id)
                self.logger.info(
                    "Skipping content %s due to policy: %s",
                    candidate.content_id,
                    policy_reason,
                )
                continue

            try:
                # --- Format for CMS ---
                cms_payload = self._format_for_cms(candidate)

                # --- Publish ---
                pub_result = self._push_to_cms(candidate, cms_payload)
                result.results[candidate.content_id] = pub_result

                if pub_result.success:
                    self._posts_today += 1
                    self._last_publish_time = datetime.now(timezone.utc)
                    log_event(
                        self.logger,
                        "publishing.pipeline.success",
                        content_id=candidate.content_id,
                        url=pub_result.published_url,
                    )
                else:
                    self.logger.warning(
                        "Publishing failed for content %s: %s",
                        candidate.content_id,
                        pub_result.error,
                    )

            except Exception as exc:
                pub_result = PublishResult(
                    content_id=candidate.content_id,
                    success=False,
                    error=str(exc),
                )
                result.results[candidate.content_id] = pub_result
                result.errors.append(f"Content {candidate.content_id}: {exc}")
                self.logger.error(
                    "Publishing pipeline failed for content %s: %s",
                    candidate.content_id,
                    exc,
                )

        return result

    def report(
        self, plan: PublishPlan, result: PublishExecutionResult
    ) -> Dict[str, Any]:
        """Log publish outcomes and return a structured summary.

        Parameters:
            plan:   The publish plan.
            result: The execution result.

        Returns:
            A summary dict for the orchestrator's audit log.
        """
        success_count = sum(1 for r in result.results.values() if r.success)
        failed_count = sum(1 for r in result.results.values() if not r.success)

        report_data: Dict[str, Any] = {
            "candidates_planned": len(plan.candidates),
            "published": success_count,
            "failed": failed_count,
            "skipped": len(result.skipped),
            "posts_today_total": self._posts_today,
            "published_urls": [
                r.published_url for r in result.results.values() if r.success
            ],
            "errors": result.errors,
        }

        self._log_metric("publishing.published", success_count)
        self._log_metric("publishing.failed", failed_count)
        self._log_metric("publishing.skipped", len(result.skipped))
        self._log_metric("publishing.posts_today", self._posts_today)

        log_event(
            self.logger,
            "publishing.report.complete",
            published=success_count,
            failed=failed_count,
            skipped=len(result.skipped),
        )
        return report_data

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _check_posting_policy(self, plan: PublishPlan) -> tuple[bool, str]:
        """Validate whether another post is allowed under current policy.

        Checks:
        - Daily post cap has not been reached.
        - Cooldown period since last post has elapsed.

        Parameters:
            plan: The active publish plan (contains policy parameters).

        Returns:
            A (allowed, reason) tuple.  ``allowed`` is ``True`` if posting
            is permitted; ``reason`` describes why posting was blocked.
        """
        if self._posts_today >= self._max_posts_per_day:
            return (
                False,
                f"Daily cap reached ({self._posts_today}/{self._max_posts_per_day})",
            )

        if self._last_publish_time is not None:
            elapsed = (
                datetime.now(timezone.utc) - self._last_publish_time
            ).total_seconds()
            required_seconds = plan.cooldown_minutes * 60
            if elapsed < required_seconds:
                remaining = int(required_seconds - elapsed)
                return False, f"Cooldown active ({remaining}s remaining)"

        return True, "OK"

    def _format_for_cms(self, candidate: PublishCandidate) -> Dict[str, Any]:
        """Transform a publish candidate into a CMS-ready API payload.

        Formats the HTML body, meta fields, and taxonomy terms according to
        the target CMS's API schema (WordPress REST API by default).

        Parameters:
            candidate: The content to format.

        Returns:
            A dict representing the CMS API request body.
        """
        slug = candidate.slug or self._slugify(candidate.title)

        payload: Dict[str, Any] = {
            "title": candidate.title,
            "content": candidate.html_body,
            "slug": slug,
            "status": "publish",
            "categories": [],
            "tags": [],
            "meta": {
                "niche": candidate.niche,
                "content_id": candidate.content_id,
            },
        }

        self.logger.debug(
            "Formatted CMS payload for content %s (slug=%s).",
            candidate.content_id,
            slug,
        )
        return payload

    def _get_cms_tool(self):
        """Lazily initialize and return a CMSTool reading config from env."""
        if not hasattr(self, "_cms_tool") or self._cms_tool is None:
            import os
            from src.agents.tools.cms_tool import CMSTool

            self._cms_tool = CMSTool(
                {
                    "cms_type": "wordpress",
                    "api_base_url": os.environ.get(
                        "WP_STAGING_BASE_URL",
                        self._cms_api_base_url,
                    ),
                    "username": os.environ.get("WP_STAGING_USER", ""),
                    "api_key": os.environ.get("WP_STAGING_APP_PASSWORD", ""),
                    "default_status": "draft",
                    "request_timeout": 30,
                    "verify_ssl": True,
                }
            )
        return self._cms_tool

    def _push_to_cms(
        self, candidate: PublishCandidate, payload: Dict[str, Any]
    ) -> PublishResult:
        """Push the formatted payload to the CMS API.

        Uses CMSTool for WordPress REST API when credentials are configured.
        In dry-run mode, returns a placeholder. Falls back gracefully when
        no CMS credentials are available.

        Parameters:
            candidate: The content being published.
            payload:   The CMS-ready API payload.

        Returns:
            A :class:`PublishResult` indicating success or failure.
        """
        if self._check_dry_run(
            f"publish content {candidate.content_id} to {self._target_site}"
        ):
            return PublishResult(
                content_id=candidate.content_id,
                success=True,
                published_url=f"https://{self._target_site}/p/{candidate.slug or 'preview'}",
                cms_post_id="dry-run",
                published_at=datetime.now(timezone.utc),
            )

        # Try real CMS publishing via CMSTool
        import os

        if os.environ.get("WP_STAGING_BASE_URL") and os.environ.get(
            "WP_STAGING_APP_PASSWORD"
        ):
            try:
                cms = self._get_cms_tool()
                result = cms.create_post(
                    {
                        "title": payload.get("title", candidate.title),
                        "content": payload.get("content", candidate.html_body),
                        "slug": payload.get("slug", candidate.slug),
                        "status": payload.get("status", "draft"),
                    }
                )

                return PublishResult(
                    content_id=candidate.content_id,
                    success=True,
                    published_url=result.get("url", ""),
                    cms_post_id=str(result.get("id", "")),
                    published_at=datetime.now(timezone.utc),
                )
            except Exception as exc:
                self.logger.error(
                    "CMS publishing failed for content %s: %s",
                    candidate.content_id,
                    exc,
                )
                return PublishResult(
                    content_id=candidate.content_id,
                    success=False,
                    error=f"CMS publishing failed: {exc}",
                )

        # No CMS credentials configured
        self.logger.warning(
            "No CMS credentials configured (WP_STAGING_BASE_URL / WP_STAGING_APP_PASSWORD). "
            "Set them in .env to enable real publishing."
        )
        return PublishResult(
            content_id=candidate.content_id,
            success=False,
            error="No CMS credentials configured. Set WP_STAGING_BASE_URL and WP_STAGING_APP_PASSWORD in .env.",
        )

    @staticmethod
    def _slugify(title: str) -> str:
        """Convert an article title into a URL-safe slug.

        Parameters:
            title: The article title.

        Returns:
            A lowercase, hyphen-separated slug string.
        """
        import re

        slug = title.lower().strip()
        slug = re.sub(r"[^\w\s-]", "", slug)
        slug = re.sub(r"[\s_]+", "-", slug)
        slug = re.sub(r"-+", "-", slug).strip("-")
        return slug[:80]
