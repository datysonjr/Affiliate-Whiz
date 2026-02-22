"""
domains.content.models
~~~~~~~~~~~~~~~~~~~~~~

Data models for the content generation and management domain.

An :class:`Article` represents a single piece of affiliate content (blog
post, product review, comparison, roundup) that progresses through the
:class:`ContentStatus` lifecycle from draft to publication.  Each article
is built from a :class:`ContentOutline` composed of :class:`ContentSection`
blocks.

Design references:
    - ARCHITECTURE.md  Section 3 (Content Pipeline)
    - core/constants.py  DEFAULT_TARGET_WORD_COUNT, DEFAULT_QUALITY_THRESHOLD
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, unique
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

@unique
class ContentStatus(str, Enum):
    """Lifecycle status of a content piece.

    State transitions:
        DRAFT -> REVIEW -> READY -> PUBLISHED
        PUBLISHED -> PRUNED (when content decays below performance thresholds)

    Any state may transition to DRAFT if major revisions are required.
    """

    DRAFT = "draft"
    REVIEW = "review"
    READY = "ready"
    PUBLISHED = "published"
    PRUNED = "pruned"

    def is_editable(self) -> bool:
        """Return ``True`` if the content can still be modified."""
        return self in (ContentStatus.DRAFT, ContentStatus.REVIEW)

    def is_live(self) -> bool:
        """Return ``True`` if the content is publicly visible."""
        return self == ContentStatus.PUBLISHED


@unique
class ContentType(str, Enum):
    """Type of affiliate content piece.

    Each type maps to a specific markdown template under
    ``domains/content/templates/``.
    """

    BLOG_POST = "blog_post"
    PRODUCT_REVIEW = "product_review"
    COMPARISON = "comparison"
    ROUNDUP = "roundup"

    @property
    def template_filename(self) -> str:
        """Return the corresponding template file name."""
        return f"{self.value}.md"


# ---------------------------------------------------------------------------
# ContentSection
# ---------------------------------------------------------------------------

@dataclass
class ContentSection:
    """A single section within a content outline or article.

    Sections are the atomic building blocks of an article.  Each one
    represents a heading + body block that the content generator fills in.

    Attributes
    ----------
    heading:
        Section heading text (rendered as an H2 or H3).
    body:
        Generated body text for this section.
    heading_level:
        HTML heading level (2 for H2, 3 for H3, etc.).
    word_count:
        Number of words in the body text.
    keywords:
        Target keywords this section should incorporate.
    order:
        Sort order within the parent outline (0-based).
    notes:
        Editorial notes or generation instructions for this section.
    """

    heading: str
    body: str = ""
    heading_level: int = 2
    word_count: int = 0
    keywords: List[str] = field(default_factory=list)
    order: int = 0
    notes: str = ""

    def compute_word_count(self) -> int:
        """Count words in the body and store the result.

        Returns
        -------
        int
            Number of whitespace-delimited words in the body.
        """
        self.word_count = len(self.body.split()) if self.body else 0
        return self.word_count


# ---------------------------------------------------------------------------
# ContentOutline
# ---------------------------------------------------------------------------

@dataclass
class ContentOutline:
    """Structured outline for a content piece prior to full generation.

    The outline is produced during the planning phase and drives the
    section-by-section generation process.  It captures the target
    structure, keyword strategy, and editorial direction.

    Attributes
    ----------
    title:
        Working title for the article.
    content_type:
        Type of content (blog post, review, comparison, roundup).
    target_word_count:
        Desired total word count for the finished article.
    primary_keyword:
        The main SEO keyword this article targets.
    secondary_keywords:
        Supporting keywords to weave into the content.
    sections:
        Ordered list of planned sections.
    target_audience:
        Description of the intended reader.
    tone:
        Desired writing tone (e.g. ``"informative"``, ``"conversational"``).
    notes:
        Free-form editorial or generation notes.
    created_at:
        UTC timestamp when the outline was created.
    """

    title: str
    content_type: ContentType = ContentType.BLOG_POST
    target_word_count: int = 1500
    primary_keyword: str = ""
    secondary_keywords: List[str] = field(default_factory=list)
    sections: List[ContentSection] = field(default_factory=list)
    target_audience: str = ""
    tone: str = "informative"
    notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def section_count(self) -> int:
        """Return the number of planned sections."""
        return len(self.sections)

    def add_section(
        self,
        heading: str,
        *,
        heading_level: int = 2,
        keywords: Optional[List[str]] = None,
        notes: str = "",
    ) -> ContentSection:
        """Append a new section to the outline.

        Parameters
        ----------
        heading:
            Section heading text.
        heading_level:
            HTML heading level.
        keywords:
            Keywords this section should target.
        notes:
            Editorial notes for generation.

        Returns
        -------
        ContentSection
            The newly created section.
        """
        section = ContentSection(
            heading=heading,
            heading_level=heading_level,
            keywords=keywords or [],
            order=len(self.sections),
            notes=notes,
        )
        self.sections.append(section)
        return section

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the outline to a JSON-friendly dictionary."""
        return {
            "title": self.title,
            "content_type": self.content_type.value,
            "target_word_count": self.target_word_count,
            "primary_keyword": self.primary_keyword,
            "secondary_keywords": self.secondary_keywords,
            "sections": [
                {
                    "heading": s.heading,
                    "heading_level": s.heading_level,
                    "keywords": s.keywords,
                    "order": s.order,
                    "notes": s.notes,
                }
                for s in self.sections
            ],
            "target_audience": self.target_audience,
            "tone": self.tone,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# Article
# ---------------------------------------------------------------------------

@dataclass
class Article:
    """A single piece of affiliate content managed by the content pipeline.

    An Article is the primary output of the content generation process.
    It progresses through the :class:`ContentStatus` lifecycle and is
    eventually published to a site via the publishing domain.

    Attributes
    ----------
    id:
        Unique identifier (auto-generated UUID hex).
    title:
        Article title / headline.
    slug:
        URL-safe slug derived from the title.
    content:
        Full article body in Markdown format.
    word_count:
        Total word count of the content body.
    keywords:
        List of target SEO keywords.
    status:
        Current lifecycle status.
    quality_score:
        Content quality score (0.0--1.0) assigned during review.
    site_id:
        Identifier of the target site for publication.
    content_type:
        Type of content (blog post, review, etc.).
    outline:
        The :class:`ContentOutline` this article was generated from.
    sections:
        Ordered list of content sections composing the article body.
    created_at:
        UTC timestamp when the article was first created.
    published_at:
        UTC timestamp when the article was published (``None`` if unpublished).
    updated_at:
        UTC timestamp of the most recent modification.
    metadata:
        Free-form dict for additional data (featured image, excerpt, etc.).
    """

    title: str
    slug: str = ""
    content: str = ""
    word_count: int = 0
    keywords: List[str] = field(default_factory=list)
    status: ContentStatus = ContentStatus.DRAFT
    quality_score: float = 0.0
    site_id: str = ""
    content_type: ContentType = ContentType.BLOG_POST
    outline: Optional[ContentOutline] = None
    sections: List[ContentSection] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    published_at: Optional[datetime] = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------

    @property
    def is_publishable(self) -> bool:
        """Return ``True`` if the article meets minimum publishing criteria.

        An article is publishable when it has READY status, a non-empty
        body, at least one keyword, and a quality score at or above 0.7.
        """
        return (
            self.status == ContentStatus.READY
            and len(self.content) > 0
            and len(self.keywords) > 0
            and self.quality_score >= 0.7
        )

    @property
    def reading_time_minutes(self) -> int:
        """Estimate reading time assuming 230 words per minute."""
        if self.word_count <= 0:
            return 0
        return max(1, round(self.word_count / 230))

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def generate_slug(self) -> str:
        """Generate a URL-safe slug from the title and store it.

        Returns
        -------
        str
            The generated slug.
        """
        import re

        slug = self.title.lower().strip()
        slug = re.sub(r"[^\w\s-]", "", slug)
        slug = re.sub(r"[\s_]+", "-", slug)
        slug = re.sub(r"-+", "-", slug).strip("-")
        self.slug = slug[:200]  # Limit slug length
        return self.slug

    def compute_word_count(self) -> int:
        """Count words in the content body and update :attr:`word_count`.

        Also recomputes word counts for individual sections.

        Returns
        -------
        int
            Total word count.
        """
        self.word_count = len(self.content.split()) if self.content else 0
        for section in self.sections:
            section.compute_word_count()
        return self.word_count

    def transition_to(self, new_status: ContentStatus) -> None:
        """Transition the article to a new lifecycle status.

        Validates that the transition is allowed and updates the
        :attr:`updated_at` timestamp.

        Parameters
        ----------
        new_status:
            Target status.

        Raises
        ------
        ValueError
            If the transition is not permitted from the current status.
        """
        allowed_transitions: Dict[ContentStatus, List[ContentStatus]] = {
            ContentStatus.DRAFT: [ContentStatus.REVIEW],
            ContentStatus.REVIEW: [ContentStatus.READY, ContentStatus.DRAFT],
            ContentStatus.READY: [ContentStatus.PUBLISHED, ContentStatus.DRAFT],
            ContentStatus.PUBLISHED: [ContentStatus.PRUNED, ContentStatus.DRAFT],
            ContentStatus.PRUNED: [ContentStatus.DRAFT],
        }

        valid_targets = allowed_transitions.get(self.status, [])
        if new_status not in valid_targets:
            raise ValueError(
                f"Cannot transition from {self.status.value} to {new_status.value}. "
                f"Allowed targets: {[s.value for s in valid_targets]}"
            )

        self.status = new_status
        self.updated_at = datetime.now(timezone.utc)

        if new_status == ContentStatus.PUBLISHED:
            self.published_at = self.updated_at

    def assemble_content(self) -> str:
        """Assemble the full article body from its sections.

        Concatenates section headings and bodies into a single Markdown
        string and stores it in :attr:`content`.

        Returns
        -------
        str
            The assembled Markdown content.
        """
        parts: List[str] = []
        sorted_sections = sorted(self.sections, key=lambda s: s.order)

        for section in sorted_sections:
            prefix = "#" * section.heading_level
            parts.append(f"{prefix} {section.heading}\n")
            if section.body:
                parts.append(f"{section.body}\n")

        self.content = "\n".join(parts)
        self.compute_word_count()
        return self.content

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the article to a JSON-friendly dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "slug": self.slug,
            "content_type": self.content_type.value,
            "word_count": self.word_count,
            "keywords": self.keywords,
            "status": self.status.value,
            "quality_score": self.quality_score,
            "site_id": self.site_id,
            "reading_time_minutes": self.reading_time_minutes,
            "is_publishable": self.is_publishable,
            "created_at": self.created_at.isoformat(),
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata,
        }

    def __repr__(self) -> str:
        return (
            f"Article(title={self.title!r}, status={self.status.value}, "
            f"words={self.word_count}, quality={self.quality_score:.2f})"
        )
