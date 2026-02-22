"""
domains.seo.schema
~~~~~~~~~~~~~~~~~~~

Schema.org structured data (JSON-LD) generation for the OpenClaw SEO domain.

Generates standards-compliant JSON-LD markup that helps search engines
understand article content, product reviews, FAQs, and site navigation.
The output is designed to be embedded as a ``<script type="application/ld+json">``
block in the ``<head>`` of published pages.

Design references:
    - https://schema.org/Article
    - https://schema.org/Product
    - https://schema.org/Review
    - https://schema.org/FAQPage
    - https://schema.org/BreadcrumbList
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.core.logger import get_logger

logger = get_logger("seo.schema")


# ---------------------------------------------------------------------------
# Helper data classes for structured inputs
# ---------------------------------------------------------------------------

@dataclass
class SchemaAuthor:
    """Author information for schema markup.

    Attributes
    ----------
    name:
        Author display name.
    url:
        URL of the author profile page.
    author_type:
        Schema.org type: ``"Person"`` or ``"Organization"``.
    """

    name: str
    url: str = ""
    author_type: str = "Person"

    def to_jsonld(self) -> Dict[str, str]:
        """Serialise to a JSON-LD ``@type: Person`` or ``Organization`` dict."""
        obj: Dict[str, str] = {"@type": self.author_type, "name": self.name}
        if self.url:
            obj["url"] = self.url
        return obj


@dataclass
class SchemaRating:
    """Rating information for review schema.

    Attributes
    ----------
    value:
        The rating value (e.g. ``4.5``).
    best:
        Best possible rating (default ``5``).
    worst:
        Worst possible rating (default ``1``).
    """

    value: float
    best: float = 5.0
    worst: float = 1.0

    def to_jsonld(self) -> Dict[str, Any]:
        """Serialise to a JSON-LD ``Rating`` dict."""
        return {
            "@type": "Rating",
            "ratingValue": str(self.value),
            "bestRating": str(self.best),
            "worstRating": str(self.worst),
        }


@dataclass
class SchemaOffer:
    """Product offer / pricing for product schema.

    Attributes
    ----------
    price:
        Product price.
    currency:
        ISO 4217 currency code.
    availability:
        Schema.org availability value (e.g. ``"https://schema.org/InStock"``).
    url:
        URL where the product can be purchased.
    """

    price: float
    currency: str = "USD"
    availability: str = "https://schema.org/InStock"
    url: str = ""

    def to_jsonld(self) -> Dict[str, Any]:
        """Serialise to a JSON-LD ``Offer`` dict."""
        obj: Dict[str, Any] = {
            "@type": "Offer",
            "price": str(self.price),
            "priceCurrency": self.currency,
            "availability": self.availability,
        }
        if self.url:
            obj["url"] = self.url
        return obj


@dataclass
class BreadcrumbItem:
    """A single item in a breadcrumb trail.

    Attributes
    ----------
    name:
        Display text for the breadcrumb link.
    url:
        URL the breadcrumb points to.
    position:
        1-based position in the trail.
    """

    name: str
    url: str
    position: int = 1


# ---------------------------------------------------------------------------
# Schema generators
# ---------------------------------------------------------------------------

def generate_article_schema(
    *,
    title: str,
    description: str,
    url: str,
    image_url: str = "",
    author: Optional[SchemaAuthor] = None,
    publisher_name: str = "",
    publisher_logo_url: str = "",
    date_published: Optional[datetime] = None,
    date_modified: Optional[datetime] = None,
    word_count: int = 0,
    keywords: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Generate a Schema.org ``Article`` JSON-LD object.

    Parameters
    ----------
    title:
        Article headline.
    description:
        Short description / meta description.
    url:
        Canonical URL of the article.
    image_url:
        URL of the primary article image.
    author:
        Author information.
    publisher_name:
        Name of the publishing organisation.
    publisher_logo_url:
        URL of the publisher logo.
    date_published:
        Publication date (UTC).
    date_modified:
        Last modification date (UTC).
    word_count:
        Article word count.
    keywords:
        List of article keywords.

    Returns
    -------
    dict
        JSON-LD object ready for serialisation.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    schema: Dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title[:110],  # Google truncates at ~110 chars
        "description": description[:320],
        "url": url,
        "datePublished": date_published.isoformat() if date_published else now_iso,
        "dateModified": date_modified.isoformat() if date_modified else now_iso,
    }

    if image_url:
        schema["image"] = image_url

    if author:
        schema["author"] = author.to_jsonld()

    if publisher_name:
        publisher: Dict[str, Any] = {
            "@type": "Organization",
            "name": publisher_name,
        }
        if publisher_logo_url:
            publisher["logo"] = {
                "@type": "ImageObject",
                "url": publisher_logo_url,
            }
        schema["publisher"] = publisher

    if word_count > 0:
        schema["wordCount"] = word_count

    if keywords:
        schema["keywords"] = ", ".join(keywords)

    logger.debug("Generated Article schema for '%s'", title)
    return schema


def generate_product_schema(
    *,
    name: str,
    description: str,
    url: str,
    image_url: str = "",
    brand: str = "",
    sku: str = "",
    offer: Optional[SchemaOffer] = None,
    rating_value: Optional[float] = None,
    rating_count: Optional[int] = None,
    review_count: Optional[int] = None,
) -> Dict[str, Any]:
    """Generate a Schema.org ``Product`` JSON-LD object.

    Parameters
    ----------
    name:
        Product name.
    description:
        Product description.
    url:
        Canonical URL of the product page.
    image_url:
        URL of the product image.
    brand:
        Brand or manufacturer name.
    sku:
        Product SKU.
    offer:
        Pricing information.
    rating_value:
        Aggregate rating value.
    rating_count:
        Number of ratings.
    review_count:
        Number of text reviews.

    Returns
    -------
    dict
        JSON-LD object.
    """
    schema: Dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": name,
        "description": description[:5000],
        "url": url,
    }

    if image_url:
        schema["image"] = image_url

    if brand:
        schema["brand"] = {"@type": "Brand", "name": brand}

    if sku:
        schema["sku"] = sku

    if offer:
        schema["offers"] = offer.to_jsonld()

    if rating_value is not None:
        aggregate: Dict[str, Any] = {
            "@type": "AggregateRating",
            "ratingValue": str(rating_value),
            "bestRating": "5",
        }
        if rating_count is not None:
            aggregate["ratingCount"] = str(rating_count)
        if review_count is not None:
            aggregate["reviewCount"] = str(review_count)
        schema["aggregateRating"] = aggregate

    logger.debug("Generated Product schema for '%s'", name)
    return schema


def generate_review_schema(
    *,
    item_name: str,
    review_body: str,
    rating: SchemaRating,
    author: Optional[SchemaAuthor] = None,
    date_published: Optional[datetime] = None,
    item_url: str = "",
    item_image_url: str = "",
    publisher_name: str = "",
) -> Dict[str, Any]:
    """Generate a Schema.org ``Review`` JSON-LD object.

    Parameters
    ----------
    item_name:
        Name of the reviewed product / item.
    review_body:
        Full text of the review.
    rating:
        Review rating.
    author:
        Review author.
    date_published:
        Review publication date (UTC).
    item_url:
        URL of the reviewed item.
    item_image_url:
        Image URL of the reviewed item.
    publisher_name:
        Name of the publishing site.

    Returns
    -------
    dict
        JSON-LD object.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    item_reviewed: Dict[str, Any] = {
        "@type": "Product",
        "name": item_name,
    }
    if item_url:
        item_reviewed["url"] = item_url
    if item_image_url:
        item_reviewed["image"] = item_image_url

    schema: Dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Review",
        "itemReviewed": item_reviewed,
        "reviewBody": review_body[:5000],
        "reviewRating": rating.to_jsonld(),
        "datePublished": date_published.isoformat() if date_published else now_iso,
    }

    if author:
        schema["author"] = author.to_jsonld()

    if publisher_name:
        schema["publisher"] = {
            "@type": "Organization",
            "name": publisher_name,
        }

    logger.debug("Generated Review schema for '%s'", item_name)
    return schema


def generate_faq_schema(
    questions_and_answers: List[Dict[str, str]],
) -> Dict[str, Any]:
    """Generate a Schema.org ``FAQPage`` JSON-LD object.

    Parameters
    ----------
    questions_and_answers:
        List of dicts with ``"question"`` and ``"answer"`` keys.

    Returns
    -------
    dict
        JSON-LD object.

    Examples
    --------
    >>> schema = generate_faq_schema([
    ...     {"question": "What is a standing desk?", "answer": "A desk that..."},
    ... ])
    >>> schema["@type"]
    'FAQPage'
    """
    main_entity: List[Dict[str, Any]] = []

    for qa in questions_and_answers:
        question = qa.get("question", "").strip()
        answer = qa.get("answer", "").strip()
        if not question or not answer:
            continue

        main_entity.append({
            "@type": "Question",
            "name": question,
            "acceptedAnswer": {
                "@type": "Answer",
                "text": answer,
            },
        })

    schema: Dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": main_entity,
    }

    logger.debug("Generated FAQ schema with %d questions", len(main_entity))
    return schema


def generate_breadcrumb_schema(
    items: List[BreadcrumbItem],
) -> Dict[str, Any]:
    """Generate a Schema.org ``BreadcrumbList`` JSON-LD object.

    Parameters
    ----------
    items:
        Ordered list of breadcrumb items (root to current page).

    Returns
    -------
    dict
        JSON-LD object.

    Examples
    --------
    >>> schema = generate_breadcrumb_schema([
    ...     BreadcrumbItem("Home", "https://example.com", 1),
    ...     BreadcrumbItem("Reviews", "https://example.com/reviews", 2),
    ... ])
    >>> len(schema["itemListElement"])
    2
    """
    elements: List[Dict[str, Any]] = []

    for item in items:
        elements.append({
            "@type": "ListItem",
            "position": item.position,
            "name": item.name,
            "item": item.url,
        })

    schema: Dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": elements,
    }

    logger.debug("Generated Breadcrumb schema with %d items", len(elements))
    return schema


# ---------------------------------------------------------------------------
# Serialisation utility
# ---------------------------------------------------------------------------

def schema_to_html(schema: Dict[str, Any]) -> str:
    """Wrap a JSON-LD schema dict in an HTML ``<script>`` tag.

    Parameters
    ----------
    schema:
        JSON-LD object produced by one of the ``generate_*`` functions.

    Returns
    -------
    str
        HTML ``<script>`` tag ready for embedding in the page ``<head>``.
    """
    json_str = json.dumps(schema, indent=2, ensure_ascii=False)
    return f'<script type="application/ld+json">\n{json_str}\n</script>'
