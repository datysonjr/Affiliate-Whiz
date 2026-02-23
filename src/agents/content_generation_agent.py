"""
agents.content_generation_agent
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ContentGenerationAgent is responsible for the full content creation
pipeline: topic selection, outline generation, draft writing, SEO
optimisation, and affiliate link insertion.

Design references:
    - ARCHITECTURE.md  Section 2 (Agent Architecture)
    - config/pipelines.yaml    (content pipeline stages)
    - config/thresholds.yaml   (quality thresholds, keyword density targets)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, unique
from typing import Any, Dict, List, Optional

from src.agents.base_agent import BaseAgent
from src.core.constants import (
    AgentName,
    ContentStatus,
    DEFAULT_KEYWORD_DENSITY,
    DEFAULT_MIN_WORD_COUNT,
    DEFAULT_QUALITY_THRESHOLD,
    DEFAULT_TARGET_WORD_COUNT,
)
from src.core.logger import log_event


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@unique
class ContentType(str, Enum):
    """Types of content the agent can produce."""

    REVIEW = "review"
    COMPARISON = "comparison"
    LISTICLE = "listicle"
    HOW_TO = "how_to"
    BUYER_GUIDE = "buyer_guide"
    INFORMATIONAL = "informational"


@dataclass
class ContentBrief:
    """Specification for a single piece of content to produce.

    Attributes:
        brief_id:         Unique identifier.
        primary_keyword:  Main keyword to target.
        secondary_keywords: Supporting keywords to weave in.
        content_type:     What format the article should take.
        target_word_count: Desired article length.
        niche:            Niche this content belongs to.
        affiliate_offers: Offers to promote within the content.
        notes:            Free-form notes from research or scheduling.
    """

    brief_id: str
    primary_keyword: str
    secondary_keywords: List[str] = field(default_factory=list)
    content_type: ContentType = ContentType.INFORMATIONAL
    target_word_count: int = DEFAULT_TARGET_WORD_COUNT
    niche: str = ""
    affiliate_offers: List[Dict[str, Any]] = field(default_factory=list)
    notes: str = ""


@dataclass
class ContentOutline:
    """Structured outline for a piece of content.

    Attributes:
        title:      Proposed H1 / page title.
        meta_desc:  Proposed meta description.
        sections:   Ordered list of section headings and notes.
        faq:        FAQ questions to include.
    """

    title: str = ""
    meta_desc: str = ""
    sections: List[Dict[str, str]] = field(default_factory=list)
    faq: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class ContentDraft:
    """A fully drafted article.

    Attributes:
        brief_id:     Links back to the original brief.
        outline:      The outline this draft follows.
        html_body:    Full HTML body of the article.
        word_count:   Actual word count of the produced text.
        status:       Current lifecycle status.
    """

    brief_id: str
    outline: ContentOutline = field(default_factory=ContentOutline)
    html_body: str = ""
    word_count: int = 0
    status: ContentStatus = ContentStatus.DRAFT


@dataclass
class QualityMetrics:
    """Quality assessment for a single piece of content.

    Attributes:
        readability_score:     Flesch-Kincaid or similar (0-100).
        keyword_density:       Primary keyword density as a fraction.
        internal_link_count:   Number of internal links placed.
        affiliate_link_count:  Number of affiliate links placed.
        seo_score:             Composite SEO quality score (0-1.0).
        word_count:            Final word count.
        passed:                Whether the content meets all thresholds.
        issues:                List of issues that need correction.
    """

    readability_score: float = 0.0
    keyword_density: float = 0.0
    internal_link_count: int = 0
    affiliate_link_count: int = 0
    seo_score: float = 0.0
    word_count: int = 0
    passed: bool = False
    issues: List[str] = field(default_factory=list)


@dataclass
class ContentPlan:
    """Output of the planning phase -- the briefs to produce this cycle.

    Attributes:
        briefs:     Content briefs to execute.
        plan_time:  When the plan was generated.
    """

    briefs: List[ContentBrief] = field(default_factory=list)
    plan_time: Optional[datetime] = None


@dataclass
class ContentExecutionResult:
    """Aggregated results of the content pipeline execution.

    Attributes:
        drafts:           Produced drafts (keyed by brief_id).
        quality_metrics:  Quality assessment for each draft.
        errors:           Errors encountered during production.
    """

    drafts: Dict[str, ContentDraft] = field(default_factory=dict)
    quality_metrics: Dict[str, QualityMetrics] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent implementation
# ---------------------------------------------------------------------------


class ContentGenerationAgent(BaseAgent):
    """Handles the full content creation pipeline.

    The ContentGenerationAgent runs a multi-stage pipeline for each content
    brief:

    1. **Outline** -- Generate a structured outline from the brief.
    2. **Draft** -- Produce a full article following the outline.
    3. **SEO pass** -- Optimise keyword placement, meta tags, schema markup.
    4. **Link insertion** -- Place affiliate and internal links.
    5. **Quality check** -- Validate readability, density, and compliance.

    Configuration keys (from ``config/agents.yaml`` under ``content_generation``):
        enabled:              bool  -- whether this agent is active.
        max_articles_per_run: int   -- cap on articles per cycle.
        target_word_count:    int   -- default article length.
        quality_threshold:    float -- minimum SEO score to pass (0-1.0).
        keyword_density:      float -- target keyword density fraction.
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        super().__init__(name=str(AgentName.CONTENT_GENERATION), config=config)
        self._max_articles: int = config.get("max_articles_per_run", 3)
        self._target_word_count: int = config.get(
            "target_word_count", DEFAULT_TARGET_WORD_COUNT
        )
        self._quality_threshold: float = config.get(
            "quality_threshold", DEFAULT_QUALITY_THRESHOLD
        )
        self._keyword_density_target: float = config.get(
            "keyword_density", DEFAULT_KEYWORD_DENSITY
        )
        self._pending_briefs: List[ContentBrief] = []
        self._brief_counter: int = 0

    # ------------------------------------------------------------------
    # Public API for upstream agents
    # ------------------------------------------------------------------

    def enqueue_brief(self, brief: ContentBrief) -> None:
        """Add a content brief to the pending queue.

        Called by the scheduler or research agent when new content
        opportunities are identified.

        Parameters:
            brief: The content brief to enqueue.
        """
        self._pending_briefs.append(brief)
        self.logger.info(
            "Enqueued brief %s: '%s'", brief.brief_id, brief.primary_keyword
        )

    # ------------------------------------------------------------------
    # BaseAgent lifecycle
    # ------------------------------------------------------------------

    def plan(self) -> ContentPlan:
        """Select topics and keywords for this cycle's content production.

        Reads from the pending brief queue and caps the number of articles
        to produce based on ``max_articles_per_run``.

        Returns:
            A :class:`ContentPlan` with the briefs to process.
        """
        log_event(
            self.logger,
            "content.plan.start",
            pending_briefs=len(self._pending_briefs),
        )

        plan = ContentPlan(plan_time=datetime.now(timezone.utc))

        # Take up to max_articles from the pending queue
        batch_size = min(self._max_articles, len(self._pending_briefs))
        plan.briefs = self._pending_briefs[:batch_size]
        self._pending_briefs = self._pending_briefs[batch_size:]

        # If no briefs are pending, generate default briefs from config
        if not plan.briefs:
            default_topics = self.config.get("default_topics", [])
            for topic in default_topics[: self._max_articles]:
                self._brief_counter += 1
                brief = ContentBrief(
                    brief_id=f"auto-{self._brief_counter:04d}",
                    primary_keyword=topic,
                    target_word_count=self._target_word_count,
                )
                plan.briefs.append(brief)

        log_event(
            self.logger,
            "content.plan.complete",
            briefs_selected=len(plan.briefs),
            remaining_pending=len(self._pending_briefs),
        )
        return plan

    def execute(self, plan: ContentPlan) -> ContentExecutionResult:
        """Run the content pipeline for each brief: outline, draft, SEO, links.

        Parameters:
            plan: The :class:`ContentPlan` from planning.

        Returns:
            A :class:`ContentExecutionResult` with produced drafts and metrics.
        """
        result = ContentExecutionResult()

        for brief in plan.briefs:
            log_event(
                self.logger,
                "content.pipeline.start",
                brief_id=brief.brief_id,
                keyword=brief.primary_keyword,
            )

            try:
                # Stage 1: Outline
                outline = self._generate_outline(brief)

                # Stage 2: Draft
                draft = self._generate_draft(brief, outline)

                # Stage 3: SEO optimisation
                draft = self._apply_seo_pass(draft, brief)

                # Stage 4: Link insertion
                draft = self._insert_links(draft, brief)

                # Stage 5: Quality check
                metrics = self._assess_quality(draft, brief)

                result.drafts[brief.brief_id] = draft
                result.quality_metrics[brief.brief_id] = metrics

                if metrics.passed:
                    draft.status = ContentStatus.REVIEW
                    log_event(
                        self.logger,
                        "content.pipeline.passed",
                        brief_id=brief.brief_id,
                        seo_score=metrics.seo_score,
                    )
                else:
                    self.logger.warning(
                        "Content for brief %s did not pass quality checks: %s",
                        brief.brief_id,
                        metrics.issues,
                    )

            except Exception as exc:
                result.errors.append(
                    f"Pipeline failed for brief {brief.brief_id}: {exc}"
                )
                self.logger.error(
                    "Content pipeline failed for brief %s: %s", brief.brief_id, exc
                )

        return result

    def report(
        self, plan: ContentPlan, result: ContentExecutionResult
    ) -> Dict[str, Any]:
        """Log content quality metrics and return a structured summary.

        Parameters:
            plan:   The content plan.
            result: The execution result.

        Returns:
            A summary dict for the orchestrator's audit log.
        """
        passed_count = sum(1 for m in result.quality_metrics.values() if m.passed)
        total_words = sum(m.word_count for m in result.quality_metrics.values())
        avg_seo = sum(m.seo_score for m in result.quality_metrics.values()) / max(
            len(result.quality_metrics), 1
        )

        report_data: Dict[str, Any] = {
            "briefs_planned": len(plan.briefs),
            "drafts_produced": len(result.drafts),
            "quality_passed": passed_count,
            "quality_failed": len(result.drafts) - passed_count,
            "total_words": total_words,
            "average_seo_score": round(avg_seo, 3),
            "errors": result.errors,
            "per_brief": {
                bid: {
                    "word_count": m.word_count,
                    "seo_score": m.seo_score,
                    "keyword_density": m.keyword_density,
                    "passed": m.passed,
                    "issues": m.issues,
                }
                for bid, m in result.quality_metrics.items()
            },
        }

        self._log_metric("content.drafts.produced", len(result.drafts))
        self._log_metric("content.quality.passed", passed_count)
        self._log_metric("content.total_words", total_words)
        self._log_metric("content.avg_seo_score", round(avg_seo, 3))

        log_event(
            self.logger,
            "content.report.complete",
            produced=len(result.drafts),
            passed=passed_count,
        )
        return report_data

    # ------------------------------------------------------------------
    # LLM Tool integration
    # ------------------------------------------------------------------

    def _get_llm_tool(self):
        """Lazily initialize and return an LLMTool reading config from env."""
        if not hasattr(self, "_llm_tool") or self._llm_tool is None:
            import os
            from src.agents.tools.llm_tool import LLMTool

            provider = os.environ.get("LLM_PROVIDER", "anthropic")
            self._llm_tool = LLMTool(
                {
                    "primary_provider": provider,
                    "primary_model": os.environ.get(
                        "LLM_MODEL_DEFAULT", "claude-sonnet-4-20250514"
                    ),
                    "primary_api_key": os.environ.get("LLM_API_KEY", ""),
                    "fallback_provider": "openai" if provider != "openai" else None,
                    "fallback_model": "gpt-4o",
                    "fallback_api_key": os.environ.get("OPENAI_API_KEY", ""),
                    "default_max_tokens": 4096,
                    "temperature": 0.7,
                    "retry_attempts": 2,
                    "retry_delay": 1.0,
                }
            )
        return self._llm_tool

    # ------------------------------------------------------------------
    # Pipeline stages
    # ------------------------------------------------------------------

    def _generate_outline(self, brief: ContentBrief) -> ContentOutline:
        """Generate a structured outline from a content brief.

        Uses LLMTool when an API key is configured and not in dry-run mode.
        Falls back to a template outline otherwise.

        Parameters:
            brief: The content brief to outline.

        Returns:
            A :class:`ContentOutline`.
        """
        self.logger.debug("Generating outline for brief %s", brief.brief_id)

        # Try LLM-generated outline if not dry-run and API key is set
        import os

        if not self._dry_run and os.environ.get("LLM_API_KEY"):
            try:
                return self._generate_outline_with_llm(brief)
            except Exception as exc:
                self.logger.warning(
                    "LLM outline generation failed for %s, using template: %s",
                    brief.brief_id,
                    exc,
                )

        # Template fallback
        sections = [
            {
                "heading": f"Introduction to {brief.primary_keyword}",
                "notes": "Hook and overview",
            },
            {
                "heading": f"What is {brief.primary_keyword}?",
                "notes": "Definition and context",
            },
            {
                "heading": "Key Features and Benefits",
                "notes": "Core value propositions",
            },
            {"heading": "How to Choose", "notes": "Buyer criteria and comparison"},
            {
                "heading": "Our Top Recommendations",
                "notes": "Curated picks with rationale",
            },
            {
                "heading": "Frequently Asked Questions",
                "notes": "Address common queries",
            },
            {"heading": "Final Verdict", "notes": "Summary and CTA"},
        ]

        faq = [
            {"question": f"What is the best {brief.primary_keyword}?", "answer": ""},
            {"question": f"How much does {brief.primary_keyword} cost?", "answer": ""},
            {"question": f"Is {brief.primary_keyword} worth it?", "answer": ""},
        ]

        return ContentOutline(
            title=f"Best {brief.primary_keyword.title()} in 2026: Complete Guide",
            meta_desc=(
                f"Discover the best {brief.primary_keyword} options. "
                f"Expert reviews, comparisons, and buying advice."
            ),
            sections=sections,
            faq=faq,
        )

    def _generate_outline_with_llm(self, brief: ContentBrief) -> ContentOutline:
        """Generate an outline using the LLM tool."""
        import json

        llm = self._get_llm_tool()
        prompt = (
            f"Create an SEO-optimized article outline for the keyword: '{brief.primary_keyword}'\n"
            f"Content type: {brief.content_type.value}\n"
            f"Target word count: {brief.target_word_count}\n\n"
            "Return a JSON object with:\n"
            '- "title": SEO-optimized H1 title\n'
            '- "meta_desc": meta description (150-160 chars)\n'
            '- "sections": array of {"heading": "...", "notes": "..."}\n'
            '- "faq": array of {"question": "...", "answer": ""}\n\n'
            "Include at least 5 sections. Include a TLDR/Quick Answer section near the top, "
            "a comparison section, and an FAQ section. Return ONLY valid JSON."
        )

        raw = llm.generate(prompt, max_tokens=2048)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
        raw = raw.strip()

        data = json.loads(raw)
        return ContentOutline(
            title=data.get("title", f"Best {brief.primary_keyword.title()} Guide"),
            meta_desc=data.get("meta_desc", ""),
            sections=data.get("sections", []),
            faq=data.get("faq", []),
        )

    def _generate_draft(
        self, brief: ContentBrief, outline: ContentOutline
    ) -> ContentDraft:
        """Produce a full article draft from the outline.

        Uses LLMTool when an API key is configured and not in dry-run mode.
        Falls back to placeholder HTML otherwise.

        Parameters:
            brief:   The content brief.
            outline: The structured outline.

        Returns:
            A :class:`ContentDraft` with HTML body.
        """
        self.logger.debug("Generating draft for brief %s", brief.brief_id)

        # Try LLM-generated draft if not dry-run and API key is set
        import os

        if not self._dry_run and os.environ.get("LLM_API_KEY"):
            try:
                return self._generate_draft_with_llm(brief, outline)
            except Exception as exc:
                self.logger.warning(
                    "LLM draft generation failed for %s, using placeholder: %s",
                    brief.brief_id,
                    exc,
                )

        # Placeholder fallback
        html_parts = [f"<h1>{outline.title}</h1>"]
        for section in outline.sections:
            html_parts.append(f"<h2>{section['heading']}</h2>")
            html_parts.append(f"<p>[Content for: {section['notes']}]</p>")

        if outline.faq:
            html_parts.append("<h2>Frequently Asked Questions</h2>")
            for item in outline.faq:
                html_parts.append(f"<h3>{item['question']}</h3>")
                html_parts.append(f"<p>{item.get('answer', '[Answer pending]')}</p>")

        html_body = "\n".join(html_parts)
        word_count = len(html_body.split())

        return ContentDraft(
            brief_id=brief.brief_id,
            outline=outline,
            html_body=html_body,
            word_count=word_count,
        )

    def _generate_draft_with_llm(
        self, brief: ContentBrief, outline: ContentOutline
    ) -> ContentDraft:
        """Generate a full article draft using the LLM tool."""

        llm = self._get_llm_tool()

        sections_str = "\n".join(
            f"- {s['heading']}: {s.get('notes', '')}" for s in outline.sections
        )
        faq_str = (
            "\n".join(f"- {q['question']}" for q in outline.faq)
            if outline.faq
            else "None"
        )

        prompt = (
            f"Write a full SEO-optimized affiliate article in HTML format.\n\n"
            f"Title: {outline.title}\n"
            f"Primary keyword: {brief.primary_keyword}\n"
            f"Secondary keywords: {', '.join(brief.secondary_keywords) if brief.secondary_keywords else 'none'}\n"
            f"Target word count: {brief.target_word_count}\n\n"
            f"Outline sections:\n{sections_str}\n\n"
            f"FAQ questions:\n{faq_str}\n\n"
            "REQUIREMENTS:\n"
            "- Start with a TLDR/Quick Answer block within the first 200 words\n"
            "- Include a comparison table (HTML <table>) for product recommendations\n"
            "- Include an FAQ section with proper <h3> headings for each question\n"
            "- Include at least 3 verdict statements (e.g. 'We recommend...', 'Our top pick is...')\n"
            "- Include an FTC affiliate disclosure near the top\n"
            "- Use proper HTML: <h1>, <h2>, <h3>, <p>, <table>, <ul>, <li> tags\n"
            "- Do NOT include <html>, <head>, or <body> wrapper tags\n"
            "- Write naturally, not robotic. Be helpful and authoritative.\n"
        )

        html_body = llm.generate(prompt, max_tokens=4096)

        # Strip markdown code fences if model wrapped output
        html_body = html_body.strip()
        if html_body.startswith("```"):
            html_body = html_body.split("\n", 1)[-1]
        if html_body.endswith("```"):
            html_body = html_body.rsplit("```", 1)[0]
        html_body = html_body.strip()

        word_count = len(html_body.split())

        return ContentDraft(
            brief_id=brief.brief_id,
            outline=outline,
            html_body=html_body,
            word_count=word_count,
        )

    def _apply_seo_pass(self, draft: ContentDraft, brief: ContentBrief) -> ContentDraft:
        """Run SEO optimisation on the draft content.

        In production this calls the SEO tool to adjust keyword placement,
        add schema markup, and optimise headings.

        Parameters:
            draft: The raw article draft.
            brief: The original content brief.

        Returns:
            The same draft with SEO enhancements applied.
        """
        self.logger.debug("Applying SEO pass for brief %s", brief.brief_id)

        # Placeholder: Add JSON-LD FAQ schema if FAQ sections exist
        if draft.outline.faq:
            faq_schema = self._build_faq_schema(draft.outline.faq)
            draft.html_body = faq_schema + "\n" + draft.html_body

        return draft

    def _insert_links(self, draft: ContentDraft, brief: ContentBrief) -> ContentDraft:
        """Insert affiliate and internal links into the draft.

        In production this calls the LinkTool to place links at natural
        anchor points.

        Parameters:
            draft: The SEO-optimised draft.
            brief: The original content brief (contains affiliate offers).

        Returns:
            The draft with links inserted.
        """
        self.logger.debug("Inserting links for brief %s", brief.brief_id)
        # Placeholder -- real implementation uses LinkTool
        return draft

    def _assess_quality(
        self, draft: ContentDraft, brief: ContentBrief
    ) -> QualityMetrics:
        """Run quality checks against configured thresholds.

        Parameters:
            draft: The final draft.
            brief: The original content brief.

        Returns:
            A :class:`QualityMetrics` assessment.
        """
        self.logger.debug("Assessing quality for brief %s", brief.brief_id)

        issues: List[str] = []

        # Word count check
        if draft.word_count < DEFAULT_MIN_WORD_COUNT:
            issues.append(
                f"Word count {draft.word_count} below minimum {DEFAULT_MIN_WORD_COUNT}."
            )

        # Keyword density (simplified)
        body_lower = draft.html_body.lower()
        keyword_lower = brief.primary_keyword.lower()
        total_words = max(draft.word_count, 1)
        keyword_count = body_lower.count(keyword_lower)
        density = keyword_count / total_words

        if density > self._keyword_density_target * 2:
            issues.append(f"Keyword density {density:.3f} exceeds maximum.")
        if density < self._keyword_density_target * 0.5:
            issues.append(f"Keyword density {density:.3f} below minimum.")

        # Compute composite SEO score
        seo_score = 0.0
        if draft.word_count >= DEFAULT_MIN_WORD_COUNT:
            seo_score += 0.3
        if (
            self._keyword_density_target * 0.5
            <= density
            <= self._keyword_density_target * 2
        ):
            seo_score += 0.3
        if draft.outline.meta_desc:
            seo_score += 0.2
        if draft.outline.faq:
            seo_score += 0.2

        passed = seo_score >= self._quality_threshold and len(issues) == 0

        return QualityMetrics(
            readability_score=70.0,  # Placeholder
            keyword_density=round(density, 4),
            internal_link_count=0,
            affiliate_link_count=len(brief.affiliate_offers),
            seo_score=round(seo_score, 3),
            word_count=draft.word_count,
            passed=passed,
            issues=issues,
        )

    @staticmethod
    def _build_faq_schema(faq: List[Dict[str, str]]) -> str:
        """Build a JSON-LD FAQ schema markup string.

        Parameters:
            faq: List of question/answer dicts.

        Returns:
            An HTML script tag containing JSON-LD.
        """
        import json

        schema = {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": item.get("question", ""),
                    "acceptedAnswer": {
                        "@type": "Answer",
                        "text": item.get("answer", ""),
                    },
                }
                for item in faq
            ],
        }
        return f'<script type="application/ld+json">{json.dumps(schema)}</script>'
