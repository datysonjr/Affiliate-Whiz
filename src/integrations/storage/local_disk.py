"""
integrations.storage.local_disk
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Local disk storage backend for the OpenClaw system.

Provides the :class:`LocalDiskStorage` class for persisting files to the
local filesystem with structured directory organisation, file metadata
tracking, and disk usage monitoring.  Used as the default storage backend
for development and single-node deployments.

Design references:
    - ARCHITECTURE.md  Section 4 (Integration Layer)
    - config/providers.yaml  ``storage`` section
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from src.core.errors import IntegrationError
from src.core.logger import get_logger, log_event

logger = get_logger("integrations.storage.local_disk")


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class FileInfo:
    """Metadata for a file on local disk.

    Attributes
    ----------
    path:
        Absolute file path.
    relative_path:
        Path relative to the storage root directory.
    filename:
        Filename (basename).
    size_bytes:
        File size in bytes.
    created_at:
        UTC timestamp of file creation (from filesystem metadata).
    modified_at:
        UTC timestamp of last modification.
    content_hash:
        SHA-256 hash of the file content (computed on demand).
    mime_type:
        Guessed MIME type.
    """

    path: str
    relative_path: str = ""
    filename: str = ""
    size_bytes: int = 0
    created_at: Optional[datetime] = None
    modified_at: Optional[datetime] = None
    content_hash: str = ""
    mime_type: str = ""


@dataclass
class DiskUsage:
    """Disk usage statistics for the storage directory.

    Attributes
    ----------
    root_dir:
        Storage root directory path.
    total_bytes:
        Total disk space in bytes.
    used_bytes:
        Used disk space in bytes.
    free_bytes:
        Free disk space in bytes.
    file_count:
        Number of files in the storage directory.
    dir_count:
        Number of subdirectories in the storage directory.
    usage_percent:
        Disk usage as a percentage (0--100).
    """

    root_dir: str
    total_bytes: int = 0
    used_bytes: int = 0
    free_bytes: int = 0
    file_count: int = 0
    dir_count: int = 0
    usage_percent: float = 0.0


# ---------------------------------------------------------------------------
# LocalDiskStorage
# ---------------------------------------------------------------------------


class LocalDiskStorage:
    """Local filesystem storage backend.

    Organises files under a root directory, providing a simple API for
    saving, loading, listing, and deleting files with optional directory
    structure.

    Parameters
    ----------
    root_dir:
        Absolute path to the root storage directory.  Created
        automatically if it does not exist.
    max_size_bytes:
        Maximum total storage size in bytes.  Set to 0 for unlimited.
    """

    def __init__(
        self,
        root_dir: str,
        max_size_bytes: int = 0,
    ) -> None:
        if not root_dir:
            raise IntegrationError("root_dir is required for LocalDiskStorage")

        self._root_dir = Path(root_dir).resolve()
        self._max_size_bytes = max_size_bytes
        self._operation_count: int = 0
        self.logger: logging.Logger = get_logger("integrations.storage.local_disk")

        # Ensure root directory exists
        self._root_dir.mkdir(parents=True, exist_ok=True)

        log_event(
            logger,
            "local_disk.init",
            root_dir=str(self._root_dir),
            max_size_mb=max_size_bytes / (1024 * 1024) if max_size_bytes else 0,
        )

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def save(
        self,
        relative_path: str,
        data: bytes,
        *,
        overwrite: bool = True,
    ) -> FileInfo:
        """Save data to a file on disk.

        Parameters
        ----------
        relative_path:
            File path relative to the root directory (e.g.
            ``"images/2025/hero.jpg"``).  Parent directories are
            created automatically.
        data:
            File content as bytes.
        overwrite:
            If ``False``, raise an error if the file already exists.

        Returns
        -------
        FileInfo
            Metadata for the saved file.

        Raises
        ------
        IntegrationError
            If the file already exists and ``overwrite`` is ``False``,
            or if the storage size limit would be exceeded.
        """
        target = self._root_dir / relative_path

        if not overwrite and target.exists():
            raise IntegrationError(
                f"File already exists and overwrite is disabled: {relative_path}",
                details={"path": str(target)},
            )

        # Check size limit
        if self._max_size_bytes > 0:
            current_usage = self._calculate_dir_size(self._root_dir)
            if current_usage + len(data) > self._max_size_bytes:
                raise IntegrationError(
                    "Storage size limit would be exceeded",
                    details={
                        "current_bytes": current_usage,
                        "incoming_bytes": len(data),
                        "max_bytes": self._max_size_bytes,
                    },
                )

        # Ensure parent directories exist
        target.parent.mkdir(parents=True, exist_ok=True)

        target.write_bytes(data)
        self._operation_count += 1

        content_hash = hashlib.sha256(data).hexdigest()

        import mimetypes as mt

        mime_type = mt.guess_type(target.name)[0] or "application/octet-stream"

        info = FileInfo(
            path=str(target),
            relative_path=relative_path,
            filename=target.name,
            size_bytes=len(data),
            created_at=datetime.now(timezone.utc),
            modified_at=datetime.now(timezone.utc),
            content_hash=content_hash,
            mime_type=mime_type,
        )

        self.logger.info(
            "Saved file: %s (%d bytes, hash=%s...)",
            relative_path,
            len(data),
            content_hash[:12],
        )
        return info

    def load(self, relative_path: str) -> bytes:
        """Load file content from disk.

        Parameters
        ----------
        relative_path:
            File path relative to the root directory.

        Returns
        -------
        bytes
            File content.

        Raises
        ------
        FileNotFoundError
            If the file does not exist.
        """
        target = self._root_dir / relative_path

        if not target.is_file():
            raise FileNotFoundError(f"File not found: {relative_path}")

        data = target.read_bytes()
        self._operation_count += 1

        self.logger.debug("Loaded file: %s (%d bytes)", relative_path, len(data))
        return data

    def list_files(
        self,
        prefix: str = "",
        *,
        recursive: bool = True,
        extension: str = "",
    ) -> List[FileInfo]:
        """List files in the storage directory.

        Parameters
        ----------
        prefix:
            Subdirectory prefix to filter by.
        recursive:
            If ``True``, list files in all subdirectories.
        extension:
            Filter by file extension (e.g. ``".jpg"``).

        Returns
        -------
        list[FileInfo]
            File metadata for matching files, sorted by path.
        """
        search_dir = self._root_dir / prefix if prefix else self._root_dir

        if not search_dir.is_dir():
            return []

        files: List[FileInfo] = []
        pattern = f"**/*{extension}" if recursive else f"*{extension}"

        for path in sorted(search_dir.glob(pattern)):
            if not path.is_file():
                continue

            stat = path.stat()
            rel_path = str(path.relative_to(self._root_dir))

            files.append(
                FileInfo(
                    path=str(path),
                    relative_path=rel_path,
                    filename=path.name,
                    size_bytes=stat.st_size,
                    created_at=datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc),
                    modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                )
            )

        self.logger.debug(
            "Listed %d files under '%s' (recursive=%s, ext=%s)",
            len(files),
            prefix or "/",
            recursive,
            extension or "*",
        )
        return files

    def delete(self, relative_path: str) -> bool:
        """Delete a file from disk.

        Parameters
        ----------
        relative_path:
            File path relative to the root directory.

        Returns
        -------
        bool
            ``True`` if the file was found and deleted.
        """
        target = self._root_dir / relative_path

        if not target.is_file():
            self.logger.warning("File not found for deletion: %s", relative_path)
            return False

        target.unlink()
        self._operation_count += 1

        self.logger.info("Deleted file: %s", relative_path)

        # Clean up empty parent directories
        self._cleanup_empty_dirs(target.parent)

        return True

    def get_usage(self) -> DiskUsage:
        """Calculate disk usage statistics for the storage directory.

        Returns
        -------
        DiskUsage
            Disk usage metrics.
        """
        disk = shutil.disk_usage(str(self._root_dir))

        file_count = 0
        dir_count = 0
        storage_used = 0

        for entry in self._root_dir.rglob("*"):
            if entry.is_file():
                file_count += 1
                storage_used += entry.stat().st_size
            elif entry.is_dir():
                dir_count += 1

        usage_pct = (disk.used / disk.total * 100) if disk.total > 0 else 0.0

        result = DiskUsage(
            root_dir=str(self._root_dir),
            total_bytes=disk.total,
            used_bytes=storage_used,
            free_bytes=disk.free,
            file_count=file_count,
            dir_count=dir_count,
            usage_percent=round(usage_pct, 2),
        )

        log_event(
            logger,
            "local_disk.usage",
            files=file_count,
            storage_mb=round(storage_used / (1024 * 1024), 2),
            usage_pct=result.usage_percent,
        )

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _calculate_dir_size(directory: Path) -> int:
        """Calculate total size of all files in a directory tree.

        Parameters
        ----------
        directory:
            Root directory to calculate size for.

        Returns
        -------
        int
            Total size in bytes.
        """
        total = 0
        for entry in directory.rglob("*"):
            if entry.is_file():
                total += entry.stat().st_size
        return total

    def _cleanup_empty_dirs(self, directory: Path) -> None:
        """Remove empty directories up to the storage root.

        Parameters
        ----------
        directory:
            Starting directory to check.
        """
        current = directory
        while current != self._root_dir and current.is_dir():
            try:
                current.rmdir()  # Only succeeds if empty
                self.logger.debug("Cleaned up empty directory: %s", current)
                current = current.parent
            except OSError:
                break  # Directory is not empty

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def root_dir(self) -> str:
        """Return the storage root directory path."""
        return str(self._root_dir)

    @property
    def operation_count(self) -> int:
        """Return the total number of file operations performed."""
        return self._operation_count

    def __repr__(self) -> str:
        return (
            f"LocalDiskStorage(root={str(self._root_dir)!r}, "
            f"operations={self._operation_count})"
        )
