"""
agents.traffic_routing_agent
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The TrafficRoutingAgent manages internal linking across the site.  It
analyses the existing link structure to find orphaned pages, suggests new
internal links to improve site topology, and updates content with optimised
cross-references.  Good internal linking improves crawlability, distributes
page authority, and boosts organic traffic.

Design references:
    - ARCHITECTURE.md  Section 2 (Agent Architecture)
    - config/agents.yaml      (traffic_routing settings)
    - config/thresholds.yaml  (min/max internal links per page)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from src.agents.base_agent import BaseAgent
from src.core.constants import (
    AgentName,
    DEFAULT_MAX_INTERNAL_LINKS,
    DEFAULT_MIN_INTERNAL_LINKS,
)
from src.core.logger import log_event

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PageNode:
    """Represents a single page in the site's link graph.

    Attributes:
        url:            Canonical URL of the page.
        title:          Page title.
        slug:           URL slug.
        niche:          Niche this page belongs to.
        primary_keyword: Primary target keyword.
        inbound_links:  Number of internal links pointing to this page.
        outbound_links: Number of internal links from this page.
        is_orphan:      True if the page has zero inbound internal links.
        word_count:     Word count of the page content.
    """

    url: str
    title: str = ""
    slug: str = ""
    niche: str = ""
    primary_keyword: str = ""
    inbound_links: int = 0
    outbound_links: int = 0
    is_orphan: bool = False
    word_count: int = 0


@dataclass
class LinkSuggestion:
    """A suggested internal link to add.

    Attributes:
        source_url:    The page that should contain the link.
        target_url:    The page being linked to.
        anchor_text:   Suggested anchor text for the link.
        relevance:     Topical relevance score (0-1.0).
        reason:        Why this link was suggested.
    """

    source_url: str
    target_url: str
    anchor_text: str = ""
    relevance: float = 0.0
    reason: str = ""


@dataclass
class LinkChange:
    """Record of an internal link that was added or removed.

    Attributes:
        source_url:  The page that was modified.
        target_url:  The page being linked to.
        anchor_text: Anchor text used.
        action:      Whether the link was ``added`` or ``removed``.
        success:     Whether the change was applied successfully.
        error:       Error message if the change failed.
    """

    source_url: str
    target_url: str
    anchor_text: str = ""
    action: str = "added"
    success: bool = False
    error: str = ""


@dataclass
class TrafficRoutingPlan:
    """Output of the planning phase -- link structure analysis and suggestions.

    Attributes:
        pages:           All pages in the link graph.
        orphan_pages:    Pages with no inbound internal links.
        under_linked:    Pages below the minimum internal link threshold.
        over_linked:     Pages above the maximum internal link threshold.
        suggestions:     Proposed new internal links.
        plan_time:       When the plan was generated.
    """

    pages: List[PageNode] = field(default_factory=list)
    orphan_pages: List[PageNode] = field(default_factory=list)
    under_linked: List[PageNode] = field(default_factory=list)
    over_linked: List[PageNode] = field(default_factory=list)
    suggestions: List[LinkSuggestion] = field(default_factory=list)
    plan_time: Optional[datetime] = None


@dataclass
class TrafficRoutingResult:
    """Aggregated results from link structure updates.

    Attributes:
        changes:         Links that were added or removed.
        orphans_fixed:   Number of orphan pages that received new inbound links.
        links_added:     Total number of links added.
        links_removed:   Total number of links removed.
        errors:          Errors encountered during execution.
    """

    changes: List[LinkChange] = field(default_factory=list)
    orphans_fixed: int = 0
    links_added: int = 0
    links_removed: int = 0
    errors: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent implementation
# ---------------------------------------------------------------------------

class TrafficRoutingAgent(BaseAgent):
    """Manages internal linking to improve site topology and organic traffic.

    The traffic routing agent periodically crawls the site's internal link
    structure, identifies orphaned and under-linked pages, and generates
    link suggestions based on topical relevance and keyword overlap.  It
    then applies approved suggestions by updating page content in the CMS.

    Configuration keys (from ``config/agents.yaml`` under ``traffic_routing``):
        enabled:               bool  -- whether this agent is active.
        min_internal_links:    int   -- minimum inbound links per page.
        max_internal_links:    int   -- maximum outbound links per page.
        max_suggestions:       int   -- cap on suggestions per cycle.
        relevance_threshold:   float -- minimum relevance score to suggest.
        auto_apply:            bool  -- whether to apply suggestions automatically.
        site_base_url:         str   -- base URL for the site.
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        super().__init__(name=str(AgentName.TRAFFIC_ROUTING), config=config)
        self._min_internal_links: int = config.get(
            "min_internal_links", DEFAULT_MIN_INTERNAL_LINKS
        )
        self._max_internal_links: int = config.get(
            "max_internal_links", DEFAULT_MAX_INTERNAL_LINKS
        )
        self._max_suggestions: int = config.get("max_suggestions", 20)
        self._relevance_threshold: float = config.get("relevance_threshold", 0.3)
        self._auto_apply: bool = config.get("auto_apply", False)
        self._site_base_url: str = config.get("site_base_url", "https://example.com")

    # ------------------------------------------------------------------
    # BaseAgent lifecycle
    # ------------------------------------------------------------------

    def plan(self) -> TrafficRoutingPlan:
        """Analyse the site's internal link structure and propose improvements.

        Builds a link graph, identifies orphaned and under-linked pages,
        and generates link suggestions based on topical relevance.

        Returns:
            A :class:`TrafficRoutingPlan` with analysis results and suggestions.
        """
        log_event(self.logger, "traffic_routing.plan.start")

        # Step 1: Build the page graph
        pages = self._build_link_graph()

        # Step 2: Find orphaned pages
        orphan_pages = self._find_orphans(pages)

        # Step 3: Identify under-linked and over-linked pages
        under_linked = [
            p for p in pages
            if p.inbound_links < self._min_internal_links and not p.is_orphan
        ]
        over_linked = [
            p for p in pages
            if p.outbound_links > self._max_internal_links
        ]

        # Step 4: Generate link suggestions
        suggestions = self._suggest_links(pages, orphan_pages, under_linked)

        plan = TrafficRoutingPlan(
            pages=pages,
            orphan_pages=orphan_pages,
            under_linked=under_linked,
            over_linked=over_linked,
            suggestions=suggestions[:self._max_suggestions],
            plan_time=datetime.now(timezone.utc),
        )

        log_event(
            self.logger,
            "traffic_routing.plan.complete",
            total_pages=len(pages),
            orphans=len(orphan_pages),
            under_linked=len(under_linked),
            over_linked=len(over_linked),
            suggestions=len(plan.suggestions),
        )
        return plan

    def execute(self, plan: TrafficRoutingPlan) -> TrafficRoutingResult:
        """Update internal links based on the plan's suggestions.

        If ``auto_apply`` is enabled, suggestions are applied directly to
        the CMS.  Otherwise, they are recorded as pending for manual review.

        Parameters:
            plan: The :class:`TrafficRoutingPlan` from planning.

        Returns:
            A :class:`TrafficRoutingResult` with applied changes.
        """
        result = TrafficRoutingResult()

        if not self._auto_apply:
            self.logger.info(
                "Auto-apply is disabled. %d suggestions recorded for manual review.",
                len(plan.suggestions),
            )
            return result

        for suggestion in plan.suggestions:
            log_event(
                self.logger,
                "traffic_routing.link.apply",
                source=suggestion.source_url,
                target=suggestion.target_url,
                relevance=suggestion.relevance,
            )

            try:
                change = self._apply_link(suggestion)
                result.changes.append(change)

                if change.success:
                    result.links_added += 1
                    # Check if this fixed an orphan
                    if any(
                        p.url == suggestion.target_url
                        for p in plan.orphan_pages
                    ):
                        result.orphans_fixed += 1
                else:
                    result.errors.append(
                        f"Failed to add link {suggestion.source_url} -> "
                        f"{suggestion.target_url}: {change.error}"
                    )

            except Exception as exc:
                change = LinkChange(
                    source_url=suggestion.source_url,
                    target_url=suggestion.target_url,
                    anchor_text=suggestion.anchor_text,
                    action="added",
                    success=False,
                    error=str(exc),
                )
                result.changes.append(change)
                result.errors.append(
                    f"Exception adding link {suggestion.source_url} -> "
                    f"{suggestion.target_url}: {exc}"
                )
                self.logger.error(
                    "Failed to apply link suggestion: %s -> %s: %s",
                    suggestion.source_url, suggestion.target_url, exc,
                )

        return result

    def report(self, plan: TrafficRoutingPlan, result: TrafficRoutingResult) -> Dict[str, Any]:
        """Log link structure changes and return a summary.

        Parameters:
            plan:   The traffic routing plan.
            result: The execution result.

        Returns:
            A summary dict for the orchestrator's audit log.
        """
        report_data: Dict[str, Any] = {
            "total_pages": len(plan.pages),
            "orphan_pages": len(plan.orphan_pages),
            "under_linked_pages": len(plan.under_linked),
            "over_linked_pages": len(plan.over_linked),
            "suggestions_generated": len(plan.suggestions),
            "links_added": result.links_added,
            "links_removed": result.links_removed,
            "orphans_fixed": result.orphans_fixed,
            "auto_apply": self._auto_apply,
            "top_suggestions": [
                {
                    "source": s.source_url,
                    "target": s.target_url,
                    "anchor": s.anchor_text,
                    "relevance": s.relevance,
                }
                for s in plan.suggestions[:10]
            ],
            "errors": result.errors,
        }

        self._log_metric("traffic_routing.pages_total", len(plan.pages))
        self._log_metric("traffic_routing.orphans", len(plan.orphan_pages))
        self._log_metric("traffic_routing.suggestions", len(plan.suggestions))
        self._log_metric("traffic_routing.links_added", result.links_added)
        self._log_metric("traffic_routing.orphans_fixed", result.orphans_fixed)

        log_event(
            self.logger,
            "traffic_routing.report.complete",
            pages=len(plan.pages),
            orphans=len(plan.orphan_pages),
            links_added=result.links_added,
        )
        return report_data

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_link_graph(self) -> List[PageNode]:
        """Build a graph of all pages and their internal links.

        In production this crawls the site or queries the CMS database
        to enumerate all published pages and their outbound/inbound links.

        Returns:
            A list of :class:`PageNode` instances representing the site graph.
        """
        if self._check_dry_run("build internal link graph"):
            return []

        self.logger.debug("Building internal link graph for %s.", self._site_base_url)

        # Placeholder: real implementation crawls the site or queries the CMS
        return []

    def _find_orphans(self, pages: List[PageNode]) -> List[PageNode]:
        """Identify pages with no inbound internal links.

        An orphan page is one that no other page links to, making it
        effectively invisible to crawlers following internal links.

        Parameters:
            pages: All pages in the link graph.

        Returns:
            A list of orphan :class:`PageNode` instances.
        """
        orphans: List[PageNode] = []

        for page in pages:
            if page.inbound_links == 0:
                page.is_orphan = True
                orphans.append(page)

        self.logger.info(
            "Found %d orphan pages out of %d total.", len(orphans), len(pages),
        )
        return orphans

    def _suggest_links(
        self,
        all_pages: List[PageNode],
        orphan_pages: List[PageNode],
        under_linked: List[PageNode],
    ) -> List[LinkSuggestion]:
        """Generate internal link suggestions based on topical relevance.

        Prioritises linking to orphan pages first, then under-linked pages.
        Suggestions are scored by keyword and niche overlap between source
        and target pages.

        Parameters:
            all_pages:    All pages in the site graph.
            orphan_pages: Pages with no inbound links.
            under_linked: Pages below the minimum link threshold.

        Returns:
            A list of :class:`LinkSuggestion` sorted by relevance descending.
        """
        suggestions: List[LinkSuggestion] = []

        # Build a niche-to-pages index for efficient lookup
        niche_index: Dict[str, List[PageNode]] = {}
        for page in all_pages:
            niche_index.setdefault(page.niche, []).append(page)

        # Suggest links to orphan pages from same-niche pages
        for orphan in orphan_pages:
            candidates = niche_index.get(orphan.niche, [])
            for source in candidates:
                if source.url == orphan.url:
                    continue
                if source.outbound_links >= self._max_internal_links:
                    continue

                relevance = self._compute_relevance(source, orphan)
                if relevance >= self._relevance_threshold:
                    suggestions.append(LinkSuggestion(
                        source_url=source.url,
                        target_url=orphan.url,
                        anchor_text=orphan.primary_keyword or orphan.title,
                        relevance=relevance,
                        reason=f"Orphan page in niche '{orphan.niche}'",
                    ))

        # Suggest links to under-linked pages
        for target in under_linked:
            candidates = niche_index.get(target.niche, [])
            for source in candidates:
                if source.url == target.url:
                    continue
                if source.outbound_links >= self._max_internal_links:
                    continue

                relevance = self._compute_relevance(source, target)
                if relevance >= self._relevance_threshold:
                    suggestions.append(LinkSuggestion(
                        source_url=source.url,
                        target_url=target.url,
                        anchor_text=target.primary_keyword or target.title,
                        relevance=relevance,
                        reason=(
                            f"Under-linked page ({target.inbound_links} < "
                            f"{self._min_internal_links} min)"
                        ),
                    ))

        # Deduplicate and sort by relevance
        seen: Set[Tuple[str, str]] = set()
        unique_suggestions: List[LinkSuggestion] = []
        for s in suggestions:
            key = (s.source_url, s.target_url)
            if key not in seen:
                seen.add(key)
                unique_suggestions.append(s)

        unique_suggestions.sort(key=lambda s: s.relevance, reverse=True)

        self.logger.info(
            "Generated %d link suggestions (%d unique).",
            len(suggestions), len(unique_suggestions),
        )
        return unique_suggestions

    @staticmethod
    def _compute_relevance(source: PageNode, target: PageNode) -> float:
        """Compute a topical relevance score between two pages.

        Uses niche overlap and keyword similarity as proxy signals.  In
        production this could use embeddings or TF-IDF similarity.

        Parameters:
            source: The page that would contain the link.
            target: The page being linked to.

        Returns:
            A float between 0 and 1.0.
        """
        score = 0.0

        # Same niche is a strong relevance signal
        if source.niche and source.niche == target.niche:
            score += 0.5

        # Keyword overlap in title
        source_words = set(source.title.lower().split())
        target_words = set(target.title.lower().split())
        if source_words and target_words:
            overlap = len(source_words & target_words)
            max_possible = min(len(source_words), len(target_words))
            if max_possible > 0:
                score += 0.3 * (overlap / max_possible)

        # Primary keyword match
        if (
            source.primary_keyword
            and target.primary_keyword
            and source.primary_keyword.lower() in target.primary_keyword.lower()
        ):
            score += 0.2

        return min(round(score, 3), 1.0)

    def _apply_link(self, suggestion: LinkSuggestion) -> LinkChange:
        """Apply a link suggestion by updating the source page's content.

        In production this calls the CMS API to update the page HTML,
        inserting an anchor tag at a suitable location.

        Parameters:
            suggestion: The link suggestion to apply.

        Returns:
            A :class:`LinkChange` recording the outcome.
        """
        if self._check_dry_run(
            f"add link from '{suggestion.source_url}' to '{suggestion.target_url}'"
        ):
            return LinkChange(
                source_url=suggestion.source_url,
                target_url=suggestion.target_url,
                anchor_text=suggestion.anchor_text,
                action="added",
                success=True,
            )

        self.logger.debug(
            "Applying link: %s -> %s (anchor='%s').",
            suggestion.source_url, suggestion.target_url, suggestion.anchor_text,
        )

        # Placeholder: real implementation updates the CMS content
        return LinkChange(
            source_url=suggestion.source_url,
            target_url=suggestion.target_url,
            anchor_text=suggestion.anchor_text,
            action="added",
            success=False,
            error="CMS integration not yet implemented.",
        )
