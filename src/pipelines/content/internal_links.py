"""
pipelines.content.internal_links
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Manage internal linking between published articles to strengthen site
architecture, distribute page authority, and improve crawlability.

Finds contextually relevant link opportunities within article text,
inserts links, maintains hub-page indices, and identifies orphan pages
that lack inbound links.

Design references:
    - config/pipelines.yaml  ``content.steps[4]``  (min_links, max_links)
    - ARCHITECTURE.md  Section 3 (Content Pipeline)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.core.constants import (
    DEFAULT_MAX_INTERNAL_LINKS,
)
from src.core.logger import get_logger, log_event

logger = get_logger("pipelines.content.internal_links")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class LinkOpportunity:
    """A potential internal link insertion point.

    Attributes
    ----------
    anchor_text:
        The text to hyperlink.
    target_url:
        The URL of the target page.
    target_title:
        Title of the target page for context.
    context_sentence:
        The sentence where the anchor was found.
    relevance_score:
        How relevant this link is to the current content (0.0 - 1.0).
    section_index:
        Index of the section where the anchor text appears.
    """

    anchor_text: str
    target_url: str
    target_title: str = ""
    context_sentence: str = ""
    relevance_score: float = 0.0
    section_index: int = 0


@dataclass
class InternalLinkReport:
    """Summary of internal linking operations on an article.

    Attributes
    ----------
    article_title:
        Title of the article being linked.
    links_added:
        Number of new links inserted.
    links_found:
        Total link opportunities identified.
    opportunities:
        All identified :class:`LinkOpportunity` objects.
    orphan_pages:
        Pages with no inbound links.
    hub_pages_updated:
        Hub/index pages that were updated with a link to this article.
    """

    article_title: str = ""
    links_added: int = 0
    links_found: int = 0
    opportunities: List[LinkOpportunity] = field(default_factory=list)
    orphan_pages: List[str] = field(default_factory=list)
    hub_pages_updated: List[str] = field(default_factory=list)


@dataclass
class SiteArticle:
    """Lightweight representation of a published article for link matching.

    Attributes
    ----------
    url:
        Full URL of the article.
    title:
        Article title.
    primary_keyword:
        The main keyword this article targets.
    category:
        Content category.
    inbound_link_count:
        Number of internal links pointing to this article.
    """

    url: str
    title: str
    primary_keyword: str = ""
    category: str = ""
    inbound_link_count: int = 0


# ---------------------------------------------------------------------------
# Link opportunity discovery
# ---------------------------------------------------------------------------

def find_link_opportunities(
    article_text: str,
    existing_articles: List[SiteArticle],
    *,
    current_url: str = "",
    max_links: int = DEFAULT_MAX_INTERNAL_LINKS,
    min_relevance: float = 0.3,
) -> List[LinkOpportunity]:
    """Find contextually relevant internal link insertion points.

    Scans the article text for phrases that match keywords or titles of
    existing published articles, scoring each match by textual relevance.

    Parameters
    ----------
    article_text:
        The full article text to scan for link opportunities.
    existing_articles:
        List of all published articles on the site.
    current_url:
        URL of the current article (excluded from link targets to avoid
        self-linking).
    max_links:
        Maximum number of link opportunities to return.
    min_relevance:
        Minimum relevance score (0.0-1.0) for a match to be considered.

    Returns
    -------
    list[LinkOpportunity]
        Sorted list of link opportunities (highest relevance first),
        capped at *max_links*.
    """
    opportunities: List[LinkOpportunity] = []
    text_lower = article_text.lower()
    sentences = re.split(r'(?<=[.!?])\s+', article_text.strip())
    seen_targets: set[str] = set()

    for target in existing_articles:
        # Skip self-links
        if target.url == current_url:
            continue

        # Skip if we already have a link to this target
        if target.url in seen_targets:
            continue

        # Find keyword matches in the text
        keyword = target.primary_keyword.lower()
        title_words = target.title.lower()

        best_match = _find_best_anchor(text_lower, sentences, keyword, title_words)
        if best_match is None:
            continue

        anchor_text, context_sentence, relevance = best_match

        if relevance < min_relevance:
            continue

        opportunities.append(
            LinkOpportunity(
                anchor_text=anchor_text,
                target_url=target.url,
                target_title=target.title,
                context_sentence=context_sentence,
                relevance_score=round(relevance, 3),
            )
        )
        seen_targets.add(target.url)

    # Sort by relevance descending, then cap at max_links
    opportunities.sort(key=lambda o: o.relevance_score, reverse=True)
    capped = opportunities[:max_links]

    log_event(
        logger,
        "internal_links.find.ok",
        total_found=len(opportunities),
        returned=len(capped),
        max_links=max_links,
    )
    return capped


def _find_best_anchor(
    text_lower: str,
    sentences: List[str],
    keyword: str,
    title_words: str,
) -> Optional[Tuple[str, str, float]]:
    """Find the best anchor text and context for a target article.

    Tries to match the full keyword phrase first, then falls back to
    matching significant words from the title.

    Parameters
    ----------
    text_lower:
        Lowercased article text.
    sentences:
        List of original-case sentences.
    keyword:
        Target article's primary keyword (lowercase).
    title_words:
        Target article's title (lowercase).

    Returns
    -------
    tuple[str, str, float] or None
        (anchor_text, context_sentence, relevance_score) or ``None`` if
        no match.
    """
    # Strategy 1: Exact keyword match
    if keyword and keyword in text_lower:
        for sentence in sentences:
            if keyword in sentence.lower():
                # Extract the original-case version of the keyword
                start = sentence.lower().find(keyword)
                anchor = sentence[start:start + len(keyword)]
                return (anchor, sentence, 0.9)

    # Strategy 2: Match significant title words (3+ chars)
    title_tokens = [w for w in title_words.split() if len(w) >= 3]
    if not title_tokens:
        return None

    for sentence in sentences:
        sentence_lower = sentence.lower()
        matched_tokens = sum(1 for t in title_tokens if t in sentence_lower)
        match_ratio = matched_tokens / len(title_tokens) if title_tokens else 0

        if match_ratio >= 0.5:
            # Use the longest matching phrase as anchor
            anchor = _extract_matching_phrase(sentence, title_tokens)
            relevance = min(match_ratio * 0.8, 0.8)
            return (anchor, sentence, relevance)

    return None


def _extract_matching_phrase(sentence: str, tokens: List[str]) -> str:
    """Extract the best contiguous phrase matching the given tokens.

    Parameters
    ----------
    sentence:
        The original-case sentence.
    tokens:
        Lowercase tokens to match against.

    Returns
    -------
    str
        The extracted anchor phrase.
    """
    words = sentence.split()
    best_start = 0
    best_end = 0
    best_count = 0

    for i in range(len(words)):
        for j in range(i + 1, min(i + 6, len(words) + 1)):
            phrase_words = [w.lower().strip(".,;:!?()\"'") for w in words[i:j]]
            matches = sum(1 for pw in phrase_words if any(t in pw for t in tokens))
            if matches > best_count:
                best_count = matches
                best_start = i
                best_end = j

    if best_count > 0:
        return " ".join(words[best_start:best_end])
    return sentence.split()[0] if sentence.split() else ""


# ---------------------------------------------------------------------------
# Link insertion
# ---------------------------------------------------------------------------

def insert_links(
    article_text: str,
    opportunities: List[LinkOpportunity],
    *,
    max_links: int = DEFAULT_MAX_INTERNAL_LINKS,
    link_format: str = "markdown",
) -> Tuple[str, int]:
    """Insert internal links into the article text.

    Replaces anchor text occurrences with hyperlinks, respecting the
    maximum link count and avoiding double-linking the same phrase.

    Parameters
    ----------
    article_text:
        The article text to modify.
    opportunities:
        List of link opportunities to insert.
    max_links:
        Maximum total internal links to add.
    link_format:
        Output format: ``"markdown"`` for ``[text](url)`` or
        ``"html"`` for ``<a href="url">text</a>``.

    Returns
    -------
    tuple[str, int]
        The modified article text and the count of links inserted.
    """
    modified = article_text
    inserted = 0

    for opp in opportunities[:max_links]:
        if inserted >= max_links:
            break

        anchor = opp.anchor_text
        if not anchor or anchor not in modified:
            continue

        # Only replace the first occurrence to avoid over-linking
        if link_format == "html":
            link_tag = f'<a href="{opp.target_url}" title="{opp.target_title}">{anchor}</a>'
        else:
            link_tag = f"[{anchor}]({opp.target_url})"

        # Check if this anchor is already linked
        if f"]({opp.target_url})" in modified or f'href="{opp.target_url}"' in modified:
            continue

        modified = modified.replace(anchor, link_tag, 1)
        inserted += 1

    log_event(
        logger,
        "internal_links.insert.ok",
        links_inserted=inserted,
        max_links=max_links,
    )
    return modified, inserted


# ---------------------------------------------------------------------------
# Hub page management
# ---------------------------------------------------------------------------

def update_hub_pages(
    article_url: str,
    article_title: str,
    article_category: str,
    hub_pages: Dict[str, Dict[str, Any]],
    *,
    link_format: str = "markdown",
) -> List[str]:
    """Add the new article to relevant hub/index pages.

    Hub pages are category-level landing pages that link to all articles
    in a given category.  This function updates their content to include
    the new article.

    Parameters
    ----------
    article_url:
        URL of the newly published article.
    article_title:
        Title of the new article.
    article_category:
        Category the article belongs to.
    hub_pages:
        Dict mapping category names to hub page info dicts with keys
        ``url``, ``content``, and ``title``.
    link_format:
        Link format (``"markdown"`` or ``"html"``).

    Returns
    -------
    list[str]
        URLs of hub pages that were updated.
    """
    updated: List[str] = []

    for category, hub_info in hub_pages.items():
        if category.lower() != article_category.lower():
            continue

        hub_url = hub_info.get("url", "")
        hub_content = hub_info.get("content", "")

        # Skip if the article is already linked from this hub
        if article_url in hub_content:
            continue

        # Create the link entry
        if link_format == "html":
            link_entry = f'<li><a href="{article_url}">{article_title}</a></li>'
        else:
            link_entry = f"- [{article_title}]({article_url})"

        hub_info["content"] = hub_content.rstrip() + "\n" + link_entry + "\n"
        updated.append(hub_url)

    log_event(
        logger,
        "internal_links.hub_update.ok",
        category=article_category,
        hubs_updated=len(updated),
    )
    return updated


# ---------------------------------------------------------------------------
# Orphan page detection
# ---------------------------------------------------------------------------

def check_orphan_pages(
    all_articles: List[SiteArticle],
    *,
    min_inbound_links: int = 1,
) -> List[str]:
    """Identify published pages that have no inbound internal links.

    Orphan pages are hard for search engines to discover and tend to
    under-perform.  This function identifies them so the linking
    strategy can address the gap.

    Parameters
    ----------
    all_articles:
        List of all published articles with their inbound link counts.
    min_inbound_links:
        Minimum number of inbound links a page needs to not be
        considered an orphan.

    Returns
    -------
    list[str]
        URLs of orphan pages.
    """
    orphans = [
        article.url
        for article in all_articles
        if article.inbound_link_count < min_inbound_links
    ]

    log_event(
        logger,
        "internal_links.orphans.checked",
        total_articles=len(all_articles),
        orphan_count=len(orphans),
    )
    return orphans
