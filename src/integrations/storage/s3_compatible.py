"""
integrations.storage.s3_compatible
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

S3-compatible object storage client for backups, media, and static assets.

Provides :class:`S3Storage` which wraps the S3 API (via ``boto3``) to
upload, download, list, and delete objects in any S3-compatible storage
service (AWS S3, Cloudflare R2, MinIO, Backblaze B2, etc.).

Design references:
    - config/providers.yaml  ``storage.s3`` section
    - ARCHITECTURE.md  Section 4 (Integration Layer)

Usage::

    from src.integrations.storage.s3_compatible import S3Storage

    storage = S3Storage(
        bucket="openclaw-backups",
        access_key="AKIA...",
        secret_key="wJal...",
        endpoint_url="https://xxx.r2.cloudflarestorage.com",
    )
    await storage.upload("backups/db-2024-01-15.sqlite", local_path="/tmp/dump.sqlite")
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.errors import IntegrationError, APIAuthenticationError
from src.core.logger import get_logger, log_event

logger = get_logger("integrations.storage.s3_compatible")

# ---------------------------------------------------------------------------
# Optional dependency: boto3
# ---------------------------------------------------------------------------
try:
    import boto3  # type: ignore[import-untyped]
    from botocore.exceptions import (  # type: ignore[import-untyped]
        BotoCoreError,
        ClientError,
        NoCredentialsError,
    )
    _HAS_BOTO3 = True
except ImportError:
    _HAS_BOTO3 = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_REGION = "auto"
_DEFAULT_SIGNED_URL_EXPIRY = 3600  # 1 hour


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class S3Object:
    """Metadata for a single object in S3 storage.

    Attributes
    ----------
    key:
        Object key (path within the bucket).
    size_bytes:
        Object size in bytes.
    last_modified:
        UTC timestamp of the last modification.
    etag:
        Entity tag (MD5 hash of the object content for standard uploads).
    content_type:
        MIME type of the object.
    storage_class:
        Storage class (``"STANDARD"``, ``"INTELLIGENT_TIERING"``, etc.).
    metadata:
        User-defined metadata key-value pairs.
    """

    key: str
    size_bytes: int = 0
    last_modified: Optional[datetime] = None
    etag: str = ""
    content_type: str = ""
    storage_class: str = "STANDARD"
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass
class UploadResult:
    """Result of an object upload operation.

    Attributes
    ----------
    key:
        Object key in the bucket.
    bucket:
        Target bucket name.
    size_bytes:
        Number of bytes uploaded.
    etag:
        ETag returned by S3.
    version_id:
        Version ID (if bucket versioning is enabled).
    url:
        Public URL of the uploaded object (if publicly accessible).
    """

    key: str
    bucket: str = ""
    size_bytes: int = 0
    etag: str = ""
    version_id: str = ""
    url: str = ""


# ---------------------------------------------------------------------------
# S3Storage client
# ---------------------------------------------------------------------------

class S3Storage:
    """S3-compatible object storage client.

    Wraps ``boto3`` to provide a simplified interface for common object
    storage operations.  Supports any S3-compatible endpoint via the
    ``endpoint_url`` parameter.

    Parameters
    ----------
    bucket:
        Default bucket name for all operations.
    access_key:
        S3 access key ID.
    secret_key:
        S3 secret access key.
    endpoint_url:
        Custom S3-compatible endpoint URL.  Required for non-AWS
        services (Cloudflare R2, MinIO, Backblaze B2, etc.).
        Leave empty for AWS S3.
    region:
        AWS region or ``"auto"`` for S3-compatible services.
    signed_url_expiry:
        Default expiry time in seconds for pre-signed URLs.
    """

    def __init__(
        self,
        bucket: str,
        access_key: str,
        secret_key: str,
        endpoint_url: str = "",
        region: str = _DEFAULT_REGION,
        signed_url_expiry: int = _DEFAULT_SIGNED_URL_EXPIRY,
    ) -> None:
        if not bucket:
            raise IntegrationError("S3 bucket name is required")
        if not access_key or not secret_key:
            raise APIAuthenticationError(
                "S3 storage requires both access_key and secret_key",
            )

        self._bucket = bucket
        self._access_key = access_key
        self._secret_key = secret_key
        self._endpoint_url = endpoint_url
        self._region = region
        self._signed_url_expiry = signed_url_expiry
        self._client: Any = None
        self._operation_count: int = 0

        # Initialize boto3 client if available
        if _HAS_BOTO3:
            client_kwargs: Dict[str, Any] = {
                "service_name": "s3",
                "aws_access_key_id": access_key,
                "aws_secret_access_key": secret_key,
                "region_name": region,
            }
            if endpoint_url:
                client_kwargs["endpoint_url"] = endpoint_url

            try:
                self._client = boto3.client(**client_kwargs)
            except (BotoCoreError, Exception) as exc:
                raise IntegrationError(
                    "Failed to initialize S3 client",
                    details={"endpoint": endpoint_url, "region": region},
                    cause=exc,
                ) from exc
        else:
            logger.warning(
                "boto3 is not installed; S3 operations will not be available. "
                "Install with: pip install boto3"
            )

        log_event(
            logger,
            "s3.init",
            bucket=bucket,
            endpoint=endpoint_url or "aws-default",
            region=region,
            has_boto3=_HAS_BOTO3,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_client(self) -> None:
        """Raise if the boto3 client is not available.

        Raises
        ------
        IntegrationError
            If boto3 is not installed.
        """
        if self._client is None:
            raise IntegrationError(
                "S3 client is not available. Ensure boto3 is installed: pip install boto3"
            )

    def _track_operation(self) -> None:
        """Record that an S3 operation was performed."""
        self._operation_count += 1

    @staticmethod
    def _detect_content_type(path: str) -> str:
        """Detect MIME type from a file path.

        Parameters
        ----------
        path:
            File path or object key.

        Returns
        -------
        str
            Detected MIME type, or ``"application/octet-stream"`` as fallback.
        """
        content_type, _ = mimetypes.guess_type(path)
        return content_type or "application/octet-stream"

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    async def upload(
        self,
        key: str,
        *,
        local_path: Optional[str] = None,
        data: Optional[bytes] = None,
        content_type: str = "",
        metadata: Optional[Dict[str, str]] = None,
        bucket: str = "",
    ) -> UploadResult:
        """Upload a file or bytes to S3.

        Either *local_path* or *data* must be provided.  If both are
        given, *data* takes precedence.

        Parameters
        ----------
        key:
            Object key (destination path in the bucket).
        local_path:
            Path to a local file to upload.
        data:
            Raw bytes to upload directly.
        content_type:
            MIME type.  Auto-detected from key if not specified.
        metadata:
            User-defined metadata to attach to the object.
        bucket:
            Override the default bucket.

        Returns
        -------
        UploadResult
            Upload outcome with ETag and version info.

        Raises
        ------
        IntegrationError
            If the upload fails or neither local_path nor data is provided.
        """
        self._ensure_client()
        target_bucket = bucket or self._bucket

        if data is None and local_path is None:
            raise IntegrationError(
                "Either local_path or data must be provided for upload"
            )

        resolved_content_type = content_type or self._detect_content_type(key)
        extra_args: Dict[str, Any] = {"ContentType": resolved_content_type}
        if metadata:
            extra_args["Metadata"] = metadata

        log_event(
            logger,
            "s3.upload",
            bucket=target_bucket,
            key=key,
            content_type=resolved_content_type,
            source="data" if data is not None else "file",
        )
        self._track_operation()

        try:
            if data is not None:
                size_bytes = len(data)
                response = self._client.put_object(
                    Bucket=target_bucket,
                    Key=key,
                    Body=data,
                    **extra_args,
                )
            else:
                size_bytes = os.path.getsize(local_path)  # type: ignore[arg-type]
                self._client.upload_file(
                    Filename=local_path,
                    Bucket=target_bucket,
                    Key=key,
                    ExtraArgs=extra_args,
                )
                response = {}

            etag = response.get("ETag", "").strip('"')
            version_id = response.get("VersionId", "")

            return UploadResult(
                key=key,
                bucket=target_bucket,
                size_bytes=size_bytes,
                etag=etag,
                version_id=version_id,
            )

        except (ClientError, BotoCoreError, OSError) as exc:
            raise IntegrationError(
                f"S3 upload failed for key={key!r}",
                details={"bucket": target_bucket, "key": key},
                cause=exc,
            ) from exc

    async def download(
        self,
        key: str,
        *,
        local_path: Optional[str] = None,
        bucket: str = "",
    ) -> bytes:
        """Download an object from S3.

        If *local_path* is provided, the file is saved to disk and the
        content is also returned as bytes.

        Parameters
        ----------
        key:
            Object key to download.
        local_path:
            Optional local filesystem path to save the downloaded file.
        bucket:
            Override the default bucket.

        Returns
        -------
        bytes
            Object content as bytes.

        Raises
        ------
        IntegrationError
            If the download fails or the object does not exist.
        """
        self._ensure_client()
        target_bucket = bucket or self._bucket

        log_event(
            logger,
            "s3.download",
            bucket=target_bucket,
            key=key,
            save_to_disk=bool(local_path),
        )
        self._track_operation()

        try:
            response = self._client.get_object(Bucket=target_bucket, Key=key)
            content = response["Body"].read()

            if local_path:
                Path(local_path).parent.mkdir(parents=True, exist_ok=True)
                with open(local_path, "wb") as fh:
                    fh.write(content)
                logger.debug("Downloaded %s to %s (%d bytes)", key, local_path, len(content))

            return content

        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "Unknown")
            if error_code == "NoSuchKey":
                raise IntegrationError(
                    f"S3 object not found: {key!r}",
                    details={"bucket": target_bucket, "key": key},
                    cause=exc,
                ) from exc
            raise IntegrationError(
                f"S3 download failed for key={key!r}",
                details={"bucket": target_bucket, "key": key, "error_code": error_code},
                cause=exc,
            ) from exc
        except (BotoCoreError, OSError) as exc:
            raise IntegrationError(
                f"S3 download failed for key={key!r}",
                details={"bucket": target_bucket, "key": key},
                cause=exc,
            ) from exc

    async def list_objects(
        self,
        prefix: str = "",
        *,
        delimiter: str = "",
        max_keys: int = 1000,
        bucket: str = "",
    ) -> List[S3Object]:
        """List objects in the bucket with an optional prefix filter.

        Parameters
        ----------
        prefix:
            Key prefix to filter results (e.g. ``"backups/"``).
        delimiter:
            Delimiter for grouping (e.g. ``"/"`` for directory-like listing).
        max_keys:
            Maximum number of objects to return.
        bucket:
            Override the default bucket.

        Returns
        -------
        list[S3Object]
            Object metadata for matching keys.

        Raises
        ------
        IntegrationError
            If the listing fails.
        """
        self._ensure_client()
        target_bucket = bucket or self._bucket

        log_event(
            logger,
            "s3.list_objects",
            bucket=target_bucket,
            prefix=prefix,
            max_keys=max_keys,
        )
        self._track_operation()

        try:
            params: Dict[str, Any] = {
                "Bucket": target_bucket,
                "MaxKeys": max_keys,
            }
            if prefix:
                params["Prefix"] = prefix
            if delimiter:
                params["Delimiter"] = delimiter

            response = self._client.list_objects_v2(**params)
            contents = response.get("Contents", [])

            objects: List[S3Object] = []
            for item in contents:
                last_modified = item.get("LastModified")
                if last_modified and not last_modified.tzinfo:
                    last_modified = last_modified.replace(tzinfo=timezone.utc)

                objects.append(S3Object(
                    key=item.get("Key", ""),
                    size_bytes=item.get("Size", 0),
                    last_modified=last_modified,
                    etag=item.get("ETag", "").strip('"'),
                    storage_class=item.get("StorageClass", "STANDARD"),
                ))

            return objects

        except (ClientError, BotoCoreError) as exc:
            raise IntegrationError(
                f"S3 list failed for prefix={prefix!r}",
                details={"bucket": target_bucket, "prefix": prefix},
                cause=exc,
            ) from exc

    async def delete(
        self,
        key: str,
        *,
        bucket: str = "",
    ) -> bool:
        """Delete an object from S3.

        Parameters
        ----------
        key:
            Object key to delete.
        bucket:
            Override the default bucket.

        Returns
        -------
        bool
            ``True`` if the deletion was successful.

        Raises
        ------
        IntegrationError
            If the deletion fails.
        """
        self._ensure_client()
        target_bucket = bucket or self._bucket

        log_event(
            logger,
            "s3.delete",
            bucket=target_bucket,
            key=key,
        )
        self._track_operation()

        try:
            self._client.delete_object(Bucket=target_bucket, Key=key)
            return True

        except (ClientError, BotoCoreError) as exc:
            raise IntegrationError(
                f"S3 delete failed for key={key!r}",
                details={"bucket": target_bucket, "key": key},
                cause=exc,
            ) from exc

    async def get_signed_url(
        self,
        key: str,
        *,
        expires_in: Optional[int] = None,
        bucket: str = "",
        http_method: str = "GET",
    ) -> str:
        """Generate a pre-signed URL for temporary access to an object.

        Parameters
        ----------
        key:
            Object key to generate the URL for.
        expires_in:
            URL expiry time in seconds.  Defaults to the instance's
            ``signed_url_expiry`` setting.
        bucket:
            Override the default bucket.
        http_method:
            HTTP method the URL will be valid for (``"GET"`` or ``"PUT"``).

        Returns
        -------
        str
            Pre-signed URL.

        Raises
        ------
        IntegrationError
            If URL generation fails.
        """
        self._ensure_client()
        target_bucket = bucket or self._bucket
        expiry = expires_in or self._signed_url_expiry

        log_event(
            logger,
            "s3.get_signed_url",
            bucket=target_bucket,
            key=key,
            expires_in=expiry,
            method=http_method,
        )
        self._track_operation()

        try:
            client_method = (
                "get_object" if http_method.upper() == "GET" else "put_object"
            )
            url = self._client.generate_presigned_url(
                ClientMethod=client_method,
                Params={"Bucket": target_bucket, "Key": key},
                ExpiresIn=expiry,
            )
            return url

        except (ClientError, BotoCoreError) as exc:
            raise IntegrationError(
                f"Failed to generate signed URL for key={key!r}",
                details={"bucket": target_bucket, "key": key},
                cause=exc,
            ) from exc

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def bucket(self) -> str:
        """Return the default bucket name."""
        return self._bucket

    @property
    def operation_count(self) -> int:
        """Return the total number of S3 operations performed."""
        return self._operation_count

    @property
    def has_client(self) -> bool:
        """Return whether the boto3 client is available."""
        return self._client is not None

    def __repr__(self) -> str:
        return (
            f"S3Storage(bucket={self._bucket!r}, "
            f"endpoint={self._endpoint_url or 'aws-default'!r}, "
            f"operations={self._operation_count})"
        )
