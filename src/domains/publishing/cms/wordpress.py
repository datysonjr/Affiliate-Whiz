"""
domains.publishing.cms.wordpress
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

WordPress CMS integration via the WordPress REST API (v2).

Provides the :class:`WordPressCMS` class for creating, updating, and
managing posts on a WordPress site.  Authentication uses Application
Passwords (WordPress 5.6+) or JWT tokens.

All methods handle pagination, media uploads, and category/tag
management through the standard WordPress REST API endpoints.

Design references:
    - https://developer.wordpress.org/rest-api/reference/
    - ARCHITECTURE.md  Section 4 (Publishing Domain)
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from src.core.constants import DEFAULT_REQUEST_TIMEOUT
from src.core.errors import CMSConnectionError, IntegrationError, PublishingError
from src.core.logger import get_logger

# ---------------------------------------------------------------------------
# Optional dependency: requests
# ---------------------------------------------------------------------------
try:
    import requests  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class WPPost:
    """Represents a WordPress post returned by the REST API.

    Attributes
    ----------
    id:
        WordPress post ID.
    title:
        Post title.
    slug:
        URL slug.
    content:
        Full HTML content.
    excerpt:
        Post excerpt.
    status:
        Post status (``"publish"``, ``"draft"``, ``"pending"``, etc.).
    categories:
        List of category IDs.
    tags:
        List of tag IDs.
    featured_media:
        ID of the featured image media attachment.
    link:
        Public permalink URL.
    date_published:
        Publication date as ISO string.
    date_modified:
        Last modification date as ISO string.
    metadata:
        Additional fields from the API response.
    """

    id: int = 0
    title: str = ""
    slug: str = ""
    content: str = ""
    excerpt: str = ""
    status: str = "draft"
    categories: List[int] = field(default_factory=list)
    tags: List[int] = field(default_factory=list)
    featured_media: int = 0
    link: str = ""
    date_published: str = ""
    date_modified: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WPCategory:
    """Represents a WordPress category.

    Attributes
    ----------
    id:
        Category ID.
    name:
        Category name.
    slug:
        URL-safe slug.
    description:
        Category description.
    parent:
        Parent category ID (0 for top-level).
    count:
        Number of posts in this category.
    """

    id: int = 0
    name: str = ""
    slug: str = ""
    description: str = ""
    parent: int = 0
    count: int = 0


@dataclass
class WPMedia:
    """Represents a WordPress media attachment.

    Attributes
    ----------
    id:
        Media ID.
    title:
        Media title.
    source_url:
        Full URL to the uploaded file.
    mime_type:
        MIME type of the file.
    alt_text:
        Alt text for accessibility.
    """

    id: int = 0
    title: str = ""
    source_url: str = ""
    mime_type: str = ""
    alt_text: str = ""


# ---------------------------------------------------------------------------
# WordPress CMS client
# ---------------------------------------------------------------------------

class WordPressCMS:
    """Client for managing content on a WordPress site via the REST API.

    Authentication uses HTTP Basic Auth with Application Passwords, which
    is the recommended method for WordPress 5.6+.  All API calls go
    through the ``/wp-json/wp/v2/`` namespace.

    Parameters
    ----------
    site_url:
        Base URL of the WordPress site (e.g. ``"https://example.com"``).
    username:
        WordPress username.
    app_password:
        Application password (not the user's login password).
    timeout:
        Per-request timeout in seconds.

    Raises
    ------
    IntegrationError
        If the ``requests`` library is not installed.
    """

    def __init__(
        self,
        site_url: str,
        username: str,
        app_password: str,
        timeout: int = DEFAULT_REQUEST_TIMEOUT,
    ) -> None:
        if requests is None:
            raise IntegrationError(
                "The 'requests' package is required for WordPressCMS. "
                "Install it with: pip install requests"
            )

        self.site_url = site_url.rstrip("/")
        self.api_base = f"{self.site_url}/wp-json/wp/v2"
        self.timeout = timeout
        self.logger: logging.Logger = get_logger("publishing.cms.wordpress")

        self._session = requests.Session()
        # HTTP Basic Auth with Application Password
        credentials = base64.b64encode(
            f"{username}:{app_password}".encode("utf-8")
        ).decode("utf-8")
        self._session.headers.update({
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

        self._connected = False

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Test the connection to the WordPress REST API.

        Verifies that the API is reachable and that the credentials are
        accepted by fetching the authenticated user profile.

        Returns
        -------
        bool
            ``True`` if the connection and authentication succeeded.

        Raises
        ------
        CMSConnectionError
            If the API is unreachable or credentials are rejected.
        """
        try:
            response = self._session.get(
                f"{self.site_url}/wp-json/wp/v2/users/me",
                timeout=self.timeout,
            )
            response.raise_for_status()
            user_data = response.json()
            self._connected = True
            self.logger.info(
                "Connected to WordPress at %s as user '%s'",
                self.site_url,
                user_data.get("name", "unknown"),
            )
            return True
        except Exception as exc:
            self._connected = False
            raise CMSConnectionError(
                f"Failed to connect to WordPress at {self.site_url}",
                details={"site_url": self.site_url},
                cause=exc,
            ) from exc

    # ------------------------------------------------------------------
    # Posts
    # ------------------------------------------------------------------

    def create_post(
        self,
        title: str,
        content: str,
        *,
        status: str = "draft",
        slug: str = "",
        excerpt: str = "",
        categories: Optional[List[int]] = None,
        tags: Optional[List[int]] = None,
        featured_media: int = 0,
        meta: Optional[Dict[str, Any]] = None,
    ) -> WPPost:
        """Create a new post on the WordPress site.

        Parameters
        ----------
        title:
            Post title.
        content:
            Full HTML content.
        status:
            Post status: ``"draft"``, ``"publish"``, ``"pending"``, or
            ``"private"``.
        slug:
            URL slug (auto-generated from title if empty).
        excerpt:
            Short excerpt for listings and meta descriptions.
        categories:
            List of category IDs to assign.
        tags:
            List of tag IDs to assign.
        featured_media:
            Media ID for the featured image.
        meta:
            Custom meta fields to set on the post.

        Returns
        -------
        WPPost
            The created post.

        Raises
        ------
        PublishingError
            If the API returns an error.
        """
        payload: Dict[str, Any] = {
            "title": title,
            "content": content,
            "status": status,
        }

        if slug:
            payload["slug"] = slug
        if excerpt:
            payload["excerpt"] = excerpt
        if categories:
            payload["categories"] = categories
        if tags:
            payload["tags"] = tags
        if featured_media:
            payload["featured_media"] = featured_media
        if meta:
            payload["meta"] = meta

        data = self._api_request("POST", "/posts", json_data=payload)
        post = self._parse_post(data)

        self.logger.info("Created post #%d: '%s' (status=%s)", post.id, post.title, post.status)
        return post

    def update_post(
        self,
        post_id: int,
        *,
        title: Optional[str] = None,
        content: Optional[str] = None,
        status: Optional[str] = None,
        slug: Optional[str] = None,
        excerpt: Optional[str] = None,
        categories: Optional[List[int]] = None,
        tags: Optional[List[int]] = None,
        featured_media: Optional[int] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> WPPost:
        """Update an existing post.

        Only fields that are explicitly provided (not ``None``) are sent
        in the update request.  All other fields remain unchanged.

        Parameters
        ----------
        post_id:
            WordPress post ID to update.
        title:
            New title.
        content:
            New content.
        status:
            New status.
        slug:
            New slug.
        excerpt:
            New excerpt.
        categories:
            New category list.
        tags:
            New tag list.
        featured_media:
            New featured image media ID.
        meta:
            Updated meta fields.

        Returns
        -------
        WPPost
            The updated post.

        Raises
        ------
        PublishingError
            If the API returns an error.
        """
        payload: Dict[str, Any] = {}

        if title is not None:
            payload["title"] = title
        if content is not None:
            payload["content"] = content
        if status is not None:
            payload["status"] = status
        if slug is not None:
            payload["slug"] = slug
        if excerpt is not None:
            payload["excerpt"] = excerpt
        if categories is not None:
            payload["categories"] = categories
        if tags is not None:
            payload["tags"] = tags
        if featured_media is not None:
            payload["featured_media"] = featured_media
        if meta is not None:
            payload["meta"] = meta

        data = self._api_request("POST", f"/posts/{post_id}", json_data=payload)
        post = self._parse_post(data)

        self.logger.info("Updated post #%d: '%s'", post.id, post.title)
        return post

    def delete_post(
        self,
        post_id: int,
        *,
        force: bool = False,
    ) -> bool:
        """Delete a post.

        Parameters
        ----------
        post_id:
            WordPress post ID to delete.
        force:
            If ``True``, permanently delete (bypass trash).

        Returns
        -------
        bool
            ``True`` if the deletion succeeded.

        Raises
        ------
        PublishingError
            If the API returns an error.
        """
        params = {"force": "true"} if force else {}
        self._api_request("DELETE", f"/posts/{post_id}", params=params)
        self.logger.info("Deleted post #%d (force=%s)", post_id, force)
        return True

    # ------------------------------------------------------------------
    # Media
    # ------------------------------------------------------------------

    def upload_media(
        self,
        file_path: str,
        *,
        title: str = "",
        alt_text: str = "",
        caption: str = "",
    ) -> WPMedia:
        """Upload a media file (image, video, etc.) to the WordPress media library.

        Parameters
        ----------
        file_path:
            Local filesystem path to the file.
        title:
            Media title.
        alt_text:
            Alt text for accessibility and SEO.
        caption:
            Media caption.

        Returns
        -------
        WPMedia
            The created media attachment.

        Raises
        ------
        PublishingError
            If the upload fails.
        FileNotFoundError
            If the file does not exist.
        """
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Media file not found: {file_path}")

        filename = path.name
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

        with open(file_path, "rb") as fh:
            file_data = fh.read()

        # WordPress media upload uses multipart form, not JSON
        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": mime_type,
        }

        try:
            response = self._session.post(
                f"{self.api_base}/media",
                data=file_data,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            raise PublishingError(
                f"Failed to upload media: {filename}",
                details={"file_path": file_path, "mime_type": mime_type},
                cause=exc,
            ) from exc

        media = WPMedia(
            id=data.get("id", 0),
            title=data.get("title", {}).get("rendered", filename),
            source_url=data.get("source_url", ""),
            mime_type=data.get("mime_type", mime_type),
            alt_text=alt_text,
        )

        # Set alt text if provided
        if alt_text:
            try:
                self._api_request("POST", f"/media/{media.id}", json_data={
                    "alt_text": alt_text,
                    "caption": caption,
                })
            except PublishingError:
                self.logger.warning("Failed to set alt text for media #%d", media.id)

        self.logger.info(
            "Uploaded media #%d: '%s' (%s)", media.id, filename, mime_type
        )
        return media

    # ------------------------------------------------------------------
    # Categories
    # ------------------------------------------------------------------

    def get_categories(
        self,
        *,
        per_page: int = 100,
        search: str = "",
    ) -> List[WPCategory]:
        """Retrieve categories from the WordPress site.

        Parameters
        ----------
        per_page:
            Number of categories per page (max 100).
        search:
            Optional search term to filter categories.

        Returns
        -------
        list[WPCategory]
            List of categories.
        """
        params: Dict[str, Any] = {"per_page": min(per_page, 100)}
        if search:
            params["search"] = search

        data = self._api_request("GET", "/categories", params=params)
        categories: List[WPCategory] = []

        if isinstance(data, list):
            for item in data:
                categories.append(WPCategory(
                    id=item.get("id", 0),
                    name=item.get("name", ""),
                    slug=item.get("slug", ""),
                    description=item.get("description", ""),
                    parent=item.get("parent", 0),
                    count=item.get("count", 0),
                ))

        self.logger.debug("Retrieved %d categories", len(categories))
        return categories

    def create_category(
        self,
        name: str,
        *,
        slug: str = "",
        description: str = "",
        parent: int = 0,
    ) -> WPCategory:
        """Create a new category.

        Parameters
        ----------
        name:
            Category name.
        slug:
            URL slug (auto-generated if empty).
        description:
            Category description.
        parent:
            Parent category ID (0 for top-level).

        Returns
        -------
        WPCategory
            The created category.

        Raises
        ------
        PublishingError
            If the API returns an error.
        """
        payload: Dict[str, Any] = {"name": name}
        if slug:
            payload["slug"] = slug
        if description:
            payload["description"] = description
        if parent:
            payload["parent"] = parent

        data = self._api_request("POST", "/categories", json_data=payload)

        category = WPCategory(
            id=data.get("id", 0),
            name=data.get("name", name),
            slug=data.get("slug", ""),
            description=data.get("description", ""),
            parent=data.get("parent", 0),
            count=0,
        )

        self.logger.info("Created category #%d: '%s'", category.id, category.name)
        return category

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _api_request(
        self,
        method: str,
        endpoint: str,
        *,
        json_data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Make an authenticated request to the WordPress REST API.

        Parameters
        ----------
        method:
            HTTP method (``"GET"``, ``"POST"``, ``"DELETE"``).
        endpoint:
            API endpoint path (e.g. ``"/posts"``).
        json_data:
            JSON request body.
        params:
            URL query parameters.

        Returns
        -------
        Any
            Parsed JSON response.

        Raises
        ------
        PublishingError
            If the request fails.
        """
        url = f"{self.api_base}{endpoint}"

        try:
            response = self._session.request(
                method=method,
                url=url,
                json=json_data,
                params=params,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            raise PublishingError(
                f"WordPress API request failed: {method} {endpoint}",
                details={
                    "method": method,
                    "endpoint": endpoint,
                    "url": url,
                    "status_code": getattr(
                        getattr(exc, "response", None), "status_code", None
                    ),
                },
                cause=exc,
            ) from exc

    @staticmethod
    def _parse_post(data: Dict[str, Any]) -> WPPost:
        """Parse a WordPress REST API post response into a WPPost.

        Parameters
        ----------
        data:
            Raw API response dict.

        Returns
        -------
        WPPost
            Parsed post object.
        """
        return WPPost(
            id=data.get("id", 0),
            title=data.get("title", {}).get("rendered", ""),
            slug=data.get("slug", ""),
            content=data.get("content", {}).get("rendered", ""),
            excerpt=data.get("excerpt", {}).get("rendered", ""),
            status=data.get("status", "draft"),
            categories=data.get("categories", []),
            tags=data.get("tags", []),
            featured_media=data.get("featured_media", 0),
            link=data.get("link", ""),
            date_published=data.get("date", ""),
            date_modified=data.get("modified", ""),
            metadata={
                k: v for k, v in data.items()
                if k not in {
                    "id", "title", "slug", "content", "excerpt", "status",
                    "categories", "tags", "featured_media", "link", "date",
                    "modified",
                }
            },
        )

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self._session.close()
        self._connected = False
        self.logger.debug("WordPress CMS session closed")

    @property
    def is_connected(self) -> bool:
        """Return ``True`` if the client has successfully connected."""
        return self._connected

    def __repr__(self) -> str:
        return (
            f"WordPressCMS(site={self.site_url!r}, connected={self._connected})"
        )
