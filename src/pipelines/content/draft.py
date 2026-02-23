"""
pipelines.content.draft
~~~~~~~~~~~~~~~~~~~~~~~~

Generate article drafts from structured content outlines.  Each section
of the outline is expanded into prose, then assembled into a cohesive
article with proper disclosure statements, internal structure, and
affiliate link placeholders.

The draft stage relies on an LLM provider (configured in
``config/pipelines.yaml`` under ``content.steps[1]``) for prose
generation, with fallback stub content when no provider is available.

Design references:
    - config/pipelines.yaml  ``content.steps[1]``  (llm_provider, max_tokens)
    - ARCHITECTURE.md  Section 3 (Content Pipeline)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.core.errors import PipelineStepError
from src.core.logger import get_logger, log_event
from src.pipelines.content.outline import ContentOutline, SectionPlan

logger = get_logger("pipelines.content.draft")


# ---------------------------------------------------------------------------
# FTC disclosure templates
# ---------------------------------------------------------------------------

_FTC_DISCLOSURE_SHORT = (
    "This article contains affiliate links. If you make a purchase through "
    "these links, we may earn a commission at no additional cost to you."
)

_FTC_DISCLOSURE_FULL = (
    "Disclosure: This content is reader-supported. When you buy through "
    "affiliate links on this page, we may earn a commission. This does not "
    "influence our editorial opinions or ratings. All opinions expressed are "
    "our own and are based on our independent research and analysis."
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SectionDraft:
    """A single drafted section of the article.

    Attributes
    ----------
    heading:
        Section heading text.
    heading_level:
        HTML heading level (2, 3, etc.).
    body:
        The drafted prose content.
    word_count:
        Actual word count of the body.
    keywords_used:
        Keywords that appear in this section.
    """

    heading: str
    heading_level: int = 2
    body: str = ""
    word_count: int = 0
    keywords_used: List[str] = field(default_factory=list)


@dataclass
class ArticleDraft:
    """Complete first draft of an affiliate article.

    Attributes
    ----------
    draft_id:
        Unique identifier for this draft.
    outline_id:
        The outline this draft was generated from.
    title:
        Article title.
    disclosure:
        FTC affiliate disclosure statement.
    introduction:
        Opening paragraph(s).
    sections:
        Ordered list of :class:`SectionDraft` objects.
    conclusion:
        Closing paragraph(s).
    total_word_count:
        Sum of all section word counts plus intro and conclusion.
    created_at:
        UTC timestamp of draft creation.
    metadata:
        Extra context (LLM model used, token counts, etc.).
    """

    title: str
    outline_id: str
    disclosure: str = ""
    introduction: str = ""
    sections: List[SectionDraft] = field(default_factory=list)
    conclusion: str = ""
    total_word_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)
    draft_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


# ---------------------------------------------------------------------------
# Section writing
# ---------------------------------------------------------------------------

def write_section(
    section_plan: SectionPlan,
    offer_data: Dict[str, Any],
    *,
    llm_provider: Optional[Any] = None,
    max_tokens: int = 4096,
) -> SectionDraft:
    """Draft a single section based on its :class:`SectionPlan`.

    If an *llm_provider* is available, it is called with a structured
    prompt.  Otherwise a template-based stub is generated so the
    pipeline remains functional during development.

    Parameters
    ----------
    section_plan:
        The blueprint for this section (heading, purpose, target words,
        keywords).
    offer_data:
        Normalized offer dict providing product context.
    llm_provider:
        Optional LLM client with a ``generate(prompt, max_tokens)``
        method.  When ``None``, a stub draft is produced.
    max_tokens:
        Maximum tokens for the LLM response.

    Returns
    -------
    SectionDraft
        The drafted section content.
    """
    product_name = offer_data.get("name", "the product")
    merchant = offer_data.get("merchant", "the brand")
    keywords = section_plan.keywords

    if llm_provider is not None:
        prompt = _build_section_prompt(section_plan, offer_data)
        try:
            body = llm_provider.generate(prompt, max_tokens=max_tokens)
        except Exception as exc:
            logger.warning(
                "LLM generation failed for section '%s': %s -- falling back to stub",
                section_plan.heading,
                exc,
            )
            body = _generate_stub_section(section_plan, product_name, merchant)
    else:
        body = _generate_stub_section(section_plan, product_name, merchant)

    word_count = len(body.split())
    keywords_used = [kw for kw in keywords if kw.lower() in body.lower()]

    draft = SectionDraft(
        heading=section_plan.heading,
        heading_level=section_plan.heading_level,
        body=body,
        word_count=word_count,
        keywords_used=keywords_used,
    )

    log_event(
        logger,
        "draft.section.ok",
        heading=section_plan.heading,
        word_count=word_count,
        keywords_found=len(keywords_used),
    )
    return draft


def _build_section_prompt(
    section_plan: SectionPlan,
    offer_data: Dict[str, Any],
) -> str:
    """Construct an LLM prompt for drafting a section.

    Parameters
    ----------
    section_plan:
        The section blueprint.
    offer_data:
        Product/offer context.

    Returns
    -------
    str
        A structured prompt string.
    """
    keywords_str = ", ".join(section_plan.keywords) if section_plan.keywords else "none specified"

    return (
        f"Write a {section_plan.target_words}-word section for an affiliate article.\n\n"
        f"Section heading: {section_plan.heading}\n"
        f"Section purpose: {section_plan.purpose}\n"
        f"Product: {offer_data.get('name', 'N/A')}\n"
        f"Brand: {offer_data.get('merchant', 'N/A')}\n"
        f"Category: {offer_data.get('category', 'N/A')}\n"
        f"Commission rate: {offer_data.get('commission_rate', 0)}\n"
        f"Average order value: ${offer_data.get('avg_order_value', 0):.2f}\n"
        f"Keywords to include: {keywords_str}\n"
        f"Notes: {section_plan.notes}\n\n"
        f"Guidelines:\n"
        f"- Write in an informative, helpful tone\n"
        f"- Be specific and evidence-based\n"
        f"- Naturally incorporate the keywords\n"
        f"- Do not use hyperbolic language\n"
        f"- Include a call-to-action where appropriate\n"
    )


def _generate_stub_section(
    section_plan: SectionPlan,
    product_name: str,
    merchant: str,
) -> str:
    """Generate template-based stub content when no LLM is available.

    Parameters
    ----------
    section_plan:
        The section blueprint.
    product_name:
        Name of the product being reviewed.
    merchant:
        Brand or merchant name.

    Returns
    -------
    str
        Placeholder prose for this section.
    """
    purpose = section_plan.purpose or "general discussion"
    keywords_mention = ""
    if section_plan.keywords:
        keywords_mention = f" Key topics include {', '.join(section_plan.keywords)}."

    return (
        f"This section covers {purpose} for {product_name} by {merchant}. "
        f"Our analysis is based on thorough research of the product's features, "
        f"user feedback, and competitive positioning in the market.{keywords_mention} "
        f"[Content to be expanded by LLM provider during production runs.]"
    )


# ---------------------------------------------------------------------------
# Disclosure handling
# ---------------------------------------------------------------------------

def add_disclosure(
    *,
    full_disclosure: bool = True,
) -> str:
    """Return the appropriate FTC affiliate disclosure statement.

    Parameters
    ----------
    full_disclosure:
        When ``True``, returns the detailed disclosure.  When ``False``,
        returns a shorter version suitable for sidebar placement.

    Returns
    -------
    str
        The disclosure text.
    """
    return _FTC_DISCLOSURE_FULL if full_disclosure else _FTC_DISCLOSURE_SHORT


# ---------------------------------------------------------------------------
# Article assembly
# ---------------------------------------------------------------------------

def assemble_article(
    sections: List[SectionDraft],
    *,
    title: str,
    outline_id: str,
    offer_data: Dict[str, Any],
    include_disclosure: bool = True,
) -> ArticleDraft:
    """Assemble individual section drafts into a complete article.

    Generates an introduction and conclusion that bookend the drafted
    sections, adds the FTC disclosure, and computes the total word count.

    Parameters
    ----------
    sections:
        Ordered list of :class:`SectionDraft` objects.
    title:
        Article title.
    outline_id:
        ID of the outline this draft is based on.
    offer_data:
        Normalized offer dict for context.
    include_disclosure:
        Whether to prepend an FTC affiliate disclosure.

    Returns
    -------
    ArticleDraft
        The fully assembled first draft.
    """
    product_name = offer_data.get("name", "the product")
    merchant = offer_data.get("merchant", "the brand")
    category = offer_data.get("category", "its category")

    # Generate introduction
    introduction = (
        f"Looking for an honest assessment of {product_name} by {merchant}? "
        f"In this comprehensive guide, we break down everything you need to know "
        f"about this {category} product, including features, pricing, pros and cons, "
        f"and whether it is the right choice for you."
    )

    # Generate conclusion
    conclusion = (
        f"After thorough research and analysis, {product_name} by {merchant} "
        f"stands as a noteworthy option in the {category} space. "
        f"We recommend evaluating your specific needs against the features "
        f"and pricing outlined above to determine if it is the right fit. "
        f"If you decide to purchase, using the links in this article helps "
        f"support our independent research at no extra cost to you."
    )

    disclosure = add_disclosure(full_disclosure=True) if include_disclosure else ""

    # Calculate total word count
    intro_words = len(introduction.split())
    conclusion_words = len(conclusion.split())
    section_words = sum(s.word_count for s in sections)
    total = intro_words + section_words + conclusion_words

    draft = ArticleDraft(
        title=title,
        outline_id=outline_id,
        disclosure=disclosure,
        introduction=introduction,
        sections=sections,
        conclusion=conclusion,
        total_word_count=total,
        metadata={
            "offer_id": offer_data.get("external_id", ""),
            "offer_name": product_name,
            "merchant": merchant,
        },
    )

    log_event(
        logger,
        "draft.assemble.ok",
        draft_id=draft.draft_id,
        title=title,
        total_words=total,
        section_count=len(sections),
    )
    return draft


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_draft(
    outline: ContentOutline,
    offer_data: Dict[str, Any],
    *,
    llm_provider: Optional[Any] = None,
    max_tokens: int = 4096,
    include_disclosure: bool = True,
) -> ArticleDraft:
    """Generate a complete article draft from an outline and offer data.

    This is the main entry point for the draft stage.  It iterates
    through each section in the outline, generates prose, and assembles
    the final article.

    Parameters
    ----------
    outline:
        A :class:`ContentOutline` from the outline stage.
    offer_data:
        Normalized and scored offer dict.
    llm_provider:
        Optional LLM client for prose generation.
    max_tokens:
        Maximum tokens per LLM call.
    include_disclosure:
        Whether to include the FTC affiliate disclosure.

    Returns
    -------
    ArticleDraft
        The complete first draft.

    Raises
    ------
    PipelineStepError
        If the outline has no sections or a critical section fails to
        draft.
    """
    if not outline.sections:
        raise PipelineStepError(
            "Cannot generate draft: outline has no sections",
            step_name="draft",
            details={"outline_id": outline.outline_id},
        )

    log_event(
        logger,
        "draft.generate.start",
        outline_id=outline.outline_id,
        section_count=len(outline.sections),
    )

    section_drafts: List[SectionDraft] = []
    for section_plan in outline.sections:
        try:
            draft_section = write_section(
                section_plan,
                offer_data,
                llm_provider=llm_provider,
                max_tokens=max_tokens,
            )
            section_drafts.append(draft_section)
        except Exception as exc:
            logger.error(
                "Failed to draft section '%s': %s", section_plan.heading, exc
            )
            # Insert a placeholder so the article structure remains intact
            section_drafts.append(
                SectionDraft(
                    heading=section_plan.heading,
                    heading_level=section_plan.heading_level,
                    body=f"[Draft generation failed for this section: {exc}]",
                    word_count=0,
                )
            )

    article = assemble_article(
        section_drafts,
        title=outline.title,
        outline_id=outline.outline_id,
        offer_data=offer_data,
        include_disclosure=include_disclosure,
    )

    log_event(
        logger,
        "draft.generate.ok",
        draft_id=article.draft_id,
        total_words=article.total_word_count,
    )
    return article
