"""
pipelines.publishing.publish_post
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Publish completed article drafts to a CMS (WordPress, headless CMS, or
static site generator).  Handles content formatting, featured image
assignment, category/tag mapping, and affiliate disclosure injection.

Design references:
    - config/pipelines.yaml  ``publishing.steps[1]``  (add_disclosure, add_schema)
    - ARCHITECTURE.md  Section 3 (Publishing Pipeline)
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.core.constants import ContentStatus
from src.core.errors import (
    CMSConnectionError,
    ContentValidationError,
)
from src.core.logger import get_logger, log_event
from src.domains.seo.validator import enforce_seo
from src.pipelines.content.draft import ArticleDraft

logger = get_logger("pipelines.publishing.publish_post")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CMSConfig:
    """Configuration for a CMS connection.

    Attributes
    ----------
    cms_type:
        Type of CMS (``"wordpress"``, ``"ghost"``, ``"static"``,
        ``"headless"``).
    base_url:
        CMS API base URL.
    api_key:
        Authentication key or token.
    username:
        Optional username for basic auth.
    default_author_id:
        Default author ID for new posts.
    default_status:
        Default post status (``"draft"`` or ``"publish"``).
    """

    cms_type: str = "wordpress"
    base_url: str = ""
    api_key: str = ""
    username: str = ""
    default_author_id: int = 1
    default_status: str = "draft"


@dataclass
class PublishResult:
    """Result of publishing an article to the CMS.

    Attributes
    ----------
    post_id:
        The ID assigned by the CMS.
    url:
        The live URL of the published post.
    status:
        Publication status.
    title:
        The published title.
    categories:
        Categories assigned to the post.
    tags:
        Tags assigned to the post.
    featured_image_url:
        URL of the featured image, if set.
    published_at:
        UTC timestamp of publication.
    errors:
        Any errors encountered during publishing.
    """

    post_id: str = ""
    url: str = ""
    status: ContentStatus = ContentStatus.DRAFT
    title: str = ""
    categories: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    featured_image_url: str = ""
    published_at: Optional[datetime] = None
    errors: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Content formatting
# ---------------------------------------------------------------------------

def format_for_cms(
    draft: ArticleDraft,
    *,
    cms_type: str = "wordpress",
    include_disclosure: bool = True,
    include_schema: bool = True,
    schema_markup: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Format an article draft for CMS submission.

    Converts the internal draft structure into the format expected by
    the target CMS API, including HTML formatting, disclosure insertion,
    and schema markup embedding.

    Parameters
    ----------
    draft:
        The article draft to format.
    cms_type:
        Target CMS type for format-specific adjustments.
    include_disclosure:
        Whether to include the FTC affiliate disclosure.
    include_schema:
        Whether to embed JSON-LD schema markup.
    schema_markup:
        Pre-generated schema markup dict from the SEO stage.

    Returns
    -------
    dict[str, Any]
        CMS-ready post payload with keys: ``title``, ``content``,
        ``excerpt``, ``status``, ``slug``.
    """
    # Build HTML content
    parts: List[str] = []

    # Disclosure at the top
    if include_disclosure and draft.disclosure:
        parts.append(f'<div class="affiliate-disclosure"><p><em>{draft.disclosure}</em></p></div>')
        parts.append("")

    # Introduction
    if draft.introduction:
        parts.append(f"<p>{_escape_html(draft.introduction)}</p>")
        parts.append("")

    # Body sections
    for section in draft.sections:
        heading_tag = f"h{section.heading_level}"
        parts.append(f"<{heading_tag}>{_escape_html(section.heading)}</{heading_tag}>")
        # Split body into paragraphs
        paragraphs = [p.strip() for p in section.body.split("\n\n") if p.strip()]
        if not paragraphs:
            paragraphs = [section.body]
        for paragraph in paragraphs:
            parts.append(f"<p>{_escape_html(paragraph)}</p>")
        parts.append("")

    # Conclusion
    if draft.conclusion:
        parts.append("<h2>Final Thoughts</h2>")
        parts.append(f"<p>{_escape_html(draft.conclusion)}</p>")

    # Schema markup
    if include_schema and schema_markup:
        import json
        schema_json = json.dumps(schema_markup, indent=2)
        parts.append(f'<script type="application/ld+json">{schema_json}</script>')

    content = "\n".join(parts)

    # Generate excerpt from introduction
    excerpt = draft.introduction[:160].rstrip() + "..." if len(draft.introduction) > 160 else draft.introduction

    # Generate slug
    slug = _generate_slug(draft.title)

    payload: Dict[str, Any] = {
        "title": draft.title,
        "content": content,
        "excerpt": excerpt,
        "status": "draft",
        "slug": slug,
        "meta": {
            "draft_id": draft.draft_id,
            "outline_id": draft.outline_id,
            "word_count": draft.total_word_count,
        },
    }

    log_event(
        logger,
        "publish.format.ok",
        cms_type=cms_type,
        title=draft.title,
        content_length=len(content),
    )
    return payload


def _escape_html(text: str) -> str:
    """Escape basic HTML special characters in text.

    Parameters
    ----------
    text:
        Raw text to escape.

    Returns
    -------
    str
        HTML-safe text.
    """
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _generate_slug(title: str) -> str:
    """Generate a URL slug from a title.

    Parameters
    ----------
    title:
        Article title.

    Returns
    -------
    str
        Lowercase hyphenated slug.
    """
    slug = re.sub(r'[^\w\s-]', '', title.lower())
    slug = re.sub(r'[\s_]+', '-', slug.strip())
    return slug.strip('-')[:100]


# ---------------------------------------------------------------------------
# Featured image
# ---------------------------------------------------------------------------

def add_featured_image(
    post_payload: Dict[str, Any],
    *,
    image_url: Optional[str] = None,
    image_alt: str = "",
    auto_generate: bool = True,
    offer_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Add a featured image to the CMS post payload.

    If *image_url* is provided directly, it is used.  Otherwise, if
    *auto_generate* is ``True``, a placeholder URL is created based on
    the article's category and title (to be resolved by the image
    pipeline later).

    Parameters
    ----------
    post_payload:
        The CMS-ready post dict to augment.
    image_url:
        Direct URL to a featured image.
    image_alt:
        Alt text for the image.
    auto_generate:
        Whether to generate a placeholder if no URL is given.
    offer_data:
        Offer data for context-based image selection.

    Returns
    -------
    dict[str, Any]
        The augmented post payload with ``featured_image`` key.
    """
    if image_url:
        post_payload["featured_image"] = {
            "url": image_url,
            "alt": image_alt or post_payload.get("title", ""),
        }
    elif auto_generate:
        category = ""
        if offer_data:
            category = offer_data.get("category", "general")
        title = post_payload.get("title", "article")
        placeholder_alt = image_alt or f"Featured image for {title}"

        post_payload["featured_image"] = {
            "url": f"/images/featured/{_generate_slug(title)}.webp",
            "alt": placeholder_alt,
            "auto_generated": True,
            "category": category,
        }

    log_event(
        logger,
        "publish.featured_image.set",
        has_image="featured_image" in post_payload,
    )
    return post_payload


# ---------------------------------------------------------------------------
# Category and tag assignment
# ---------------------------------------------------------------------------

def set_categories_tags(
    post_payload: Dict[str, Any],
    offer_data: Dict[str, Any],
    *,
    category_mapping: Optional[Dict[str, str]] = None,
    extra_tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Assign categories and tags to a post based on offer data.

    Maps offer categories to CMS category slugs and generates relevant
    tags from offer attributes.

    Parameters
    ----------
    post_payload:
        The CMS-ready post dict to augment.
    offer_data:
        Normalized offer dict with ``category``, ``merchant``, ``name``.
    category_mapping:
        Optional mapping from offer categories to CMS category slugs.
    extra_tags:
        Additional tags to include.

    Returns
    -------
    dict[str, Any]
        The augmented post payload with ``categories`` and ``tags``.
    """
    mapping = category_mapping or {}
    offer_category = offer_data.get("category", "uncategorized")

    # Map offer category to CMS category
    cms_category = mapping.get(offer_category, offer_category)
    categories = [cms_category]

    # Generate tags from offer data
    tags: List[str] = []
    merchant = offer_data.get("merchant", "")
    if merchant:
        tags.append(merchant.lower().replace(" ", "-"))

    name = offer_data.get("name", "")
    if name:
        # Extract significant words from the product name
        stop_words = {"the", "a", "an", "and", "or", "for", "in", "on", "at", "to", "of", "is"}
        name_tags = [
            w.lower() for w in name.split()
            if w.lower() not in stop_words and len(w) > 2
        ]
        tags.extend(name_tags[:5])

    if offer_category and offer_category != "uncategorized":
        tags.append(offer_category)

    if extra_tags:
        tags.extend(extra_tags)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_tags: List[str] = []
    for tag in tags:
        if tag not in seen:
            seen.add(tag)
            unique_tags.append(tag)

    post_payload["categories"] = categories
    post_payload["tags"] = unique_tags

    log_event(
        logger,
        "publish.categories_tags.set",
        categories=categories,
        tag_count=len(unique_tags),
    )
    return post_payload


# ---------------------------------------------------------------------------
# Main publishing function
# ---------------------------------------------------------------------------

def publish_to_cms(
    draft: ArticleDraft,
    offer_data: Dict[str, Any],
    *,
    cms_config: Optional[CMSConfig] = None,
    schema_markup: Optional[Dict[str, Any]] = None,
    add_disclosure: bool = True,
    add_schema: bool = True,
    dry_run: bool = False,
) -> PublishResult:
    """Publish a completed article draft to the configured CMS.

    Orchestrates formatting, featured image, categories/tags, and the
    actual CMS API call.  In dry-run mode, all steps except the API
    call are performed and the payload is logged.

    Parameters
    ----------
    draft:
        The article draft to publish.
    offer_data:
        Normalized offer dict for context.
    cms_config:
        CMS connection configuration.  Falls back to defaults.
    schema_markup:
        Pre-generated JSON-LD schema markup.
    add_disclosure:
        Whether to include FTC disclosure.
    add_schema:
        Whether to embed schema markup.
    dry_run:
        If ``True``, prepare but do not submit to the CMS.

    Returns
    -------
    PublishResult
        Summary of the publishing operation.

    Raises
    ------
    CMSConnectionError
        If the CMS cannot be reached.
    ContentValidationError
        If the draft fails pre-publish validation.
    DuplicateContentError
        If similar content already exists on the site.
    """
    config = cms_config or CMSConfig()

    log_event(
        logger,
        "publish.start",
        title=draft.title,
        cms_type=config.cms_type,
        dry_run=dry_run,
    )

    # Validate before publishing
    _validate_draft(draft)

    # Enforce OpenClaw SEO structural requirements
    # Assembles full article text and checks for: TLDR block, comparison
    # table, FAQ section, minimum internal links, verdict statements.
    # Raises ContentValidationError if any required block is missing.
    full_text = draft.introduction + "\n"
    for section in draft.sections:
        full_text += f"## {section.heading}\n{section.body}\n"
    full_text += draft.conclusion
    enforce_seo(full_text)

    # Format for CMS
    payload = format_for_cms(
        draft,
        cms_type=config.cms_type,
        include_disclosure=add_disclosure,
        include_schema=add_schema,
        schema_markup=schema_markup,
    )

    # Add featured image
    payload = add_featured_image(payload, offer_data=offer_data)

    # Set categories and tags
    payload = set_categories_tags(payload, offer_data)

    result = PublishResult(
        title=draft.title,
        categories=payload.get("categories", []),
        tags=payload.get("tags", []),
    )

    if dry_run:
        result.status = ContentStatus.DRAFT
        result.post_id = f"dry-run-{uuid.uuid4().hex[:8]}"
        log_event(
            logger,
            "publish.dry_run",
            title=draft.title,
            payload_size=len(str(payload)),
        )
        return result

    # Submit to CMS
    try:
        post_id, post_url = _submit_to_cms(payload, config)
        result.post_id = post_id
        result.url = post_url
        result.status = ContentStatus.PUBLISHED
        result.published_at = datetime.now(timezone.utc)
    except Exception as exc:
        result.errors.append(str(exc))
        result.status = ContentStatus.DRAFT
        raise CMSConnectionError(
            f"Failed to publish '{draft.title}' to {config.cms_type}",
            details={"title": draft.title, "cms_type": config.cms_type},
            cause=exc,
        ) from exc

    log_event(
        logger,
        "publish.complete",
        post_id=result.post_id,
        url=result.url,
        status=result.status.value,
    )
    return result


def _validate_draft(draft: ArticleDraft) -> None:
    """Run pre-publish validation checks on a draft.

    Parameters
    ----------
    draft:
        The draft to validate.

    Raises
    ------
    ContentValidationError
        If the draft fails any validation check.
    """
    issues: List[str] = []

    if not draft.title:
        issues.append("Article has no title.")
    if draft.total_word_count < 100:
        issues.append(f"Word count ({draft.total_word_count}) is below minimum threshold.")
    if not draft.sections:
        issues.append("Article has no content sections.")
    if not draft.disclosure:
        issues.append("FTC affiliate disclosure is missing.")

    if issues:
        raise ContentValidationError(
            f"Draft validation failed: {len(issues)} issue(s)",
            details={"title": draft.title, "issues": issues},
        )


def _submit_to_cms(
    payload: Dict[str, Any],
    config: CMSConfig,
) -> tuple[str, str]:
    """Submit the formatted payload to the CMS API.

    Uses CMSTool for WordPress REST API integration.  Falls back to a
    stub response when api_key is not configured (local dev).

    Parameters
    ----------
    payload:
        CMS-ready post payload.
    config:
        CMS connection configuration.

    Returns
    -------
    tuple[str, str]
        (post_id, post_url) from the CMS response.
    """
    # If CMS credentials are configured, use real integration
    if config.base_url and config.api_key:
        from src.agents.tools.cms_tool import CMSTool

        cms = CMSTool({
            "cms_type": config.cms_type,
            "api_base_url": config.base_url,
            "api_key": config.api_key,
            "username": config.username,
            "default_status": config.default_status,
        })

        post_data = {
            "title": payload.get("title", ""),
            "content": payload.get("content", ""),
            "excerpt": payload.get("excerpt", ""),
            "status": payload.get("status", config.default_status),
            "slug": payload.get("slug", ""),
        }

        result = cms.create_post(post_data)
        post_id = str(result.get("id", ""))
        post_url = result.get("url", "")

        logger.info(
            "Published to %s CMS via API: %s -> %s",
            config.cms_type, post_id, post_url,
        )
        return post_id, post_url

    # Fallback: no credentials configured (local dev / dry-run-like)
    post_id = uuid.uuid4().hex[:12]
    slug = payload.get("slug", "post")
    base = config.base_url.rstrip("/") if config.base_url else "https://example.com"
    post_url = f"{base}/{slug}/"

    logger.info("Submitted post to %s CMS (stub): %s -> %s", config.cms_type, post_id, post_url)
    return post_id, post_url
