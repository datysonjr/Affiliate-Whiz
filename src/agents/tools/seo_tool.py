"""SEO Tool - Search engine optimization analysis and utilities.

This module provides methods for keyword research, SERP analysis, keyword
density calculations, schema markup generation, and competitor analysis.
Designed to support affiliate content optimization workflows.
"""

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)


class SEOTool:
    """Search engine optimization toolkit for affiliate content.

    Integrates with keyword research APIs, SERP checkers, and provides
    local analysis utilities for on-page SEO tasks.

    Config keys:
        serp_api_key (str): API key for the SERP checking provider.
        serp_api_base_url (str, optional): Custom SERP API base URL.
        keyword_api_key (str, optional): API key for keyword research data.
        keyword_api_base_url (str, optional): Custom keyword API base URL.
        country (str): Target country code for SERP/keyword data (default "us").
        language (str): Target language code (default "en").
        max_results (int): Default number of results to return (default 10).
        request_timeout (int): Timeout in seconds for external API calls (default 30).
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize the SEO tool with API credentials and preferences.

        Args:
            config: Dictionary containing API keys, locale settings, and
                request preferences. See class docstring for supported keys.
        """
        self.config = config

        # API credentials
        self.serp_api_key: str = config.get("serp_api_key", "")
        self.serp_api_base_url: Optional[str] = config.get("serp_api_base_url")
        self.keyword_api_key: str = config.get("keyword_api_key", "")
        self.keyword_api_base_url: Optional[str] = config.get("keyword_api_base_url")

        # Locale and search settings
        self.country: str = config.get("country", "us")
        self.language: str = config.get("language", "en")
        self.max_results: int = config.get("max_results", 10)
        self.request_timeout: int = config.get("request_timeout", 30)

        logger.info(
            "SEOTool initialized (country=%s, language=%s, max_results=%d)",
            self.country,
            self.language,
            self.max_results,
        )

    # ------------------------------------------------------------------
    # Keyword research
    # ------------------------------------------------------------------

    def analyze_keywords(
        self,
        keywords: list[str],
        include_related: bool = True,
    ) -> list[dict[str, Any]]:
        """Analyze a list of keywords for search volume, difficulty, and CPC.

        Queries a keyword research API (e.g. SEMrush, Ahrefs, or a custom
        provider) and returns enriched metrics for each keyword along with
        optionally related keyword suggestions.

        Args:
            keywords: List of seed keyword strings to analyze.
            include_related: If True, append related/suggested keywords to
                the results.

        Returns:
            A list of dicts, one per keyword, each containing:
                - keyword (str): The keyword phrase.
                - search_volume (int): Estimated monthly search volume.
                - keyword_difficulty (float): 0-100 difficulty score.
                - cpc (float): Estimated cost-per-click in USD.
                - competition (str): "low", "medium", or "high".
                - trend (list[int]): Monthly search volume trend (12 months).
                - related_keywords (list[str]): Related keyword suggestions
                  (present only when ``include_related`` is True).

        Raises:
            ValueError: If ``keywords`` is empty.
            ConnectionError: If the keyword API is unreachable.
        """
        if not keywords:
            raise ValueError("At least one keyword is required")

        logger.info(
            "Analyzing %d keywords (include_related=%s)", len(keywords), include_related
        )

        results: list[dict[str, Any]] = []
        for keyword in keywords:
            # TODO: Replace with actual API call to keyword research provider
            entry: dict[str, Any] = {
                "keyword": keyword,
                "search_volume": 0,
                "keyword_difficulty": 0.0,
                "cpc": 0.0,
                "competition": "low",
                "trend": [0] * 12,
            }
            if include_related:
                entry["related_keywords"] = []
            results.append(entry)

        logger.debug("Keyword analysis returned %d results", len(results))
        return results

    # ------------------------------------------------------------------
    # SERP checking
    # ------------------------------------------------------------------

    def check_serp(
        self,
        keyword: str,
        num_results: Optional[int] = None,
    ) -> dict[str, Any]:
        """Check search engine results page for a given keyword.

        Returns the top organic results, featured snippets, People Also Ask
        data, and other SERP features.

        Args:
            keyword: The search query to look up.
            num_results: Number of organic results to return. Defaults to
                ``self.max_results``.

        Returns:
            Dict containing:
                - keyword (str): The queried keyword.
                - organic_results (list[dict]): Top organic results, each with
                  "position", "title", "url", "snippet", and "domain".
                - featured_snippet (dict | None): Featured snippet data if present.
                - people_also_ask (list[str]): Related questions from the SERP.
                - total_results (int): Estimated total number of results.
                - serp_features (list[str]): List of detected SERP features
                  (e.g. "knowledge_panel", "video_carousel", "local_pack").

        Raises:
            ValueError: If keyword is empty.
            ConnectionError: If the SERP API is unreachable.
        """
        if not keyword or not keyword.strip():
            raise ValueError("Keyword must not be empty")

        effective_num = num_results or self.max_results
        logger.info("Checking SERP for '%s' (top %d)", keyword, effective_num)

        # TODO: Replace with actual SERP API call
        result: dict[str, Any] = {
            "keyword": keyword,
            "organic_results": [],
            "featured_snippet": None,
            "people_also_ask": [],
            "total_results": 0,
            "serp_features": [],
        }

        logger.debug("SERP check complete for '%s'", keyword)
        return result

    # ------------------------------------------------------------------
    # On-page SEO analysis
    # ------------------------------------------------------------------

    def calculate_keyword_density(self, text: str, keyword: str) -> float:
        """Calculate the keyword density within a body of text.

        Keyword density is computed as::

            (occurrences of keyword / total words) * 100

        Both single-word and multi-word keyword phrases are supported. The
        comparison is case-insensitive.

        Args:
            text: The full text content to analyze.
            keyword: The keyword or keyphrase to measure density for.

        Returns:
            Keyword density as a percentage (e.g. 2.5 means 2.5%).

        Raises:
            ValueError: If text or keyword is empty.
        """
        if not text or not text.strip():
            raise ValueError("Text must not be empty")
        if not keyword or not keyword.strip():
            raise ValueError("Keyword must not be empty")

        text_lower = text.lower()
        keyword_lower = keyword.lower().strip()

        # Count occurrences using regex word-boundary matching
        pattern = re.compile(r"\b" + re.escape(keyword_lower) + r"\b")
        occurrences = len(pattern.findall(text_lower))

        # Total word count
        total_words = len(text_lower.split())
        if total_words == 0:
            return 0.0

        # For multi-word keywords, each occurrence counts as one unit
        density = (occurrences / total_words) * 100

        logger.debug(
            "Keyword density for '%s': %.2f%% (%d occurrences in %d words)",
            keyword,
            density,
            occurrences,
            total_words,
        )
        return round(density, 4)

    # ------------------------------------------------------------------
    # Schema markup
    # ------------------------------------------------------------------

    def generate_schema_markup(
        self,
        data: dict[str, Any],
        schema_type: Optional[str] = None,
    ) -> dict[str, Any]:
        """Generate JSON-LD schema markup for structured data.

        Supports common schema.org types relevant to affiliate marketing:
        Product, Review, Article, FAQ, HowTo, and BreadcrumbList.

        Args:
            data: A dictionary containing the fields to embed in the schema.
                Required keys vary by ``schema_type``:

                **Product**: name, description, image, brand, offers (dict
                with price, currency, availability, url).

                **Review**: name, reviewBody, author, ratingValue,
                bestRating, itemReviewed.

                **Article**: headline, description, author, datePublished,
                image, publisher.

                **FAQ**: questions (list of dicts with "question" and "answer").

            schema_type: The schema.org type to generate. If not provided,
                the type is inferred from the ``data`` keys.

        Returns:
            A JSON-LD compatible dictionary ready to be embedded in a
            ``<script type="application/ld+json">`` tag.

        Raises:
            ValueError: If the schema type cannot be determined or required
                fields are missing.
        """
        inferred_type = schema_type or self._infer_schema_type(data)
        logger.info("Generating schema markup for type=%s", inferred_type)

        base: dict[str, Any] = {
            "@context": "https://schema.org",
            "@type": inferred_type,
        }

        if inferred_type == "Product":
            base.update(self._build_product_schema(data))
        elif inferred_type == "Review":
            base.update(self._build_review_schema(data))
        elif inferred_type == "Article":
            base.update(self._build_article_schema(data))
        elif inferred_type == "FAQPage":
            base.update(self._build_faq_schema(data))
        else:
            # Generic pass-through for unknown types
            base.update(data)

        logger.debug("Schema markup generated with %d top-level keys", len(base))
        return base

    def _infer_schema_type(self, data: dict[str, Any]) -> str:
        """Infer the schema.org type from the provided data keys.

        Args:
            data: The data dictionary to inspect.

        Returns:
            A schema.org type string.

        Raises:
            ValueError: If the type cannot be determined.
        """
        keys = set(data.keys())
        if "offers" in keys or ("name" in keys and "brand" in keys):
            return "Product"
        if "reviewBody" in keys or "ratingValue" in keys:
            return "Review"
        if "headline" in keys or "datePublished" in keys:
            return "Article"
        if "questions" in keys:
            return "FAQPage"
        raise ValueError(
            "Cannot infer schema type from data keys. "
            "Please provide schema_type explicitly."
        )

    def _build_product_schema(self, data: dict[str, Any]) -> dict[str, Any]:
        """Build Product schema fields from data.

        Args:
            data: Source data dictionary.

        Returns:
            Schema fields dict.
        """
        schema: dict[str, Any] = {
            "name": data.get("name", ""),
            "description": data.get("description", ""),
        }
        if "image" in data:
            schema["image"] = data["image"]
        if "brand" in data:
            schema["brand"] = {"@type": "Brand", "name": data["brand"]}
        if "offers" in data:
            offers = data["offers"]
            schema["offers"] = {
                "@type": "Offer",
                "price": offers.get("price", ""),
                "priceCurrency": offers.get("currency", "USD"),
                "availability": offers.get(
                    "availability", "https://schema.org/InStock"
                ),
                "url": offers.get("url", ""),
            }
        return schema

    def _build_review_schema(self, data: dict[str, Any]) -> dict[str, Any]:
        """Build Review schema fields from data.

        Args:
            data: Source data dictionary.

        Returns:
            Schema fields dict.
        """
        schema: dict[str, Any] = {
            "name": data.get("name", ""),
            "reviewBody": data.get("reviewBody", ""),
            "author": {"@type": "Person", "name": data.get("author", "")},
        }
        if "ratingValue" in data:
            schema["reviewRating"] = {
                "@type": "Rating",
                "ratingValue": data["ratingValue"],
                "bestRating": data.get("bestRating", 5),
            }
        if "itemReviewed" in data:
            schema["itemReviewed"] = data["itemReviewed"]
        return schema

    def _build_article_schema(self, data: dict[str, Any]) -> dict[str, Any]:
        """Build Article schema fields from data.

        Args:
            data: Source data dictionary.

        Returns:
            Schema fields dict.
        """
        schema: dict[str, Any] = {
            "headline": data.get("headline", ""),
            "description": data.get("description", ""),
            "author": {"@type": "Person", "name": data.get("author", "")},
            "datePublished": data.get("datePublished", ""),
        }
        if "image" in data:
            schema["image"] = data["image"]
        if "publisher" in data:
            schema["publisher"] = {
                "@type": "Organization",
                "name": data["publisher"],
            }
        return schema

    def _build_faq_schema(self, data: dict[str, Any]) -> dict[str, Any]:
        """Build FAQPage schema fields from data.

        Args:
            data: Source data dictionary with a "questions" list.

        Returns:
            Schema fields dict.
        """
        questions = data.get("questions", [])
        main_entity: list[dict[str, Any]] = []
        for q in questions:
            main_entity.append(
                {
                    "@type": "Question",
                    "name": q.get("question", ""),
                    "acceptedAnswer": {
                        "@type": "Answer",
                        "text": q.get("answer", ""),
                    },
                }
            )
        return {"mainEntity": main_entity}

    # ------------------------------------------------------------------
    # Competitor analysis
    # ------------------------------------------------------------------

    def analyze_competitors(
        self,
        keyword: str,
        num_competitors: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Analyze top-ranking competitors for a given keyword.

        Retrieves the top SERP results and enriches them with domain
        authority, estimated traffic, content length, backlink count, and
        on-page SEO signals.

        Args:
            keyword: The target keyword to analyze competition for.
            num_competitors: Number of competitors to analyze. Defaults to
                ``self.max_results``.

        Returns:
            A list of dicts, one per competitor, each containing:
                - rank (int): SERP position.
                - url (str): The ranking page URL.
                - domain (str): The root domain.
                - title (str): The page title.
                - domain_authority (float): Estimated DA score (0-100).
                - estimated_traffic (int): Estimated monthly organic traffic.
                - content_length (int): Word count of the page content.
                - backlinks (int): Number of backlinks to the page.
                - keyword_in_title (bool): Whether the keyword appears in
                  the page title.
                - keyword_in_h1 (bool): Whether the keyword appears in an H1.

        Raises:
            ValueError: If keyword is empty.
            ConnectionError: If the required APIs are unreachable.
        """
        if not keyword or not keyword.strip():
            raise ValueError("Keyword must not be empty")

        effective_num = num_competitors or self.max_results
        logger.info(
            "Analyzing top %d competitors for '%s'", effective_num, keyword
        )

        # Step 1: Get SERP results
        serp_data = self.check_serp(keyword, num_results=effective_num)

        competitors: list[dict[str, Any]] = []
        for idx, organic in enumerate(serp_data.get("organic_results", []), start=1):
            # TODO: Enrich each result with DA, backlinks, content metrics
            competitor: dict[str, Any] = {
                "rank": idx,
                "url": organic.get("url", ""),
                "domain": organic.get("domain", ""),
                "title": organic.get("title", ""),
                "domain_authority": 0.0,
                "estimated_traffic": 0,
                "content_length": 0,
                "backlinks": 0,
                "keyword_in_title": keyword.lower() in organic.get("title", "").lower(),
                "keyword_in_h1": False,
            }
            competitors.append(competitor)

        logger.debug(
            "Competitor analysis complete: %d competitors found", len(competitors)
        )
        return competitors
