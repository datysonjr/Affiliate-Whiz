"""
domains.seo.internal_linking
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Internal linking engine for the OpenClaw SEO domain.

Builds and analyses a directed graph of internal links across a site's
content, then provides recommendations for improving link equity
distribution, fixing orphan pages, and structuring topic hubs.

A well-designed internal linking structure improves crawlability, spreads
page authority, and helps search engines understand the topical hierarchy
of an affiliate site.

Design references:
    - ARCHITECTURE.md  Section 3 (Content Pipeline -- SEO Optimisation)
    - core/constants.py  DEFAULT_MAX_INTERNAL_LINKS, DEFAULT_MIN_INTERNAL_LINKS
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from src.core.constants import DEFAULT_MAX_INTERNAL_LINKS, DEFAULT_MIN_INTERNAL_LINKS
from src.core.logger import get_logger

logger = get_logger("seo.internal_linking")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class PageNode:
    """A single page in the internal link graph.

    Attributes
    ----------
    url:
        Canonical URL of the page.
    title:
        Page title.
    slug:
        URL slug for the page.
    keywords:
        Target keywords for this page.
    category:
        Content category or topic cluster label.
    word_count:
        Page word count.
    link_equity:
        Computed internal link equity score (0.0--1.0).
    inbound_count:
        Number of internal pages linking to this page.
    outbound_count:
        Number of internal pages this page links to.
    is_hub:
        Whether this page is identified as a topic hub.
    metadata:
        Additional page-level data.
    """

    url: str
    title: str = ""
    slug: str = ""
    keywords: List[str] = field(default_factory=list)
    category: str = ""
    word_count: int = 0
    link_equity: float = 0.0
    inbound_count: int = 0
    outbound_count: int = 0
    is_hub: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LinkSuggestion:
    """A suggested internal link to add to a page.

    Attributes
    ----------
    source_url:
        URL of the page that should contain the link.
    target_url:
        URL of the page to link to.
    anchor_text:
        Suggested anchor text for the link.
    relevance_score:
        How relevant the link is (0.0--1.0).
    reason:
        Human-readable explanation of why this link is recommended.
    """

    source_url: str
    target_url: str
    anchor_text: str = ""
    relevance_score: float = 0.0
    reason: str = ""


# ---------------------------------------------------------------------------
# Link graph
# ---------------------------------------------------------------------------

class LinkGraph:
    """Directed graph of internal links for a site.

    Nodes are pages (identified by URL), edges are internal links between
    them.  The graph supports equity calculation, orphan detection, and
    hub-page identification.

    Usage::

        graph = LinkGraph()
        graph.add_page(PageNode(url="/best-desk", title="Best Desks", keywords=["desk"]))
        graph.add_page(PageNode(url="/desk-review", title="Desk Review", keywords=["desk"]))
        graph.add_link("/best-desk", "/desk-review")

        orphans = detect_orphan_pages(graph)
        suggestions = find_link_targets(graph, "/best-desk")
    """

    def __init__(self) -> None:
        self._pages: Dict[str, PageNode] = {}
        self._outbound: Dict[str, Set[str]] = defaultdict(set)
        self._inbound: Dict[str, Set[str]] = defaultdict(set)

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def add_page(self, page: PageNode) -> None:
        """Add a page node to the graph.

        If the page already exists, its metadata is updated.

        Parameters
        ----------
        page:
            Page node to add or update.
        """
        self._pages[page.url] = page
        # Ensure edge sets exist
        if page.url not in self._outbound:
            self._outbound[page.url] = set()
        if page.url not in self._inbound:
            self._inbound[page.url] = set()

    def add_link(self, source_url: str, target_url: str) -> None:
        """Add a directed internal link from source to target.

        Both URLs must have been added as pages first.

        Parameters
        ----------
        source_url:
            URL of the linking page.
        target_url:
            URL of the linked-to page.

        Raises
        ------
        ValueError
            If either URL has not been added to the graph.
        """
        if source_url not in self._pages:
            raise ValueError(f"Source page not in graph: {source_url}")
        if target_url not in self._pages:
            raise ValueError(f"Target page not in graph: {target_url}")
        if source_url == target_url:
            return  # Ignore self-links

        self._outbound[source_url].add(target_url)
        self._inbound[target_url].add(source_url)

        # Update counts on page nodes
        self._pages[source_url].outbound_count = len(self._outbound[source_url])
        self._pages[target_url].inbound_count = len(self._inbound[target_url])

    def remove_link(self, source_url: str, target_url: str) -> None:
        """Remove an internal link from the graph.

        Parameters
        ----------
        source_url:
            URL of the linking page.
        target_url:
            URL of the linked-to page.
        """
        self._outbound[source_url].discard(target_url)
        self._inbound[target_url].discard(source_url)

        if source_url in self._pages:
            self._pages[source_url].outbound_count = len(self._outbound[source_url])
        if target_url in self._pages:
            self._pages[target_url].inbound_count = len(self._inbound[target_url])

    # ------------------------------------------------------------------
    # Graph queries
    # ------------------------------------------------------------------

    @property
    def page_count(self) -> int:
        """Return the total number of pages in the graph."""
        return len(self._pages)

    @property
    def link_count(self) -> int:
        """Return the total number of internal links."""
        return sum(len(targets) for targets in self._outbound.values())

    def get_page(self, url: str) -> Optional[PageNode]:
        """Return the page node for a URL, or ``None``."""
        return self._pages.get(url)

    def get_all_pages(self) -> List[PageNode]:
        """Return all pages in the graph."""
        return list(self._pages.values())

    def get_outbound_links(self, url: str) -> Set[str]:
        """Return the set of URLs that a page links to."""
        return set(self._outbound.get(url, set()))

    def get_inbound_links(self, url: str) -> Set[str]:
        """Return the set of URLs that link to a page."""
        return set(self._inbound.get(url, set()))

    def get_pages_by_category(self, category: str) -> List[PageNode]:
        """Return all pages in a given category."""
        return [p for p in self._pages.values() if p.category == category]

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the graph to a JSON-friendly dictionary."""
        return {
            "page_count": self.page_count,
            "link_count": self.link_count,
            "pages": {
                url: {
                    "title": page.title,
                    "category": page.category,
                    "inbound": page.inbound_count,
                    "outbound": page.outbound_count,
                    "link_equity": page.link_equity,
                    "is_hub": page.is_hub,
                }
                for url, page in self._pages.items()
            },
        }

    def __repr__(self) -> str:
        return f"LinkGraph(pages={self.page_count}, links={self.link_count})"


# ---------------------------------------------------------------------------
# Analysis functions
# ---------------------------------------------------------------------------

def find_link_targets(
    graph: LinkGraph,
    source_url: str,
    *,
    max_suggestions: int = 10,
) -> List[LinkSuggestion]:
    """Find the best internal link targets for a given page.

    Analyses keyword overlap, category affinity, and current link equity
    distribution to suggest pages that would benefit from a link.

    Parameters
    ----------
    graph:
        The site's internal link graph.
    source_url:
        URL of the page to find link targets for.
    max_suggestions:
        Maximum number of suggestions to return.

    Returns
    -------
    list[LinkSuggestion]
        Suggested links sorted by relevance score (highest first).
    """
    source = graph.get_page(source_url)
    if source is None:
        logger.warning("Source page not found in graph: %s", source_url)
        return []

    existing_links = graph.get_outbound_links(source_url)
    source_keywords = set(kw.lower() for kw in source.keywords)
    suggestions: List[LinkSuggestion] = []

    for page in graph.get_all_pages():
        if page.url == source_url:
            continue
        if page.url in existing_links:
            continue

        # Calculate relevance score
        score = 0.0
        reasons: List[str] = []

        # Keyword overlap
        target_keywords = set(kw.lower() for kw in page.keywords)
        overlap = source_keywords & target_keywords
        if overlap:
            keyword_score = len(overlap) / max(len(source_keywords), 1)
            score += keyword_score * 0.5
            reasons.append(f"shared keywords: {', '.join(list(overlap)[:3])}")

        # Same category bonus
        if source.category and page.category == source.category:
            score += 0.25
            reasons.append(f"same category: {source.category}")

        # Low inbound count bonus (help under-linked pages)
        if page.inbound_count < DEFAULT_MIN_INTERNAL_LINKS:
            deficit = DEFAULT_MIN_INTERNAL_LINKS - page.inbound_count
            score += min(deficit * 0.08, 0.25)
            reasons.append(f"under-linked ({page.inbound_count} inbound)")

        if score > 0:
            # Determine anchor text from the best matching keyword
            if overlap:
                anchor = sorted(overlap, key=len, reverse=True)[0]
            else:
                anchor = page.title

            suggestions.append(LinkSuggestion(
                source_url=source_url,
                target_url=page.url,
                anchor_text=anchor,
                relevance_score=round(min(score, 1.0), 3),
                reason="; ".join(reasons),
            ))

    suggestions.sort(key=lambda s: s.relevance_score, reverse=True)
    result = suggestions[:max_suggestions]

    logger.debug(
        "Found %d link suggestions for %s (showing top %d)",
        len(suggestions),
        source_url,
        len(result),
    )
    return result


def calculate_link_equity(
    graph: LinkGraph,
    *,
    damping_factor: float = 0.85,
    iterations: int = 20,
    tolerance: float = 1e-6,
) -> Dict[str, float]:
    """Calculate internal link equity using a simplified PageRank algorithm.

    Assigns each page a link equity score based on the number and quality
    of internal links pointing to it.  Pages with more high-equity inbound
    links receive higher scores.

    Parameters
    ----------
    graph:
        The site's internal link graph.
    damping_factor:
        Probability that a "random surfer" follows a link rather than
        jumping to a random page.  Standard value is 0.85.
    iterations:
        Maximum number of iterative computation rounds.
    tolerance:
        Convergence threshold.  Stops when the max change between
        iterations falls below this value.

    Returns
    -------
    dict[str, float]
        Mapping of page URL to link equity score.  Scores are normalised
        to sum to 1.0 across all pages.
    """
    pages = graph.get_all_pages()
    n = len(pages)
    if n == 0:
        return {}

    urls = [p.url for p in pages]
    # Initialise uniform equity
    equity: Dict[str, float] = {url: 1.0 / n for url in urls}
    base_value = (1.0 - damping_factor) / n

    for iteration in range(iterations):
        new_equity: Dict[str, float] = {}
        max_delta = 0.0

        for url in urls:
            incoming = graph.get_inbound_links(url)
            rank_sum = 0.0
            for in_url in incoming:
                out_count = len(graph.get_outbound_links(in_url))
                if out_count > 0:
                    rank_sum += equity[in_url] / out_count

            new_val = base_value + damping_factor * rank_sum
            new_equity[url] = new_val
            max_delta = max(max_delta, abs(new_val - equity[url]))

        equity = new_equity

        if max_delta < tolerance:
            logger.debug("Link equity converged after %d iterations", iteration + 1)
            break

    # Normalise so scores sum to 1.0
    total = sum(equity.values())
    if total > 0:
        equity = {url: round(val / total, 6) for url, val in equity.items()}

    # Update page nodes with computed equity
    for url, score in equity.items():
        page = graph.get_page(url)
        if page:
            page.link_equity = score

    logger.info(
        "Computed link equity for %d pages (damping=%.2f, iterations<=%d)",
        n,
        damping_factor,
        iterations,
    )
    return equity


def detect_orphan_pages(graph: LinkGraph) -> List[PageNode]:
    """Identify orphan pages that have no internal links pointing to them.

    Orphan pages are effectively invisible to search engine crawlers that
    discover pages by following links from the homepage.  They should
    either be linked from relevant content or removed.

    Parameters
    ----------
    graph:
        The site's internal link graph.

    Returns
    -------
    list[PageNode]
        Pages with zero inbound internal links.
    """
    orphans: List[PageNode] = []

    for page in graph.get_all_pages():
        inbound = graph.get_inbound_links(page.url)
        if len(inbound) == 0:
            orphans.append(page)

    if orphans:
        logger.warning(
            "Detected %d orphan pages with no inbound links: %s",
            len(orphans),
            [p.url for p in orphans[:5]],
        )
    else:
        logger.info("No orphan pages detected")

    return orphans


def suggest_hub_pages(
    graph: LinkGraph,
    *,
    min_category_pages: int = 3,
    top_n: int = 5,
) -> List[PageNode]:
    """Identify pages that should serve as topic hub / pillar pages.

    A hub page is the central page of a topic cluster, linking out to
    all related spoke pages and accumulating authority.  This function
    identifies the best candidate for each category based on inbound
    links, word count, and outbound connectivity.

    Parameters
    ----------
    graph:
        The site's internal link graph.
    min_category_pages:
        Minimum number of pages in a category to warrant a hub.
    top_n:
        Maximum number of hub suggestions to return.

    Returns
    -------
    list[PageNode]
        Suggested hub pages sorted by hub score (highest first).
    """
    # Group pages by category
    categories: Dict[str, List[PageNode]] = defaultdict(list)
    for page in graph.get_all_pages():
        if page.category:
            categories[page.category].append(page)

    hub_candidates: List[Tuple[PageNode, float]] = []

    for category, pages in categories.items():
        if len(pages) < min_category_pages:
            continue

        # Score each page's suitability as a hub
        for page in pages:
            # Hub score: weighted combination of inbound links, outbound
            # connectivity within category, and content depth
            category_outbound = sum(
                1 for p in pages
                if p.url in graph.get_outbound_links(page.url)
            )
            coverage = category_outbound / max(len(pages) - 1, 1)

            hub_score = (
                page.inbound_count * 0.3
                + coverage * 40
                + min(page.word_count / 100, 20) * 0.3
            )

            hub_candidates.append((page, hub_score))

    # Sort by hub score and take top N
    hub_candidates.sort(key=lambda x: x[1], reverse=True)

    # Mark the selected pages as hubs
    hubs: List[PageNode] = []
    seen_categories: Set[str] = set()

    for page, score in hub_candidates:
        if page.category in seen_categories:
            continue
        page.is_hub = True
        hubs.append(page)
        seen_categories.add(page.category)
        if len(hubs) >= top_n:
            break

    logger.info(
        "Identified %d hub page candidates across %d categories",
        len(hubs),
        len(categories),
    )
    return hubs
