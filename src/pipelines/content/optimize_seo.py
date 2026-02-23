"""
pipelines.content.optimize_seo
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Optimize article drafts for search engine visibility.  Covers title tags,
meta descriptions, keyword density, heading structure, and structured
data (JSON-LD schema markup).

The SEO optimization stage runs after drafting and before publishing,
applying rules derived from ``config/pipelines.yaml`` under
``content.steps[2]`` (target_keyword_density).

Design references:
    - config/pipelines.yaml  ``content.steps[2]``
    - ARCHITECTURE.md  Section 3 (Content Pipeline)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List

from src.core.constants import DEFAULT_KEYWORD_DENSITY
from src.core.logger import get_logger, log_event
from src.pipelines.content.draft import ArticleDraft

logger = get_logger("pipelines.content.optimize_seo")


# ---------------------------------------------------------------------------
# SEO constraints
# ---------------------------------------------------------------------------

TITLE_MAX_LENGTH = 60
TITLE_MIN_LENGTH = 25
META_DESCRIPTION_MAX_LENGTH = 160
META_DESCRIPTION_MIN_LENGTH = 70
HEADING_MAX_LENGTH = 80


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SEOReport:
    """Results of SEO optimization applied to an article draft.

    Attributes
    ----------
    title_tag:
        Optimized title tag.
    meta_description:
        Optimized meta description.
    keyword_density:
        Measured keyword density as a decimal fraction.
    density_target:
        Target density from configuration.
    density_ok:
        Whether density is within acceptable range.
    heading_issues:
        List of heading-level problems found.
    schema_markup:
        JSON-LD schema markup dict.
    suggestions:
        List of actionable SEO improvement suggestions.
    score:
        Overall SEO readiness score (0-100).
    """

    title_tag: str = ""
    meta_description: str = ""
    keyword_density: float = 0.0
    density_target: float = DEFAULT_KEYWORD_DENSITY
    density_ok: bool = False
    heading_issues: List[str] = field(default_factory=list)
    schema_markup: Dict[str, Any] = field(default_factory=dict)
    suggestions: List[str] = field(default_factory=list)
    score: int = 0


# ---------------------------------------------------------------------------
# Title optimization
# ---------------------------------------------------------------------------

def optimize_title(
    title: str,
    primary_keyword: str,
    *,
    max_length: int = TITLE_MAX_LENGTH,
) -> str:
    """Optimize an article title for search engine display.

    Ensures the primary keyword appears near the front, the title fits
    within SERP display limits, and power words are preserved.

    Parameters
    ----------
    title:
        The working title from the draft stage.
    primary_keyword:
        The main target keyword.
    max_length:
        Maximum character length for the title tag.

    Returns
    -------
    str
        The optimized title tag.
    """
    # Ensure keyword is present
    if primary_keyword.lower() not in title.lower():
        title = f"{primary_keyword} - {title}"

    # Truncate to max length at a word boundary
    if len(title) > max_length:
        truncated = title[:max_length]
        last_space = truncated.rfind(" ")
        if last_space > max_length * 0.6:
            title = truncated[:last_space]
        else:
            title = truncated

    # Strip trailing punctuation artifacts from truncation
    title = title.rstrip(" -:|")

    log_event(logger, "seo.title.optimized", length=len(title))
    return title


# ---------------------------------------------------------------------------
# Meta description optimization
# ---------------------------------------------------------------------------

def optimize_meta_description(
    article_intro: str,
    primary_keyword: str,
    *,
    max_length: int = META_DESCRIPTION_MAX_LENGTH,
    include_cta: bool = True,
) -> str:
    """Generate an optimized meta description from the article introduction.

    Extracts the most relevant sentence, ensures keyword inclusion, and
    appends a call-to-action if space permits.

    Parameters
    ----------
    article_intro:
        The article's introduction paragraph.
    primary_keyword:
        The target keyword to include.
    max_length:
        Maximum character length.
    include_cta:
        Whether to append a CTA phrase.

    Returns
    -------
    str
        The optimized meta description.
    """
    # Split into sentences and pick the best one
    sentences = re.split(r'(?<=[.!?])\s+', article_intro.strip())
    best_sentence = ""

    # Prefer a sentence that contains the keyword
    for sentence in sentences:
        if primary_keyword.lower() in sentence.lower():
            best_sentence = sentence
            break
    if not best_sentence and sentences:
        best_sentence = sentences[0]

    # Ensure keyword presence
    if primary_keyword.lower() not in best_sentence.lower():
        best_sentence = f"Discover {primary_keyword}. {best_sentence}"

    # Add CTA if space allows
    cta = " Read our complete guide."
    if include_cta and len(best_sentence) + len(cta) <= max_length:
        best_sentence += cta

    # Truncate at word boundary
    if len(best_sentence) > max_length:
        truncated = best_sentence[:max_length]
        last_space = truncated.rfind(" ")
        if last_space > max_length * 0.5:
            best_sentence = truncated[:last_space].rstrip(".,;:") + "..."
        else:
            best_sentence = truncated.rstrip(".,;:") + "..."

    log_event(logger, "seo.meta_description.optimized", length=len(best_sentence))
    return best_sentence


# ---------------------------------------------------------------------------
# Keyword density analysis
# ---------------------------------------------------------------------------

def check_keyword_density(
    text: str,
    primary_keyword: str,
    *,
    target_density: float = DEFAULT_KEYWORD_DENSITY,
    tolerance: float = 0.005,
) -> Dict[str, Any]:
    """Measure keyword density and compare against the target.

    Keyword density = (keyword occurrences * keyword word count) / total words.
    An acceptable range is ``target +/- tolerance``.

    Parameters
    ----------
    text:
        The full article text (all sections concatenated).
    primary_keyword:
        The keyword to measure.
    target_density:
        Desired density as a decimal (e.g. ``0.015`` for 1.5%).
    tolerance:
        Acceptable deviation from target.

    Returns
    -------
    dict[str, Any]
        Analysis dict with keys: ``keyword``, ``occurrences``,
        ``total_words``, ``density``, ``target``, ``within_range``,
        ``recommendation``.
    """
    words = text.lower().split()
    total_words = len(words)

    if total_words == 0:
        return {
            "keyword": primary_keyword,
            "occurrences": 0,
            "total_words": 0,
            "density": 0.0,
            "target": target_density,
            "within_range": False,
            "recommendation": "Article has no content.",
        }

    # Count keyword occurrences (case-insensitive, as a phrase)
    keyword_lower = primary_keyword.lower()
    text_lower = text.lower()
    occurrences = text_lower.count(keyword_lower)
    keyword_word_count = len(keyword_lower.split())
    density = (occurrences * keyword_word_count) / total_words

    within_range = abs(density - target_density) <= tolerance

    if density < target_density - tolerance:
        recommendation = (
            f"Keyword density ({density:.3f}) is below target ({target_density:.3f}). "
            f"Add {_estimate_insertions_needed(density, target_density, total_words, keyword_word_count)} "
            f"more mentions of '{primary_keyword}'."
        )
    elif density > target_density + tolerance:
        recommendation = (
            f"Keyword density ({density:.3f}) exceeds target ({target_density:.3f}). "
            f"Consider reducing mentions to avoid keyword stuffing."
        )
    else:
        recommendation = f"Keyword density ({density:.3f}) is within acceptable range."

    result = {
        "keyword": primary_keyword,
        "occurrences": occurrences,
        "total_words": total_words,
        "density": round(density, 4),
        "target": target_density,
        "within_range": within_range,
        "recommendation": recommendation,
    }

    log_event(
        logger,
        "seo.keyword_density.checked",
        density=round(density, 4),
        target=target_density,
        within_range=within_range,
    )
    return result


def _estimate_insertions_needed(
    current_density: float,
    target_density: float,
    total_words: int,
    keyword_word_count: int,
) -> int:
    """Estimate how many additional keyword mentions are needed to reach target density.

    Parameters
    ----------
    current_density:
        Current keyword density.
    target_density:
        Target density.
    total_words:
        Total word count of the article.
    keyword_word_count:
        Number of words in the keyword phrase.

    Returns
    -------
    int
        Estimated additional mentions needed.
    """
    if keyword_word_count == 0:
        return 0
    current_mentions = (current_density * total_words) / keyword_word_count
    target_mentions = (target_density * total_words) / keyword_word_count
    return max(0, int(target_mentions - current_mentions) + 1)


# ---------------------------------------------------------------------------
# Heading optimization
# ---------------------------------------------------------------------------

def optimize_headings(
    draft: ArticleDraft,
    primary_keyword: str,
) -> List[str]:
    """Analyze and optimize heading structure for SEO.

    Checks for:
    - Proper heading hierarchy (no skipped levels)
    - Keyword presence in at least one heading
    - Heading length within SERP-friendly limits
    - Unique headings (no duplicates)

    Parameters
    ----------
    draft:
        The article draft with sections.
    primary_keyword:
        The target keyword.

    Returns
    -------
    list[str]
        List of issues and suggestions.  An empty list means headings
        are well-optimized.
    """
    issues: List[str] = []
    headings = [(s.heading, s.heading_level) for s in draft.sections]
    keyword_lower = primary_keyword.lower()

    if not headings:
        issues.append("Article has no headings.")
        return issues

    # Check for keyword in at least one heading
    keyword_in_heading = any(keyword_lower in h.lower() for h, _ in headings)
    if not keyword_in_heading:
        issues.append(
            f"Primary keyword '{primary_keyword}' not found in any heading. "
            f"Consider adding it to an H2."
        )

    # Check heading hierarchy (no skipped levels)
    prev_level = 1  # H1 is the title
    for heading, level in headings:
        if level > prev_level + 1:
            issues.append(
                f"Heading '{heading}' (H{level}) skips a level after H{prev_level}. "
                f"Use H{prev_level + 1} instead."
            )
        prev_level = level

    # Check heading lengths
    for heading, level in headings:
        if len(heading) > HEADING_MAX_LENGTH:
            issues.append(
                f"Heading '{heading[:40]}...' (H{level}) exceeds {HEADING_MAX_LENGTH} chars. "
                f"Consider shortening."
            )

    # Check for duplicate headings
    seen_headings: Dict[str, int] = {}
    for heading, _ in headings:
        normalized = heading.lower().strip()
        seen_headings[normalized] = seen_headings.get(normalized, 0) + 1
    for heading_text, count in seen_headings.items():
        if count > 1:
            issues.append(f"Duplicate heading found: '{heading_text}' appears {count} times.")

    log_event(
        logger,
        "seo.headings.analyzed",
        heading_count=len(headings),
        issues_found=len(issues),
    )
    return issues


# ---------------------------------------------------------------------------
# Schema markup
# ---------------------------------------------------------------------------

def add_schema_markup(
    draft: ArticleDraft,
    offer_data: Dict[str, Any],
    *,
    site_url: str = "",
    author_name: str = "Editorial Team",
) -> Dict[str, Any]:
    """Generate JSON-LD structured data for the article.

    Produces an ``Article`` schema with ``Review`` and ``Product``
    annotations, suitable for rich snippet eligibility in Google.

    Parameters
    ----------
    draft:
        The article draft.
    offer_data:
        Normalized offer dict.
    site_url:
        Base URL of the publishing site.
    author_name:
        Author name for the Article schema.

    Returns
    -------
    dict[str, Any]
        JSON-LD structured data dict ready for ``<script>`` injection.
    """
    product_name = offer_data.get("name", "")
    merchant = offer_data.get("merchant", "")
    category = offer_data.get("category", "")
    url = offer_data.get("url", "")

    schema: Dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": draft.title,
        "author": {
            "@type": "Organization",
            "name": author_name,
        },
        "datePublished": draft.created_at.strftime("%Y-%m-%d"),
        "dateModified": draft.created_at.strftime("%Y-%m-%d"),
        "wordCount": draft.total_word_count,
        "articleSection": category,
    }

    if site_url:
        schema["url"] = f"{site_url.rstrip('/')}/{_slugify(draft.title)}"
        schema["publisher"] = {
            "@type": "Organization",
            "name": author_name,
            "url": site_url,
        }

    # Add product review markup
    if product_name:
        schema["about"] = {
            "@type": "Product",
            "name": product_name,
            "brand": {
                "@type": "Brand",
                "name": merchant,
            },
            "category": category,
        }
        if url:
            schema["about"]["url"] = url

    log_event(
        logger,
        "seo.schema.generated",
        schema_type=schema["@type"],
        has_product="about" in schema,
    )
    return schema


def _slugify(text: str) -> str:
    """Convert a title to a URL-friendly slug.

    Parameters
    ----------
    text:
        The text to slugify.

    Returns
    -------
    str
        Lowercase, hyphen-separated slug.
    """
    slug = re.sub(r'[^\w\s-]', '', text.lower())
    slug = re.sub(r'[\s_]+', '-', slug)
    return slug.strip('-')


# ---------------------------------------------------------------------------
# Main optimization pipeline
# ---------------------------------------------------------------------------

def optimize_seo(
    draft: ArticleDraft,
    offer_data: Dict[str, Any],
    primary_keyword: str,
    *,
    target_keyword_density: float = DEFAULT_KEYWORD_DENSITY,
    site_url: str = "",
    author_name: str = "Editorial Team",
) -> SEOReport:
    """Run all SEO optimizations on an article draft.

    Orchestrates title, meta description, keyword density, heading, and
    schema markup optimizations into a single :class:`SEOReport`.

    Parameters
    ----------
    draft:
        The article draft to optimize.
    offer_data:
        Normalized offer dict.
    primary_keyword:
        The main target keyword.
    target_keyword_density:
        Desired keyword density (from pipelines.yaml).
    site_url:
        Base URL of the publishing site.
    author_name:
        Author attribution for schema markup.

    Returns
    -------
    SEOReport
        Comprehensive SEO analysis and optimizations.
    """
    log_event(logger, "seo.optimize.start", draft_id=draft.draft_id)

    # Assemble full text for density analysis
    full_text = draft.introduction + " "
    for section in draft.sections:
        full_text += section.body + " "
    full_text += draft.conclusion

    # Optimize title
    title_tag = optimize_title(draft.title, primary_keyword)

    # Optimize meta description
    meta_description = optimize_meta_description(draft.introduction, primary_keyword)

    # Check keyword density
    density_result = check_keyword_density(
        full_text,
        primary_keyword,
        target_density=target_keyword_density,
    )

    # Optimize headings
    heading_issues = optimize_headings(draft, primary_keyword)

    # Generate schema markup
    schema = add_schema_markup(
        draft,
        offer_data,
        site_url=site_url,
        author_name=author_name,
    )

    # Build suggestions list
    suggestions: List[str] = []
    if not density_result["within_range"]:
        suggestions.append(density_result["recommendation"])
    suggestions.extend(heading_issues)
    if len(title_tag) < TITLE_MIN_LENGTH:
        suggestions.append(f"Title tag is short ({len(title_tag)} chars). Aim for {TITLE_MIN_LENGTH}-{TITLE_MAX_LENGTH}.")
    if len(meta_description) < META_DESCRIPTION_MIN_LENGTH:
        suggestions.append(f"Meta description is short ({len(meta_description)} chars). Aim for {META_DESCRIPTION_MIN_LENGTH}-{META_DESCRIPTION_MAX_LENGTH}.")

    # Calculate SEO score
    score = _calculate_seo_score(
        title_tag=title_tag,
        meta_description=meta_description,
        density_ok=density_result["within_range"],
        heading_issues=heading_issues,
        has_schema=bool(schema),
        primary_keyword=primary_keyword,
    )

    report = SEOReport(
        title_tag=title_tag,
        meta_description=meta_description,
        keyword_density=density_result["density"],
        density_target=target_keyword_density,
        density_ok=density_result["within_range"],
        heading_issues=heading_issues,
        schema_markup=schema,
        suggestions=suggestions,
        score=score,
    )

    log_event(
        logger,
        "seo.optimize.ok",
        draft_id=draft.draft_id,
        seo_score=score,
        suggestions_count=len(suggestions),
    )
    return report


def _calculate_seo_score(
    *,
    title_tag: str,
    meta_description: str,
    density_ok: bool,
    heading_issues: List[str],
    has_schema: bool,
    primary_keyword: str,
) -> int:
    """Calculate an overall SEO readiness score (0-100).

    Parameters
    ----------
    title_tag:
        The optimized title tag.
    meta_description:
        The optimized meta description.
    density_ok:
        Whether keyword density is within range.
    heading_issues:
        List of heading problems.
    has_schema:
        Whether schema markup was generated.
    primary_keyword:
        The target keyword.

    Returns
    -------
    int
        SEO score between 0 and 100.
    """
    score = 0

    # Title tag scoring (0-25)
    if title_tag:
        score += 10
        if TITLE_MIN_LENGTH <= len(title_tag) <= TITLE_MAX_LENGTH:
            score += 10
        if primary_keyword.lower() in title_tag.lower():
            score += 5

    # Meta description scoring (0-20)
    if meta_description:
        score += 10
        if META_DESCRIPTION_MIN_LENGTH <= len(meta_description) <= META_DESCRIPTION_MAX_LENGTH:
            score += 5
        if primary_keyword.lower() in meta_description.lower():
            score += 5

    # Keyword density scoring (0-20)
    if density_ok:
        score += 20
    else:
        score += 5  # partial credit for having measured it

    # Heading structure scoring (0-20)
    if len(heading_issues) == 0:
        score += 20
    elif len(heading_issues) <= 2:
        score += 10
    else:
        score += 5

    # Schema markup scoring (0-15)
    if has_schema:
        score += 15

    return min(score, 100)
