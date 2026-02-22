"""Link Tool - Affiliate link management and validation utilities.

This module provides methods for validating URLs, constructing affiliate links
with tracking tags, discovering internal linking opportunities within content,
and auditing existing links for broken or redirected destinations.
"""

import logging
import re
from typing import Any, Optional
from urllib.parse import urlencode, urlparse, urlunparse, parse_qs

logger = logging.getLogger(__name__)


class LinkTool:
    """Link management toolkit for affiliate content workflows.

    Handles affiliate link construction, link validation, broken-link
    checking, and internal link opportunity discovery.

    Config keys:
        default_affiliate_tag (str): Default affiliate tracking tag/ID.
        affiliate_networks (dict, optional): Mapping of network names to
            their link template patterns. Example::

                {
                    "amazon": "https://www.amazon.com/dp/{asin}?tag={tag}",
                    "shareasale": "https://www.shareasale.com/r.cfm?u={user_id}&b={banner_id}&m={merchant_id}",
                }

        link_check_timeout (int): Timeout for HTTP HEAD requests when
            validating links (default 10 seconds).
        link_check_user_agent (str): User-Agent header used for link
            checking requests.
        max_concurrent_checks (int): Maximum concurrent HTTP requests when
            batch-checking links (default 10).
        nofollow_external (bool): Whether external links should carry
            rel="nofollow" (default True).
        internal_domains (list[str]): List of domains treated as internal
            (e.g. ["example.com", "www.example.com"]).
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize the link tool with affiliate and validation settings.

        Args:
            config: Dictionary containing affiliate network settings,
                validation preferences, and internal domain list.
                See class docstring for supported keys.
        """
        self.config = config

        # Affiliate settings
        self.default_affiliate_tag: str = config.get("default_affiliate_tag", "")
        self.affiliate_networks: dict[str, str] = config.get("affiliate_networks", {})

        # Link checking settings
        self.link_check_timeout: int = config.get("link_check_timeout", 10)
        self.link_check_user_agent: str = config.get(
            "link_check_user_agent",
            "AffiliateWhiz-LinkChecker/1.0",
        )
        self.max_concurrent_checks: int = config.get("max_concurrent_checks", 10)

        # Content settings
        self.nofollow_external: bool = config.get("nofollow_external", True)
        self.internal_domains: list[str] = config.get("internal_domains", [])

        logger.info(
            "LinkTool initialized (default_tag=%s, internal_domains=%d, networks=%d)",
            self.default_affiliate_tag or "(none)",
            len(self.internal_domains),
            len(self.affiliate_networks),
        )

    # ------------------------------------------------------------------
    # URL validation
    # ------------------------------------------------------------------

    def validate_link(self, url: str, follow_redirects: bool = True) -> bool:
        """Check whether a URL is reachable and returns a successful status.

        Sends an HTTP HEAD request (falling back to GET if HEAD is rejected)
        and considers any 2xx or 3xx status as valid.

        Args:
            url: The URL to validate.
            follow_redirects: Whether to follow redirects when checking.
                Default True.

        Returns:
            True if the URL is reachable and returns a successful HTTP status,
            False otherwise.
        """
        if not url or not url.strip():
            logger.warning("validate_link called with empty URL")
            return False

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            logger.warning("Invalid scheme '%s' for URL: %s", parsed.scheme, url)
            return False

        logger.debug("Validating link: %s", url)

        # TODO: Implement HTTP HEAD/GET request
        # try:
        #     import requests
        #     resp = requests.head(
        #         url,
        #         timeout=self.link_check_timeout,
        #         allow_redirects=follow_redirects,
        #         headers={"User-Agent": self.link_check_user_agent},
        #     )
        #     if resp.status_code >= 400:
        #         # Retry with GET in case the server rejects HEAD
        #         resp = requests.get(
        #             url,
        #             timeout=self.link_check_timeout,
        #             allow_redirects=follow_redirects,
        #             headers={"User-Agent": self.link_check_user_agent},
        #             stream=True,
        #         )
        #         resp.close()
        #     return resp.status_code < 400
        # except requests.RequestException as exc:
        #     logger.debug("Link validation failed for %s: %s", url, exc)
        #     return False
        raise NotImplementedError("validate_link HTTP request not yet implemented")

    # ------------------------------------------------------------------
    # Affiliate link construction
    # ------------------------------------------------------------------

    def build_affiliate_link(
        self,
        url: str,
        tag: Optional[str] = None,
        network: Optional[str] = None,
        extra_params: Optional[dict[str, str]] = None,
    ) -> str:
        """Construct an affiliate link by appending a tracking tag to a URL.

        If a known affiliate network is specified, the link is built using
        the corresponding template. Otherwise the tag is appended as a query
        parameter.

        Args:
            url: The destination URL (product page, landing page, etc.).
            tag: Affiliate tracking tag. Falls back to
                ``self.default_affiliate_tag`` if not provided.
            network: Optional affiliate network name (e.g. "amazon"). When
                provided, the URL is constructed using the template in
                ``self.affiliate_networks``.
            extra_params: Additional query parameters to append.

        Returns:
            The fully constructed affiliate URL string.

        Raises:
            ValueError: If the URL is empty or the tag is missing and no
                default is configured.
        """
        if not url or not url.strip():
            raise ValueError("URL must not be empty")

        effective_tag = tag or self.default_affiliate_tag
        if not effective_tag:
            raise ValueError(
                "An affiliate tag is required. Provide one explicitly or "
                "set 'default_affiliate_tag' in the config."
            )

        logger.info("Building affiliate link for %s (tag=%s)", url, effective_tag)

        # Network-specific template building
        if network and network in self.affiliate_networks:
            template = self.affiliate_networks[network]
            params = {"tag": effective_tag, "url": url}
            if extra_params:
                params.update(extra_params)
            try:
                affiliate_url = template.format(**params)
                logger.debug("Built network link: %s", affiliate_url)
                return affiliate_url
            except KeyError as exc:
                logger.warning(
                    "Template for network '%s' requires key %s; falling back "
                    "to query-param method",
                    network,
                    exc,
                )

        # Generic approach: append tag as a query parameter
        parsed = urlparse(url)
        existing_params = parse_qs(parsed.query)
        new_params: dict[str, str] = {}
        # Flatten existing multi-value params to single values
        for key, values in existing_params.items():
            new_params[key] = values[0]
        new_params["tag"] = effective_tag
        if extra_params:
            new_params.update(extra_params)

        new_query = urlencode(new_params)
        affiliate_url = urlunparse(parsed._replace(query=new_query))

        logger.debug("Built affiliate link: %s", affiliate_url)
        return affiliate_url

    # ------------------------------------------------------------------
    # Internal linking
    # ------------------------------------------------------------------

    def find_internal_link_opportunities(
        self,
        content: str,
        existing_posts: list[dict[str, Any]],
        max_links_per_post: int = 3,
        min_keyword_length: int = 3,
    ) -> list[dict[str, Any]]:
        """Identify opportunities to add internal links within content.

        Scans the provided content for mentions of keywords/phrases that
        match titles or focus keywords of existing posts, suggesting where
        internal links could be inserted.

        Args:
            content: The HTML or plain text content to scan for link
                opportunities.
            existing_posts: A list of post dicts, each expected to contain:
                - id (int): Post identifier.
                - title (str): Post title.
                - url (str): Post permalink.
                - keywords (list[str], optional): Focus keywords for the post.
            max_links_per_post: Maximum number of link suggestions to return
                per existing post (avoids over-linking to a single target).
            min_keyword_length: Minimum character length for a keyword to be
                considered (filters out very short matches).

        Returns:
            A list of opportunity dicts, each containing:
                - target_post_id (int): The ID of the post to link to.
                - target_url (str): The URL of the post to link to.
                - target_title (str): Title of the target post.
                - anchor_text (str): The matched text in the content that
                  could serve as anchor text.
                - match_position (int): Character offset in ``content``
                  where the match was found.
                - confidence (float): 0.0-1.0 confidence that this is a
                  good linking opportunity.
        """
        if not content or not content.strip():
            logger.warning("find_internal_link_opportunities called with empty content")
            return []

        if not existing_posts:
            logger.debug("No existing posts provided; no opportunities to find")
            return []

        logger.info(
            "Scanning content (%d chars) against %d existing posts",
            len(content),
            len(existing_posts),
        )

        content_lower = content.lower()
        opportunities: list[dict[str, Any]] = []

        for post in existing_posts:
            post_id: int = post.get("id", 0)
            post_url: str = post.get("url", "")
            post_title: str = post.get("title", "")
            keywords: list[str] = post.get("keywords", [])

            # Combine title words and explicit keywords as match candidates
            candidates: list[str] = list(keywords)
            if post_title:
                candidates.append(post_title)

            matches_for_post = 0
            for candidate in candidates:
                if len(candidate) < min_keyword_length:
                    continue

                pattern = re.compile(
                    r"\b" + re.escape(candidate.lower()) + r"\b"
                )
                for match in pattern.finditer(content_lower):
                    if matches_for_post >= max_links_per_post:
                        break

                    # Extract the original-case text from the content
                    start, end = match.start(), match.end()
                    anchor_text = content[start:end]

                    confidence = self._score_link_opportunity(
                        anchor_text=anchor_text,
                        candidate=candidate,
                        post_title=post_title,
                    )

                    opportunities.append(
                        {
                            "target_post_id": post_id,
                            "target_url": post_url,
                            "target_title": post_title,
                            "anchor_text": anchor_text,
                            "match_position": start,
                            "confidence": confidence,
                        }
                    )
                    matches_for_post += 1

        # Sort by confidence descending
        opportunities.sort(key=lambda x: x["confidence"], reverse=True)
        logger.debug("Found %d internal link opportunities", len(opportunities))
        return opportunities

    def _score_link_opportunity(
        self,
        anchor_text: str,
        candidate: str,
        post_title: str,
    ) -> float:
        """Compute a confidence score for a potential internal link.

        Args:
            anchor_text: The matched text in the source content.
            candidate: The keyword or phrase that was matched.
            post_title: The title of the target post.

        Returns:
            A float between 0.0 and 1.0 representing match confidence.
        """
        score = 0.5  # Base score for a keyword match

        # Boost for exact title match
        if anchor_text.lower() == post_title.lower():
            score += 0.3

        # Boost for longer anchor text (more specific)
        if len(anchor_text) > 20:
            score += 0.1

        # Boost for multi-word matches
        if " " in anchor_text:
            score += 0.1

        return min(score, 1.0)

    # ------------------------------------------------------------------
    # Broken link checking
    # ------------------------------------------------------------------

    def check_broken_links(
        self,
        urls: list[str],
        concurrency: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Check a batch of URLs for broken or problematic links.

        Performs HTTP HEAD requests (with GET fallback) against every URL
        and categorizes results by status.

        Args:
            urls: List of URLs to check.
            concurrency: Maximum number of concurrent checks. Defaults to
                ``self.max_concurrent_checks``.

        Returns:
            A list of dicts, one per URL, each containing:
                - url (str): The checked URL.
                - status_code (int | None): HTTP status code, or None if
                  the request failed entirely.
                - is_broken (bool): True if the URL is unreachable or
                  returns a 4xx/5xx status.
                - redirect_url (str | None): Final URL after redirects,
                  if different from the original.
                - error (str | None): Error message if the check failed.
                - response_time_ms (float | None): Round-trip time in
                  milliseconds.
        """
        if not urls:
            logger.debug("check_broken_links called with empty URL list")
            return []

        effective_concurrency = concurrency or self.max_concurrent_checks
        logger.info(
            "Checking %d links for broken URLs (concurrency=%d)",
            len(urls),
            effective_concurrency,
        )

        results: list[dict[str, Any]] = []

        for url in urls:
            # TODO: Replace with concurrent HTTP HEAD/GET checks
            # (e.g. using asyncio + aiohttp, or concurrent.futures)
            result: dict[str, Any] = {
                "url": url,
                "status_code": None,
                "is_broken": True,
                "redirect_url": None,
                "error": "Link checking not yet implemented",
                "response_time_ms": None,
            }
            results.append(result)

        broken_count = sum(1 for r in results if r["is_broken"])
        logger.info(
            "Link check complete: %d/%d broken", broken_count, len(results)
        )
        return results
