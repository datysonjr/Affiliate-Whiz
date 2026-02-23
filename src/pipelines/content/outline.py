"""
pipelines.content.outline
~~~~~~~~~~~~~~~~~~~~~~~~~~

Generate structured content outlines for affiliate articles.  An outline
defines the heading hierarchy, section purposes, estimated word counts,
and keyword placement strategy *before* any prose is written.

The outline stage bridges the gap between a scored offer and a finished
draft by providing the ``draft`` stage with a deterministic blueprint.

Design references:
    - config/pipelines.yaml  ``content.steps[0]``  (max_sections)
    - ARCHITECTURE.md  Section 3 (Content Pipeline)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.core.constants import (
    DEFAULT_TARGET_WORD_COUNT,
)
from src.core.errors import PipelineStepError
from src.core.logger import get_logger, log_event

logger = get_logger("pipelines.content.outline")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SectionPlan:
    """Blueprint for a single section within the article outline.

    Attributes
    ----------
    heading:
        The heading text (H2 or H3).
    heading_level:
        HTML heading level (2 for H2, 3 for H3, etc.).
    purpose:
        Brief description of the section's goal (e.g. "product overview",
        "pros/cons", "pricing comparison").
    target_words:
        Approximate word count target for this section.
    keywords:
        Primary and secondary keywords to weave into this section.
    subsections:
        Optional child sections (H3s under an H2).
    notes:
        Free-form guidance for the draft stage.
    """

    heading: str
    heading_level: int = 2
    purpose: str = ""
    target_words: int = 200
    keywords: List[str] = field(default_factory=list)
    subsections: List["SectionPlan"] = field(default_factory=list)
    notes: str = ""


@dataclass
class ContentOutline:
    """Full outline for an affiliate content piece.

    Attributes
    ----------
    outline_id:
        Unique identifier for this outline.
    title:
        Working title for the article.
    offer_id:
        Identifier of the primary offer this content promotes.
    content_type:
        Article type: ``"review"``, ``"comparison"``, ``"roundup"``,
        ``"how_to"``, or ``"buying_guide"``.
    primary_keyword:
        The main target keyword for SEO.
    secondary_keywords:
        Supporting keywords and long-tail variants.
    sections:
        Ordered list of :class:`SectionPlan` objects forming the body.
    estimated_words:
        Total estimated word count across all sections.
    meta_notes:
        High-level editorial guidance (tone, audience, angle).
    """

    title: str
    offer_id: str
    content_type: str = "review"
    primary_keyword: str = ""
    secondary_keywords: List[str] = field(default_factory=list)
    sections: List[SectionPlan] = field(default_factory=list)
    estimated_words: int = 0
    meta_notes: str = ""
    outline_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


# ---------------------------------------------------------------------------
# Content type templates
# ---------------------------------------------------------------------------

_SECTION_TEMPLATES: Dict[str, List[Dict[str, Any]]] = {
    "review": [
        {"heading": "Overview", "purpose": "High-level product summary and first impressions", "target_words": 200},
        {"heading": "Key Features", "purpose": "Detailed walkthrough of standout features", "target_words": 300},
        {"heading": "Pros and Cons", "purpose": "Balanced assessment of strengths and weaknesses", "target_words": 200},
        {"heading": "Pricing and Value", "purpose": "Cost analysis relative to alternatives", "target_words": 200},
        {"heading": "Who Is It Best For?", "purpose": "Target audience and use-case fit", "target_words": 150},
        {"heading": "Verdict", "purpose": "Final recommendation with CTA", "target_words": 150},
    ],
    "comparison": [
        {"heading": "Quick Comparison", "purpose": "Side-by-side summary table of key specs", "target_words": 150},
        {"heading": "Product A Overview", "purpose": "First product deep-dive", "target_words": 250},
        {"heading": "Product B Overview", "purpose": "Second product deep-dive", "target_words": 250},
        {"heading": "Feature-by-Feature Comparison", "purpose": "Detailed attribute comparison", "target_words": 300},
        {"heading": "Pricing Breakdown", "purpose": "Cost comparison and value analysis", "target_words": 200},
        {"heading": "Which Should You Choose?", "purpose": "Conditional recommendation", "target_words": 150},
    ],
    "roundup": [
        {"heading": "Our Top Picks at a Glance", "purpose": "Summary of all recommendations", "target_words": 200},
        {"heading": "How We Evaluated", "purpose": "Methodology and selection criteria", "target_words": 150},
        {"heading": "Detailed Reviews", "purpose": "Individual mini-reviews for each pick", "target_words": 400},
        {"heading": "Buying Guide", "purpose": "What to look for when choosing", "target_words": 250},
        {"heading": "Frequently Asked Questions", "purpose": "Common buyer questions", "target_words": 200},
    ],
    "how_to": [
        {"heading": "What You Will Need", "purpose": "Prerequisites and tools required", "target_words": 150},
        {"heading": "Step-by-Step Guide", "purpose": "Detailed walkthrough with numbered steps", "target_words": 400},
        {"heading": "Tips for Best Results", "purpose": "Pro tips and common mistakes to avoid", "target_words": 200},
        {"heading": "Recommended Products", "purpose": "Product recommendations with affiliate links", "target_words": 250},
        {"heading": "Frequently Asked Questions", "purpose": "Common questions about the process", "target_words": 150},
    ],
    "buying_guide": [
        {"heading": "What to Look For", "purpose": "Key factors to consider before buying", "target_words": 300},
        {"heading": "Top Recommendations", "purpose": "Curated picks across budget ranges", "target_words": 350},
        {"heading": "Feature Deep Dive", "purpose": "Technical features explained simply", "target_words": 250},
        {"heading": "Budget Considerations", "purpose": "Price tiers and value analysis", "target_words": 200},
        {"heading": "Final Thoughts", "purpose": "Summary recommendation and next steps", "target_words": 150},
    ],
}


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def create_heading_structure(
    content_type: str,
    *,
    primary_keyword: str = "",
    max_sections: int = 10,
) -> List[SectionPlan]:
    """Build a heading hierarchy from a template for the given content type.

    Selects the appropriate section template and converts it into a list
    of :class:`SectionPlan` objects with keyword-enriched headings.

    Parameters
    ----------
    content_type:
        One of ``"review"``, ``"comparison"``, ``"roundup"``,
        ``"how_to"``, or ``"buying_guide"``.
    primary_keyword:
        The target keyword to weave into headings where natural.
    max_sections:
        Maximum number of top-level sections to include.

    Returns
    -------
    list[SectionPlan]
        Ordered list of section blueprints.

    Raises
    ------
    PipelineStepError
        If *content_type* is not recognised.
    """
    template = _SECTION_TEMPLATES.get(content_type)
    if template is None:
        raise PipelineStepError(
            f"Unknown content type: {content_type!r}",
            step_name="outline",
            details={
                "content_type": content_type,
                "supported": list(_SECTION_TEMPLATES.keys()),
            },
        )

    sections: List[SectionPlan] = []
    for entry in template[:max_sections]:
        heading = entry["heading"]
        # Inject keyword into the first heading if it reads naturally
        if primary_keyword and sections == [] and primary_keyword.lower() not in heading.lower():
            heading = f"{heading}: {primary_keyword}"

        sections.append(
            SectionPlan(
                heading=heading,
                heading_level=2,
                purpose=entry.get("purpose", ""),
                target_words=entry.get("target_words", 200),
                keywords=[primary_keyword] if primary_keyword else [],
            )
        )

    return sections


def plan_sections(
    offer_data: Dict[str, Any],
    content_type: str,
    *,
    primary_keyword: str = "",
    secondary_keywords: Optional[List[str]] = None,
    max_sections: int = 10,
) -> List[SectionPlan]:
    """Plan sections tailored to a specific offer and content strategy.

    Extends :func:`create_heading_structure` by injecting offer-specific
    context (merchant name, category, pricing) into section purposes and
    distributing secondary keywords across sections.

    Parameters
    ----------
    offer_data:
        Normalized offer dict containing ``name``, ``merchant``,
        ``category``, and other fields.
    content_type:
        Article type identifier.
    primary_keyword:
        Main SEO target keyword.
    secondary_keywords:
        Additional keywords to distribute across sections.
    max_sections:
        Maximum number of top-level sections.

    Returns
    -------
    list[SectionPlan]
        Section blueprints enriched with offer context.
    """
    sections = create_heading_structure(
        content_type,
        primary_keyword=primary_keyword,
        max_sections=max_sections,
    )

    merchant = offer_data.get("merchant", "")
    product_name = offer_data.get("name", "")
    category = offer_data.get("category", "")

    secondary = secondary_keywords or []

    for idx, section in enumerate(sections):
        # Enrich purpose with offer context
        if merchant and product_name:
            section.notes = f"Focus on {product_name} by {merchant} in the {category} space."

        # Distribute secondary keywords round-robin
        if secondary:
            kw = secondary[idx % len(secondary)]
            if kw not in section.keywords:
                section.keywords.append(kw)

    log_event(
        logger,
        "outline.plan_sections.ok",
        content_type=content_type,
        section_count=len(sections),
        offer=product_name,
    )
    return sections


def estimate_word_count(sections: List[SectionPlan]) -> int:
    """Calculate the total estimated word count from a list of sections.

    Recursively includes subsection targets.

    Parameters
    ----------
    sections:
        List of :class:`SectionPlan` objects.

    Returns
    -------
    int
        Total estimated word count.
    """
    total = 0
    for section in sections:
        total += section.target_words
        if section.subsections:
            total += estimate_word_count(section.subsections)
    return total


def generate_outline(
    offer_data: Dict[str, Any],
    *,
    content_type: str = "review",
    primary_keyword: str = "",
    secondary_keywords: Optional[List[str]] = None,
    max_sections: int = 10,
    target_word_count: int = DEFAULT_TARGET_WORD_COUNT,
) -> ContentOutline:
    """Generate a complete content outline for an affiliate article.

    This is the main entry point for the outline stage.  It selects a
    template, plans sections enriched with offer context, adjusts word
    counts to hit the target, and returns a :class:`ContentOutline`
    ready for the draft stage.

    Parameters
    ----------
    offer_data:
        Normalized and scored offer dict.
    content_type:
        Article type (``"review"``, ``"comparison"``, ``"roundup"``,
        ``"how_to"``, ``"buying_guide"``).
    primary_keyword:
        Main SEO target keyword.  If empty, defaults to
        ``"{merchant} {name} review"``.
    secondary_keywords:
        Supporting keywords.
    max_sections:
        Maximum number of top-level sections (from pipelines.yaml).
    target_word_count:
        Desired total word count for the article.

    Returns
    -------
    ContentOutline
        A fully structured outline ready for the draft stage.

    Raises
    ------
    PipelineStepError
        If the content type is not supported or offer data is missing
        required fields.
    """
    name = offer_data.get("name", "")
    merchant = offer_data.get("merchant", "")

    if not name:
        raise PipelineStepError(
            "Cannot generate outline: offer has no name",
            step_name="outline",
            details={"offer_data_keys": list(offer_data.keys())},
        )

    # Auto-generate primary keyword if not provided
    if not primary_keyword:
        primary_keyword = f"{merchant} {name} review".strip()

    # Generate a working title
    title = _generate_title(name, merchant, content_type, primary_keyword)

    # Plan sections with offer context
    sections = plan_sections(
        offer_data,
        content_type,
        primary_keyword=primary_keyword,
        secondary_keywords=secondary_keywords,
        max_sections=max_sections,
    )

    # Adjust section word counts to hit target
    raw_estimate = estimate_word_count(sections)
    if raw_estimate > 0 and raw_estimate != target_word_count:
        scale_factor = target_word_count / raw_estimate
        for section in sections:
            section.target_words = max(50, int(section.target_words * scale_factor))

    final_estimate = estimate_word_count(sections)

    outline = ContentOutline(
        title=title,
        offer_id=offer_data.get("external_id", offer_data.get("id", "")),
        content_type=content_type,
        primary_keyword=primary_keyword,
        secondary_keywords=secondary_keywords or [],
        sections=sections,
        estimated_words=final_estimate,
        meta_notes=f"Tone: helpful and authoritative. Audience: consumers researching {merchant} products.",
    )

    log_event(
        logger,
        "outline.generate.ok",
        outline_id=outline.outline_id,
        title=title,
        sections=len(sections),
        estimated_words=final_estimate,
    )
    return outline


def _generate_title(
    product_name: str,
    merchant: str,
    content_type: str,
    primary_keyword: str,
) -> str:
    """Generate a working title based on content type and offer info.

    Parameters
    ----------
    product_name:
        The product or offer name.
    merchant:
        The merchant or brand name.
    content_type:
        Article type identifier.
    primary_keyword:
        Primary SEO keyword.

    Returns
    -------
    str
        A working article title.
    """
    year = "2026"  # Updated via config or runtime in production

    templates = {
        "review": f"{product_name} Review ({year}): Is It Worth It?",
        "comparison": f"{product_name} vs Competitors: Which Is Best in {year}?",
        "roundup": f"Best {merchant} Products in {year}: Top Picks Reviewed",
        "how_to": f"How to Get the Most Out of {product_name} ({year} Guide)",
        "buying_guide": f"{product_name} Buying Guide: Everything You Need to Know in {year}",
    }

    return templates.get(content_type, f"{primary_keyword} - Complete Guide ({year})")
