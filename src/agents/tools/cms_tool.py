"""CMS Tool - Content management system integration for publishing workflows.

This module provides a unified interface for creating, updating, deleting,
and querying posts and media across CMS platforms (WordPress, Ghost, headless
CMS solutions, etc.). Designed for automated affiliate content publishing.
"""

import logging
import mimetypes
import os
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)


class CMSTool:
    """CMS integration tool for managing posts, media, and categories.

    Connects to a CMS via its REST API and exposes common CRUD operations
    needed for automated content publishing pipelines.

    Config keys:
        cms_type (str): CMS platform identifier
            (e.g. "wordpress", "ghost", "strapi", "custom").
        api_base_url (str): Base URL of the CMS REST API
            (e.g. "https://example.com/wp-json/wp/v2").
        api_key (str): Authentication token or application password.
        api_secret (str, optional): API secret for providers that require it.
        username (str, optional): Username for basic-auth CMS APIs.
        default_status (str): Default post status on creation
            (default "draft").
        default_author_id (int, optional): Default author ID for new posts.
        request_timeout (int): Timeout for API requests in seconds (default 30).
        verify_ssl (bool): Whether to verify SSL certificates (default True).
        max_retries (int): Max retry attempts for transient failures (default 3).
        retry_backoff (float): Base backoff in seconds between retries (default 1.0).
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

        # Connection settings
        self.cms_type: str = config.get("cms_type", "wordpress")
        self.api_base_url: str = config.get("api_base_url", "")
        self.api_key: str = config.get("api_key", "")
        self.api_secret: Optional[str] = config.get("api_secret")
        self.username: Optional[str] = config.get("username")

        # Publishing defaults
        self.default_status: str = config.get("default_status", "draft")
        self.default_author_id: Optional[int] = config.get("default_author_id")

        # Request settings
        self.request_timeout: int = config.get("request_timeout", 30)
        self.verify_ssl: bool = config.get("verify_ssl", True)
        self.max_retries: int = config.get("max_retries", 3)
        self.retry_backoff: float = config.get("retry_backoff", 1.0)

        # Session placeholder (lazily initialized)
        self._session: Optional[requests.Session] = None

        logger.info(
            "CMSTool initialized (cms_type=%s, api_base_url=%s)",
            self.cms_type,
            self.api_base_url,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_session(self) -> requests.Session:
        """Lazily create and return an HTTP session with authentication."""
        if self._session is None:
            logger.debug("Creating new HTTP session for CMS API")
            session = requests.Session()
            session.verify = self.verify_ssl

            # WordPress uses Basic Auth with username + application password
            if self.cms_type == "wordpress" and self.username and self.api_key:
                session.auth = (self.username, self.api_key)
            elif self.api_key:
                session.headers["Authorization"] = f"Bearer {self.api_key}"

            session.headers["User-Agent"] = "OpenClaw/0.1.0"
            session.headers["Accept"] = "application/json"

            self._session = session
        return self._session

    def _build_url(self, endpoint: str) -> str:
        """Construct a full API URL from a relative endpoint path."""
        base = self.api_base_url.rstrip("/")
        endpoint = endpoint.lstrip("/")
        return f"{base}/{endpoint}"

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        json_data: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
        data: Any = None,
        headers: Optional[dict[str, str]] = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Send an HTTP request with retry logic.

        Args:
            method: HTTP method (GET, POST, PATCH, DELETE).
            endpoint: Relative API path.
            json_data: JSON body payload.
            params: Query parameters.
            data: Raw body data (for file uploads).
            headers: Extra headers to merge.

        Returns:
            Parsed JSON response.

        Raises:
            RuntimeError: If the request fails after all retries.
        """
        session = self._get_session()
        url = self._build_url(endpoint)
        last_error: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = session.request(
                    method=method,
                    url=url,
                    json=json_data,
                    params=params,
                    data=data,
                    headers=headers,
                    timeout=self.request_timeout,
                )
                return self._handle_response(response)
            except requests.exceptions.ConnectionError as exc:
                last_error = exc
                logger.warning(
                    "Connection error on attempt %d/%d for %s %s: %s",
                    attempt,
                    self.max_retries,
                    method,
                    endpoint,
                    exc,
                )
            except requests.exceptions.Timeout as exc:
                last_error = exc
                logger.warning(
                    "Timeout on attempt %d/%d for %s %s: %s",
                    attempt,
                    self.max_retries,
                    method,
                    endpoint,
                    exc,
                )
            except RuntimeError:
                raise
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Request error on attempt %d/%d for %s %s: %s",
                    attempt,
                    self.max_retries,
                    method,
                    endpoint,
                    exc,
                )

            if attempt < self.max_retries:
                import time

                delay = self.retry_backoff * (2 ** (attempt - 1))
                logger.debug("Retrying in %.1fs", delay)
                time.sleep(delay)

        raise RuntimeError(
            f"CMS API request failed after {self.max_retries} attempts: "
            f"{method} {endpoint} — {last_error}"
        )

    def _handle_response(self, response: requests.Response) -> Any:
        """Validate an HTTP response and return parsed JSON.

        Raises:
            RuntimeError: If the response indicates an error (non-2xx status).
        """
        if response.status_code == 401:
            raise RuntimeError(
                f"CMS authentication failed (401). Check credentials. "
                f"Response: {response.text[:200]}"
            )
        if response.status_code == 403:
            raise RuntimeError(
                f"CMS permission denied (403). User may lack required role. "
                f"Response: {response.text[:200]}"
            )

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            raise RuntimeError(
                f"CMS API error ({response.status_code}): {response.text[:300]}"
            ) from exc

        if response.status_code == 204:
            return {}

        return response.json()

    def _normalize_wp_post(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Normalize a WordPress REST API post response to a standard format."""
        title = raw.get("title", {})
        if isinstance(title, dict):
            title = title.get("rendered", "")

        link = raw.get("link", "")
        return {
            "id": raw.get("id"),
            "url": link,
            "title": title,
            "slug": raw.get("slug", ""),
            "status": raw.get("status", ""),
            "created_at": raw.get("date", ""),
            "updated_at": raw.get("modified", ""),
        }

    # ------------------------------------------------------------------
    # Post management
    # ------------------------------------------------------------------

    def create_post(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new post in the CMS.

        Args:
            data: Post data with title, content, status, slug, etc.

        Returns:
            Normalized post dict with id, url, title, status, created_at.

        Raises:
            ValueError: If required fields are missing.
            RuntimeError: If the CMS API returns an error.
        """
        if not data.get("title"):
            raise ValueError("Post title is required")
        if not data.get("content"):
            raise ValueError("Post content is required")

        data.setdefault("status", self.default_status)
        if self.default_author_id and "author" not in data:
            data["author"] = self.default_author_id

        logger.info(
            "Creating post: title='%s', status='%s'",
            data["title"],
            data["status"],
        )

        result = self._request("POST", "/posts", json_data=data)
        if isinstance(result, dict):
            return self._normalize_wp_post(result)
        raise RuntimeError(
            "Unexpected WP response shape: expected dict for create_post"
        )

    def update_post(self, post_id: int, data: dict[str, Any]) -> dict[str, Any]:
        """Update an existing post in the CMS.

        Args:
            post_id: The ID of the post to update.
            data: Fields to update.

        Returns:
            Normalized updated post dict.
        """
        if not isinstance(post_id, int) or post_id <= 0:
            raise ValueError(f"Invalid post_id: {post_id}")

        logger.info("Updating post %d with %d field(s)", post_id, len(data))
        result = self._request("PATCH", f"/posts/{post_id}", json_data=data)
        if isinstance(result, dict):
            return self._normalize_wp_post(result)
        raise RuntimeError(
            "Unexpected WP response shape: expected dict for update_post"
        )

    def delete_post(self, post_id: int, force: bool = False) -> bool:
        """Delete (or trash) a post from the CMS.

        Args:
            post_id: The ID of the post to delete.
            force: If True, permanently delete instead of trashing.

        Returns:
            True if successful.
        """
        if not isinstance(post_id, int) or post_id <= 0:
            raise ValueError(f"Invalid post_id: {post_id}")

        logger.info("Deleting post %d (force=%s)", post_id, force)
        self._request("DELETE", f"/posts/{post_id}", params={"force": force})
        return True

    def get_posts(
        self, filters: Optional[dict[str, Any]] = None
    ) -> list[dict[str, Any]]:
        """Retrieve posts from the CMS, optionally filtered.

        Args:
            filters: Query parameters (status, search, per_page, page, etc.)

        Returns:
            List of normalized post dicts.
        """
        filters = filters or {}
        logger.info("Fetching posts with filters: %s", filters)

        result = self._request("GET", "/posts", params=filters)
        if isinstance(result, list):
            return [self._normalize_wp_post(p) for p in result]
        return []

    # ------------------------------------------------------------------
    # Media management
    # ------------------------------------------------------------------

    def upload_media(
        self,
        file_path: str,
        title: Optional[str] = None,
        alt_text: Optional[str] = None,
        caption: Optional[str] = None,
    ) -> str:
        """Upload a media file to the CMS.

        Args:
            file_path: Local path to the file.
            title: Optional title for the media item.
            alt_text: Optional alt text.
            caption: Optional caption.

        Returns:
            The public URL of the uploaded media.
        """
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"Media file not found: {file_path}")

        filename = os.path.basename(file_path)
        mime_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        logger.info("Uploading media: %s (%s)", filename, mime_type)

        with open(file_path, "rb") as f:
            file_data = f.read()

        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": mime_type,
        }
        result = self._request("POST", "/media", data=file_data, headers=headers)

        if isinstance(result, dict):
            url = result.get("source_url") or result.get("url") or ""
            # Set alt text if provided
            if alt_text and result.get("id"):
                try:
                    self._request(
                        "PATCH",
                        f"/media/{result['id']}",
                        json_data={"alt_text": alt_text},
                    )
                except Exception as exc:
                    logger.warning("Failed to set alt text: %s", exc)
            return str(url)
        return ""

    # ------------------------------------------------------------------
    # Category / taxonomy management
    # ------------------------------------------------------------------

    def get_categories(self, parent_id: Optional[int] = None) -> list[dict[str, Any]]:
        """Retrieve categories from the CMS.

        Args:
            parent_id: If provided, only return child categories.

        Returns:
            List of category dicts with id, name, slug, parent, count.
        """
        logger.info("Fetching categories (parent_id=%s)", parent_id)
        params: dict[str, Any] = {"per_page": 100}
        if parent_id is not None:
            params["parent"] = parent_id

        result = self._request("GET", "/categories", params=params)
        if isinstance(result, list):
            return result
        return []

    def ensure_category(self, name: str) -> int:
        """Get or create a category by name. Returns the category ID.

        Args:
            name: Category name to find or create.

        Returns:
            The category ID (int).
        """
        categories = self._request("GET", "/categories", params={"search": name})
        if isinstance(categories, list):
            for cat in categories:
                if cat.get("name", "").lower() == name.lower():
                    return cat["id"]

        # Create it
        result = self._request("POST", "/categories", json_data={"name": name})
        if isinstance(result, dict):
            return result["id"]
        raise RuntimeError(f"Failed to create category: {name}")

    def ensure_tag(self, name: str) -> int:
        """Get or create a tag by name. Returns the tag ID.

        Args:
            name: Tag name to find or create.

        Returns:
            The tag ID (int).
        """
        tags = self._request("GET", "/tags", params={"search": name})
        if isinstance(tags, list):
            for tag in tags:
                if tag.get("name", "").lower() == name.lower():
                    return tag["id"]

        result = self._request("POST", "/tags", json_data={"name": name})
        if isinstance(result, dict):
            return result["id"]
        raise RuntimeError(f"Failed to create tag: {name}")
