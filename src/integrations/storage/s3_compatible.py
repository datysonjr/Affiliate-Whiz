"""
integrations.storage.s3_compatible
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

S3-compatible object storage integration for the OpenClaw system.

Provides the :class:`S3Storage` class for uploading, downloading, listing,
and deleting objects in S3-compatible storage services (AWS S3, MinIO,
Backblaze B2, Cloudflare R2, DigitalOcean Spaces, etc.).

Design references:
    - ARCHITECTURE.md  Section 4 (Integration Layer)
    - config/providers.yaml  ``storage`` section
"""

from __future__ import annotations

import logging
import mimetypes
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.constants import DEFAULT_REQUEST_TIMEOUT
from src.core.errors import IntegrationError
from src.core.logger import get_logger, log_event

# ---------------------------------------------------------------------------
# Optional dependency: boto3
# ---------------------------------------------------------------------------
try:
    import boto3  # type: ignore[import-untyped]
    from botocore.config import Config as BotoConfig  # type: ignore[import-untyped]
    from botocore.exceptions import ClientError  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    boto3 = None  # type: ignore[assignment]
    BotoConfig = None  # type: ignore[assignment]
    ClientError = Exception  # type: ignore[assignment,misc]

logger = get_logger("integrations.storage.s3_compatible")


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class S3Object:
    """Metadata for a single object in S3-compatible storage.

    Attributes
    ----------
    key:
        Object key (path) within the bucket.
    bucket:
        Bucket name.
    size_bytes:
        Object size in bytes.
    last_modified:
        UTC timestamp of the last modification.
    etag:
        Entity tag (usually an MD5 hash of the object content).
    content_type:
        MIME type of the object.
    storage_class:
        Storage class (e.g. ``"STANDARD"``, ``"GLACIER"``).
    url:
        Public URL if the object is publicly accessible.
    metadata:
        User-defined metadata key-value pairs.
    """

    key: str
    bucket: str = ""
    size_bytes: int = 0
    last_modified: Optional[datetime] = None
    etag: str = ""
    content_type: str = ""
    storage_class: str = "STANDARD"
    url: str = ""
    metadata: Dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# S3Storage client
# ---------------------------------------------------------------------------


class S3Storage:
    """Client for S3-compatible object storage.

    Wraps ``boto3`` to provide a simplified interface for common storage
    operations.  Supports any S3-compatible endpoint by configuring the
    ``endpoint_url`` parameter.

    Parameters
    ----------
    bucket:
        Default bucket name.
    access_key:
        AWS / S3-compatible access key ID.
    secret_key:
        AWS / S3-compatible secret access key.
    endpoint_url:
        Custom S3-compatible endpoint URL (e.g. ``"https://s3.us-west-002.backblazeb2.com"``).
        Leave empty for AWS S3.
    region:
        AWS region (e.g. ``"us-east-1"``).
    public_base_url:
        Base URL for constructing public object URLs (e.g. a CDN URL).
    timeout:
        HTTP request timeout in seconds.

    Raises
    ------
    IntegrationError
        If ``boto3`` is not installed.
    APIAuthenticationError
        If credentials are missing.
    """

    def __init__(
        self,
        bucket: str,
        access_key: str = "",
        secret_key: str = "",
        endpoint_url: str = "",
        region: str = "us-east-1",
        public_base_url: str = "",
        timeout: int = DEFAULT_REQUEST_TIMEOUT,
    ) -> None:
        if boto3 is None:
            raise IntegrationError(
                "The 'boto3' package is required for S3Storage. "
                "Install it with: pip install boto3"
            )
        if not bucket:
            raise IntegrationError("bucket is required for S3Storage")

        self._bucket = bucket
        self._endpoint_url = endpoint_url
        self._region = region
        self._public_base_url = public_base_url.rstrip("/") if public_base_url else ""
        self._request_count: int = 0
        self.logger: logging.Logger = get_logger("integrations.storage.s3_compatible")

        # Build boto3 client
        client_kwargs: Dict[str, Any] = {
            "service_name": "s3",
            "region_name": region,
        }
        if access_key and secret_key:
            client_kwargs["aws_access_key_id"] = access_key
            client_kwargs["aws_secret_access_key"] = secret_key
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url

        boto_config = (
            BotoConfig(
                connect_timeout=timeout,
                read_timeout=timeout,
                retries={"max_attempts": 3, "mode": "standard"},
            )
            if BotoConfig
            else None
        )
        if boto_config:
            client_kwargs["config"] = boto_config

        self._client = boto3.client(**client_kwargs)

        log_event(
            logger,
            "s3.init",
            bucket=bucket,
            region=region,
            has_endpoint=bool(endpoint_url),
        )

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def upload(
        self,
        local_path: str,
        key: str,
        *,
        content_type: str = "",
        metadata: Optional[Dict[str, str]] = None,
        public: bool = False,
    ) -> S3Object:
        """Upload a local file to S3.

        Parameters
        ----------
        local_path:
            Path to the local file.
        key:
            Destination object key in the bucket.
        content_type:
            MIME type override.  If empty, it is guessed from the filename.
        metadata:
            User-defined metadata to attach to the object.
        public:
            If ``True``, set the ACL to ``public-read``.

        Returns
        -------
        S3Object
            Metadata of the uploaded object.

        Raises
        ------
        FileNotFoundError
            If the local file does not exist.
        IntegrationError
            If the upload fails.
        """
        path = Path(local_path)
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {local_path}")

        if not content_type:
            content_type = (
                mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            )

        extra_args: Dict[str, Any] = {"ContentType": content_type}
        if metadata:
            extra_args["Metadata"] = metadata
        if public:
            extra_args["ACL"] = "public-read"

        try:
            self._client.upload_file(str(path), self._bucket, key, ExtraArgs=extra_args)
            self._request_count += 1
        except ClientError as exc:
            raise IntegrationError(
                f"S3 upload failed: {key}",
                details={"bucket": self._bucket, "key": key, "error": str(exc)},
                cause=exc,
            ) from exc

        size = path.stat().st_size
        url = self._build_url(key) if public else ""

        self.logger.info(
            "Uploaded %s to s3://%s/%s (%d bytes, %s)",
            path.name,
            self._bucket,
            key,
            size,
            content_type,
        )

        return S3Object(
            key=key,
            bucket=self._bucket,
            size_bytes=size,
            last_modified=datetime.now(timezone.utc),
            content_type=content_type,
            url=url,
            metadata=metadata or {},
        )

    def download(
        self,
        key: str,
        local_path: str,
    ) -> str:
        """Download an object from S3 to a local file.

        Parameters
        ----------
        key:
            Object key in the bucket.
        local_path:
            Destination path on the local filesystem.

        Returns
        -------
        str
            The local file path where the object was saved.

        Raises
        ------
        IntegrationError
            If the download fails.
        """
        try:
            # Ensure parent directory exists
            Path(local_path).parent.mkdir(parents=True, exist_ok=True)
            self._client.download_file(self._bucket, key, local_path)
            self._request_count += 1
        except ClientError as exc:
            raise IntegrationError(
                f"S3 download failed: {key}",
                details={"bucket": self._bucket, "key": key, "error": str(exc)},
                cause=exc,
            ) from exc

        self.logger.info(
            "Downloaded s3://%s/%s to %s",
            self._bucket,
            key,
            local_path,
        )
        return local_path

    def list_objects(
        self,
        prefix: str = "",
        *,
        max_keys: int = 1000,
        delimiter: str = "",
    ) -> List[S3Object]:
        """List objects in the bucket with an optional prefix filter.

        Parameters
        ----------
        prefix:
            Key prefix to filter by (e.g. ``"images/"``).
        max_keys:
            Maximum number of objects to return.
        delimiter:
            Delimiter for grouping keys (e.g. ``"/"`` for directory-like listing).

        Returns
        -------
        list[S3Object]
            Object metadata for matching keys.
        """
        params: Dict[str, Any] = {
            "Bucket": self._bucket,
            "MaxKeys": min(max_keys, 1000),
        }
        if prefix:
            params["Prefix"] = prefix
        if delimiter:
            params["Delimiter"] = delimiter

        try:
            response = self._client.list_objects_v2(**params)
            self._request_count += 1
        except ClientError as exc:
            raise IntegrationError(
                f"S3 list_objects failed for prefix '{prefix}'",
                details={"bucket": self._bucket, "prefix": prefix, "error": str(exc)},
                cause=exc,
            ) from exc

        objects: List[S3Object] = []
        for item in response.get("Contents", []):
            objects.append(
                S3Object(
                    key=item.get("Key", ""),
                    bucket=self._bucket,
                    size_bytes=item.get("Size", 0),
                    last_modified=item.get("LastModified"),
                    etag=item.get("ETag", "").strip('"'),
                    storage_class=item.get("StorageClass", "STANDARD"),
                )
            )

        self.logger.debug(
            "Listed %d objects in s3://%s/%s",
            len(objects),
            self._bucket,
            prefix,
        )
        return objects

    def delete(self, key: str) -> bool:
        """Delete an object from S3.

        Parameters
        ----------
        key:
            Object key to delete.

        Returns
        -------
        bool
            ``True`` if the deletion succeeded.

        Raises
        ------
        IntegrationError
            If the deletion fails.
        """
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
            self._request_count += 1
        except ClientError as exc:
            raise IntegrationError(
                f"S3 delete failed: {key}",
                details={"bucket": self._bucket, "key": key, "error": str(exc)},
                cause=exc,
            ) from exc

        self.logger.info("Deleted s3://%s/%s", self._bucket, key)
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_url(self, key: str) -> str:
        """Build a public URL for an S3 object.

        Parameters
        ----------
        key:
            Object key.

        Returns
        -------
        str
            Public URL, or empty string if no base URL is configured.
        """
        if self._public_base_url:
            return f"{self._public_base_url}/{key}"
        if self._endpoint_url:
            return f"{self._endpoint_url}/{self._bucket}/{key}"
        return f"https://{self._bucket}.s3.{self._region}.amazonaws.com/{key}"

    @property
    def bucket(self) -> str:
        """Return the configured bucket name."""
        return self._bucket

    @property
    def request_count(self) -> int:
        """Return the total number of S3 API requests made."""
        return self._request_count

    def __repr__(self) -> str:
        return (
            f"S3Storage(bucket={self._bucket!r}, "
            f"region={self._region!r}, requests={self._request_count})"
        )
