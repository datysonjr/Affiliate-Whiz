"""
domains.publishing.cms.headless
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Abstract interface for headless CMS integrations.

Defines the :class:`HeadlessCMS` abstract base class that all headless CMS
backends must implement.  This allows the publishing pipeline to interact
with any headless CMS (Strapi, Contentful, Sanity, Ghost, etc.) through a
uniform API without coupling to a specific vendor.

The interface covers the full content lifecycle: creation, retrieval, update,
deletion, media management, and content-type introspection.

Design references:
    - ARCHITECTURE.md  Section 4 (Publishing Domain)
    - config/providers.yaml  ``cms`` section
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.core.constants import DEFAULT_REQUEST_TIMEOUT
from src.core.logger import get_logger

logger = get_logger("publishing.cms.headless")


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class CMSContent:
    """Generic content record returned by a headless CMS.

    Attributes
    ----------
    content_id:
        CMS-assigned content identifier (may be a string UUID or integer).
    content_type:
        The CMS content-type slug (e.g. ``"article"``, ``"product-review"``).
    title:
        Content title / headline.
    slug:
        URL-safe slug for routing.
    body:
        Full content body (typically HTML or Markdown).
    status:
        Publication status (``"draft"``, ``"published"``, ``"archived"``).
    locale:
        Content locale code (e.g. ``"en-US"``).
    author:
        Author identifier or display name.
    fields:
        Custom field data as a flat dictionary.
    created_at:
        UTC creation timestamp.
    updated_at:
        UTC last-modification timestamp.
    published_at:
        UTC publication timestamp (``None`` if not yet published).
    metadata:
        Additional CMS-specific metadata.
    """

    content_id: str
    content_type: str = ""
    title: str = ""
    slug: str = ""
    body: str = ""
    status: str = "draft"
    locale: str = "en-US"
    author: str = ""
    fields: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CMSMedia:
    """Generic media asset record returned by a headless CMS.

    Attributes
    ----------
    media_id:
        CMS-assigned media identifier.
    filename:
        Original filename of the uploaded asset.
    url:
        Public URL for the asset.
    mime_type:
        MIME type (e.g. ``"image/jpeg"``).
    size_bytes:
        File size in bytes.
    alt_text:
        Alternative text for accessibility.
    width:
        Image width in pixels (0 for non-image assets).
    height:
        Image height in pixels (0 for non-image assets).
    created_at:
        UTC upload timestamp.
    """

    media_id: str
    filename: str = ""
    url: str = ""
    mime_type: str = ""
    size_bytes: int = 0
    alt_text: str = ""
    width: int = 0
    height: int = 0
    created_at: Optional[datetime] = None


@dataclass
class ContentType:
    """Schema description of a content type in the headless CMS.

    Attributes
    ----------
    name:
        Human-readable content-type name.
    slug:
        API-safe identifier (e.g. ``"product-review"``).
    fields:
        List of field definitions, each a dict with at least
        ``"name"`` and ``"type"`` keys.
    description:
        Optional description of the content type's purpose.
    """

    name: str
    slug: str = ""
    fields: List[Dict[str, Any]] = field(default_factory=list)
    description: str = ""


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------

class HeadlessCMS(ABC):
    """Abstract interface for headless CMS integrations.

    Subclasses implement vendor-specific API calls while the publishing
    pipeline interacts only with this interface, ensuring portability
    across CMS backends.

    Parameters
    ----------
    cms_name:
        Human-readable CMS name (e.g. ``"strapi"``, ``"contentful"``).
    base_url:
        API base URL of the CMS instance.
    api_key:
        Authentication token or API key.
    timeout:
        Per-request HTTP timeout in seconds.
    """

    def __init__(
        self,
        cms_name: str,
        base_url: str,
        api_key: str,
        timeout: int = DEFAULT_REQUEST_TIMEOUT,
    ) -> None:
        self._cms_name = cms_name
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._request_count: int = 0
        self.logger = get_logger(f"publishing.cms.{cms_name}")

    def _track_request(self) -> None:
        """Record that an API request was made."""
        self._request_count += 1

    # ------------------------------------------------------------------
    # Content CRUD
    # ------------------------------------------------------------------

    @abstractmethod
    async def create_content(
        self,
        content_type: str,
        data: Dict[str, Any],
        *,
        status: str = "draft",
        locale: str = "en-US",
    ) -> CMSContent:
        """Create a new content entry in the CMS.

        Parameters
        ----------
        content_type:
            Content-type slug that determines the schema.
        data:
            Field values for the new content entry.
        status:
            Initial publication status.
        locale:
            Content locale for internationalised CMS setups.

        Returns
        -------
        CMSContent
            The created content record.

        Raises
        ------
        PublishingError
            If the creation fails.
        """

    @abstractmethod
    async def get_content(
        self,
        content_type: str,
        content_id: str,
        *,
        locale: str = "en-US",
    ) -> CMSContent:
        """Retrieve a single content entry by ID.

        Parameters
        ----------
        content_type:
            Content-type slug.
        content_id:
            CMS content identifier.
        locale:
            Content locale to retrieve.

        Returns
        -------
        CMSContent
            The requested content record.

        Raises
        ------
        PublishingError
            If the content is not found or the request fails.
        """

    @abstractmethod
    async def update_content(
        self,
        content_type: str,
        content_id: str,
        data: Dict[str, Any],
        *,
        locale: str = "en-US",
    ) -> CMSContent:
        """Update an existing content entry.

        Parameters
        ----------
        content_type:
            Content-type slug.
        content_id:
            CMS content identifier.
        data:
            Field values to update.  Only provided fields are changed.
        locale:
            Content locale to update.

        Returns
        -------
        CMSContent
            The updated content record.

        Raises
        ------
        PublishingError
            If the update fails.
        """

    @abstractmethod
    async def delete_content(
        self,
        content_type: str,
        content_id: str,
    ) -> bool:
        """Delete a content entry from the CMS.

        Parameters
        ----------
        content_type:
            Content-type slug.
        content_id:
            CMS content identifier.

        Returns
        -------
        bool
            ``True`` if the deletion succeeded.

        Raises
        ------
        PublishingError
            If the deletion fails.
        """

    @abstractmethod
    async def list_content(
        self,
        content_type: str,
        *,
        status: str = "",
        locale: str = "en-US",
        page: int = 1,
        page_size: int = 25,
        sort_field: str = "",
        sort_order: str = "desc",
    ) -> List[CMSContent]:
        """List content entries with optional filtering and pagination.

        Parameters
        ----------
        content_type:
            Content-type slug.
        status:
            Optional status filter.
        locale:
            Content locale to query.
        page:
            Page number (1-based).
        page_size:
            Number of results per page.
        sort_field:
            Field name to sort by.
        sort_order:
            Sort direction: ``"asc"`` or ``"desc"``.

        Returns
        -------
        list[CMSContent]
            Matching content records.
        """

    @abstractmethod
    async def publish_content(
        self,
        content_type: str,
        content_id: str,
    ) -> CMSContent:
        """Transition a content entry to published status.

        Parameters
        ----------
        content_type:
            Content-type slug.
        content_id:
            CMS content identifier.

        Returns
        -------
        CMSContent
            The published content record.
        """

    # ------------------------------------------------------------------
    # Media management
    # ------------------------------------------------------------------

    @abstractmethod
    async def upload_media(
        self,
        file_path: str,
        *,
        alt_text: str = "",
        folder: str = "",
    ) -> CMSMedia:
        """Upload a media file to the CMS media library.

        Parameters
        ----------
        file_path:
            Local filesystem path to the file.
        alt_text:
            Alternative text for the media.
        folder:
            Optional target folder in the media library.

        Returns
        -------
        CMSMedia
            The uploaded media record.
        """

    @abstractmethod
    async def delete_media(self, media_id: str) -> bool:
        """Delete a media asset from the CMS.

        Parameters
        ----------
        media_id:
            CMS media identifier.

        Returns
        -------
        bool
            ``True`` if the deletion succeeded.
        """

    # ------------------------------------------------------------------
    # Content-type introspection
    # ------------------------------------------------------------------

    @abstractmethod
    async def get_content_types(self) -> List[ContentType]:
        """Retrieve all content types defined in the CMS.

        Returns
        -------
        list[ContentType]
            Content-type schemas available in the CMS instance.
        """

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    @abstractmethod
    async def connect(self) -> bool:
        """Test the connection to the headless CMS API.

        Returns
        -------
        bool
            ``True`` if the connection and authentication succeeded.

        Raises
        ------
        CMSConnectionError
            If the API is unreachable or credentials are rejected.
        """

    @abstractmethod
    async def disconnect(self) -> None:
        """Clean up any held resources (sessions, connections)."""

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def cms_name(self) -> str:
        """Return the CMS provider name."""
        return self._cms_name

    @property
    def base_url(self) -> str:
        """Return the CMS API base URL."""
        return self._base_url

    @property
    def request_count(self) -> int:
        """Return the total number of API requests made."""
        return self._request_count

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(cms={self._cms_name!r}, "
            f"base_url={self._base_url!r}, requests={self._request_count})"
        )
