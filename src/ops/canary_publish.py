"""
ops.canary_publish
~~~~~~~~~~~~~~~~~~

One-shot canary publish: build a minimal SEO-valid article and push it to
WordPress staging as a draft.  Used to prove the real CMS integration works
end-to-end before enabling the full automated pipeline.

Usage (CLI):
    python -m src.cli publish-canary --staging --title "My Canary Post"

Usage (Python):
    from src.ops.canary_publish import run_canary_publish
    result = run_canary_publish(staging=True, title="My Canary Post")
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from src.core.errors import (
    CMSConnectionError,
    ConfigError,
)
from src.core.logger import get_logger, log_event
from src.domains.seo.validator import enforce_seo
from src.pipelines.content.draft import ArticleDraft, SectionDraft
from src.pipelines.publishing.publish_post import CMSConfig

logger = get_logger("ops.canary_publish")

# ---------------------------------------------------------------------------
# Safety gates
# ---------------------------------------------------------------------------

_CANARY_TITLE_PREFIX = "[CANARY]"


def _check_safety_gates(staging: bool) -> None:
    """Validate environment before allowing a canary publish.

    Raises ConfigError if any gate fails.
    """
    allow_publishing = os.environ.get("ALLOW_PUBLISHING", "false").lower()
    if allow_publishing != "true":
        raise ConfigError(
            "ALLOW_PUBLISHING is not 'true'. "
            "Set ALLOW_PUBLISHING=true in .env to enable canary publishing.",
        )

    if staging:
        staging_only = os.environ.get("STAGING_ONLY", "true").lower()
        if staging_only != "true":
            raise ConfigError(
                "STAGING_ONLY must be 'true' when using --staging. "
                "Set STAGING_ONLY=true in .env.",
            )

    # Check kill switch
    from pathlib import Path

    ks_file = Path("data/.kill_switch")
    if ks_file.exists():
        raise ConfigError(
            "Kill switch is engaged. Disengage with "
            "'python -m src.cli kill-switch --disengage' before publishing.",
        )


# ---------------------------------------------------------------------------
# Env → CMSConfig mapper
# ---------------------------------------------------------------------------


def get_staging_wp_config_from_env() -> CMSConfig:
    """Read WordPress staging credentials from environment and return a CMSConfig.

    Required env vars:
        WP_STAGING_BASE_URL   — e.g. https://staging.example.com
        WP_STAGING_USER       — WordPress username
        WP_STAGING_APP_PASSWORD — WordPress application password

    Returns:
        A populated CMSConfig for WordPress staging.

    Raises:
        ConfigError: If required env vars are missing.
    """
    base_url = os.environ.get("WP_STAGING_BASE_URL", "").rstrip("/")
    username = os.environ.get("WP_STAGING_USER", "")
    app_password = os.environ.get("WP_STAGING_APP_PASSWORD", "")

    missing = []
    if not base_url:
        missing.append("WP_STAGING_BASE_URL")
    if not username:
        missing.append("WP_STAGING_USER")
    if not app_password:
        missing.append("WP_STAGING_APP_PASSWORD")

    if missing:
        raise ConfigError(
            f"Missing required WordPress staging env vars: {', '.join(missing)}. "
            "See .env.example for reference.",
        )

    # Construct the WP REST API URL from the site base URL
    api_base_url = f"{base_url}/wp-json/wp/v2"

    return CMSConfig(
        cms_type="wordpress",
        base_url=api_base_url,
        api_key=app_password,
        username=username,
        default_status="draft",
    )


# ---------------------------------------------------------------------------
# Canary article builder
# ---------------------------------------------------------------------------

_CANARY_SITE_BASE = "https://example.com"


def build_canary_article_draft(
    site_base_url: str = _CANARY_SITE_BASE,
    title: str = "Best Wireless Earbuds for Running 2025 — Honest Review",
) -> ArticleDraft:
    """Build a minimal but SEO-valid canary article that passes enforce_seo().

    The article contains every required OpenClaw SEO block:
    - TLDR / Quick Answer within the first 200 words
    - Comparison table (markdown pipe table)
    - FAQ section with 3+ questions
    - 5+ internal links
    - 3+ verdict statements
    - FTC affiliate disclosure

    Parameters
    ----------
    site_base_url:
        Base URL of the site, used to generate internal links.
    title:
        Article title (prefixed with [CANARY] automatically).

    Returns
    -------
    ArticleDraft
        A complete draft ready for CMS submission.
    """
    canary_title = f"{_CANARY_TITLE_PREFIX} {title}"
    base = site_base_url.rstrip("/")

    disclosure = (
        "Disclosure: This content is reader-supported. When you buy through "
        "affiliate links on this page, we may earn a commission. This does not "
        "influence our editorial opinions or ratings. All opinions expressed are "
        "our own and are based on our independent research and analysis."
    )

    # Introduction with TLDR at the top and internal links
    introduction = (
        f"## TL;DR — Quick Answer\n\n"
        f"Looking for the best wireless earbuds for running? After testing 12 models "
        f"over 3 months, our top pick is the SoundFit Pro X for most runners. "
        f"It combines excellent sound quality, secure fit, and IPX7 waterproofing "
        f"at a competitive price point. Read on for our full breakdown.\n\n"
        f"Whether you are training for a marathon or doing casual jogs, choosing "
        f"the right wireless earbuds matters. We tested comfort, sound quality, "
        f"battery life, and water resistance across all price ranges. "
        f"Check our [running gear guide]({base}/running-gear/) and "
        f"[fitness tech reviews]({base}/fitness-tech/) for more recommendations."
    )

    # Section 1: Comparison table
    section_table = SectionDraft(
        heading="Head-to-Head Comparison",
        heading_level=2,
        body=(
            f"Here is how our top picks stack up against each other:\n\n"
            f"| Model | Price | Battery | Water Rating | Our Verdict |\n"
            f"|-------|-------|---------|--------------|-------------|\n"
            f"| SoundFit Pro X | $79 | 8h | IPX7 | Best Overall |\n"
            f"| BassRun Elite | $129 | 10h | IPX5 | Best Premium |\n"
            f"| BudgetBeat Go | $29 | 6h | IPX4 | Best Budget |\n"
            f"| RunPods Ultra | $99 | 9h | IPX6 | Best for Long Runs |\n\n"
            f"For more details on water resistance ratings, see our "
            f"[IPX ratings explained guide]({base}/guides/ipx-ratings/)."
        ),
        word_count=80,
    )

    # Section 2: Detailed reviews with verdict statements
    section_reviews = SectionDraft(
        heading="Detailed Product Reviews",
        heading_level=2,
        body=(
            f"**SoundFit Pro X — Best Overall**\n\n"
            f"The SoundFit Pro X is our top pick for most runners. It delivers "
            f"rich bass, a secure ear-hook design, and reliable Bluetooth 5.3 "
            f"connectivity. Battery life of 8 hours is more than enough for "
            f"most training sessions. We highly recommend this model for anyone "
            f"who wants great sound without breaking the bank.\n\n"
            f"**BassRun Elite — Best Premium**\n\n"
            f"If budget is not a concern, the BassRun Elite is the winner in "
            f"the premium category. Adaptive noise cancellation and spatial "
            f"audio make it a standout. The 10-hour battery and premium fit "
            f"justify the higher price tag.\n\n"
            f"**BudgetBeat Go — Best Budget**\n\n"
            f"Verdict: the BudgetBeat Go punches well above its weight class. "
            f"At just $29, it offers surprisingly good sound and a comfortable "
            f"fit. IPX4 splash resistance handles sweat without issue. "
            f"For more affordable options, browse our "
            f"[budget headphones roundup]({base}/budget-headphones/)."
        ),
        word_count=160,
    )

    # Section 3: FAQ
    section_faq = SectionDraft(
        heading="Frequently Asked Questions (FAQ)",
        heading_level=2,
        body=(
            f"**Q: Are wireless earbuds good for running?**\n\n"
            f"A: Yes. Modern wireless earbuds with ear hooks or wing tips stay "
            f"secure during intense workouts. Look for IPX5 or higher water "
            f"resistance for sweat protection.\n\n"
            f"**Q: How long do running earbuds last?**\n\n"
            f"A: Most quality running earbuds last 6-10 hours per charge. "
            f"Models with a charging case extend total battery to 24-30 hours.\n\n"
            f"**Q: Can I use AirPods for running?**\n\n"
            f"A: AirPods work for casual jogs, but dedicated running earbuds "
            f"with ear hooks provide a more secure fit for intense sessions. "
            f"See our [AirPods alternatives guide]({base}/airpods-alternatives/) "
            f"for better sport-focused options."
        ),
        word_count=120,
    )

    # Conclusion with final verdict
    conclusion = (
        f"After extensive testing, we recommend the SoundFit Pro X as the best "
        f"wireless earbuds for running for most people. It strikes the ideal "
        f"balance of price, performance, and durability. For premium buyers, "
        f"the BassRun Elite is our editor's choice. And the BudgetBeat Go "
        f"proves you do not need to spend a fortune for a solid running companion. "
        f"Final verdict: invest in a pair that matches your budget and running "
        f"style — your training sessions will thank you. "
        f"For our full lineup of recommendations, visit our "
        f"[best running accessories page]({base}/running-accessories/)."
    )

    sections = [section_table, section_reviews, section_faq]

    # Calculate total word count
    intro_words = len(introduction.split())
    section_words = sum(len(s.body.split()) for s in sections)
    conclusion_words = len(conclusion.split())
    total_words = intro_words + section_words + conclusion_words

    # Update section word counts
    for s in sections:
        s.word_count = len(s.body.split())

    draft = ArticleDraft(
        title=canary_title,
        outline_id=f"canary-{uuid.uuid4().hex[:8]}",
        disclosure=disclosure,
        introduction=introduction,
        sections=sections,
        conclusion=conclusion,
        total_word_count=total_words,
        metadata={
            "canary": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    # Validate against SEO rules before returning
    full_text = draft.introduction + "\n"
    for section in draft.sections:
        full_text += f"## {section.heading}\n{section.body}\n"
    full_text += draft.conclusion

    # This will raise ContentValidationError if any block is missing
    seo_result = enforce_seo(full_text)
    logger.info(
        "Canary article passed SEO validation (AI Domination Score: %d/10)",
        seo_result.ai_domination_score,
    )

    return draft


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def run_canary_publish(
    staging: bool = True,
    title: str = "Best Wireless Earbuds for Running 2025 — Honest Review",
) -> Dict[str, Any]:
    """Build a canary article, validate it, and publish to WordPress staging.

    Steps:
    1. Check safety gates (ALLOW_PUBLISHING, STAGING_ONLY, kill switch).
    2. Load CMS config from environment.
    3. Build a canary article that passes enforce_seo().
    4. Push to WordPress as a draft via CMSTool.
    5. Return result summary.

    Parameters
    ----------
    staging:
        Must be True (only staging publishing is supported for canary).
    title:
        Title for the canary article.

    Returns
    -------
    dict
        Result summary with post_id, url, status, and validation details.

    Raises
    ------
    ConfigError:
        If safety gates fail or credentials are missing.
    ContentValidationError:
        If the canary article fails SEO validation (bug in builder).
    CMSConnectionError:
        If WordPress cannot be reached.
    """
    log_event(logger, "canary.start", staging=staging, title=title)

    # 1. Safety gates
    _check_safety_gates(staging)

    # 2. Load CMS config
    cms_config = get_staging_wp_config_from_env()
    log_event(
        logger,
        "canary.config_loaded",
        api_base_url=cms_config.base_url,
        username=cms_config.username,
    )

    # 3. Build canary article (validates SEO internally)
    site_base_url = os.environ.get("WP_STAGING_BASE_URL", _CANARY_SITE_BASE)
    draft = build_canary_article_draft(site_base_url=site_base_url, title=title)
    log_event(
        logger,
        "canary.draft_built",
        title=draft.title,
        word_count=draft.total_word_count,
    )

    # 4. Format and push to CMS
    from src.pipelines.publishing.publish_post import format_for_cms

    payload = format_for_cms(
        draft,
        cms_type="wordpress",
        include_disclosure=True,
        include_schema=False,
    )
    # Force draft status for canary
    payload["status"] = "draft"

    from src.agents.tools.cms_tool import CMSTool

    cms = CMSTool(
        {
            "cms_type": "wordpress",
            "api_base_url": cms_config.base_url,
            "api_key": cms_config.api_key,
            "username": cms_config.username,
            "default_status": "draft",
            "request_timeout": 30,
            "verify_ssl": True,
        }
    )

    try:
        result = cms.create_post(
            {
                "title": payload["title"],
                "content": payload["content"],
                "excerpt": payload.get("excerpt", ""),
                "slug": payload.get("slug", ""),
                "status": "draft",
            }
        )
    except Exception as exc:
        raise CMSConnectionError(
            f"Canary publish failed: {exc}",
            details={"title": draft.title, "api_base_url": cms_config.base_url},
            cause=exc,
        ) from exc

    post_id = result.get("id", "")
    post_url = result.get("url", "")

    summary = {
        "success": True,
        "post_id": post_id,
        "url": post_url,
        "title": draft.title,
        "status": "draft",
        "word_count": draft.total_word_count,
        "api_base_url": cms_config.base_url,
        "published_at": datetime.now(timezone.utc).isoformat(),
    }

    log_event(
        logger,
        "canary.complete",
        post_id=post_id,
        url=post_url,
    )

    return summary
