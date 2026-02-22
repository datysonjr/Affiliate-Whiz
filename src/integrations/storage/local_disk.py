"""
integrations.storage.local_disk
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Local filesystem storage with space monitoring.

Provides :class:`LocalDiskStorage` which manages files on the local
filesystem within a configurable base directory.  Includes disk-space
monitoring to prevent the system from filling up the host's storage
during backup, media, or cache operations.

Design references:
    - config/providers.yaml  ``storage.local`` section
    - ARCHITECTURE.md  Section 4 (Integration Layer)

Usage::

    from src.integrations.storage.local_disk import LocalDiskStorage

    storage = LocalDiskStorage(base_dir="/data/openclaw")
    await storage.save("backups/db-2024-01-15.sqlite", data=db_bytes)
    files = await storage.list_files("backups/")
    usage = await storage.get_usage()
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.errors import IntegrationError
from src.core.logger import get_logger, log_event

logger = get_logger("integrations.storage.local_disk")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_BASE_DIR = "data/storage"
_MIN_FREE_SPACE_BYTES = 500 * 1024 * 1024  # 500 MB minimum free space


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class FileInfo:
    """Metadata for a single file on the local filesystem.

    Attributes
    ----------
    path:
        Relative path from the storage base directory.
    absolute_path:
        Absolute filesystem path.
    size_bytes:
        File size in bytes.
    created_at:
        UTC timestamp of file creation (or metadata change on Linux).
    modified_at:
        UTC timestamp of the last modification.
    is_directory:
        Whether this entry is a directory.
    """

    path: str
    absolute_path: str
    size_bytes: int = 0
    created_at: Optional[datetime] = None
    modified_at: Optional[datetime] = None
    is_directory: bool = False


@dataclass
class DiskUsage:
    """Disk usage statistics for the storage volume.

    Attributes
    ----------
    total_bytes:
        Total disk capacity in bytes.
    used_bytes:
        Used disk space in bytes.
    free_bytes:
        Free disk space in bytes.
    usage_percent:
        Percentage of disk space used (0.0--100.0).
    storage_dir_bytes:
        Total size of files within the managed storage directory.
    storage_file_count:
        Number of files in the managed storage directory.
    below_minimum_free:
        Whether free space has dropped below the safety threshold.
    """

    total_bytes: int = 0
    used_bytes: int = 0
    free_bytes: int = 0
    usage_percent: float = 0.0
    storage_dir_bytes: int = 0
    storage_file_count: int = 0
    below_minimum_free: bool = False


# ---------------------------------------------------------------------------
# LocalDiskStorage
# ---------------------------------------------------------------------------

class LocalDiskStorage:
    """Local filesystem storage manager with space monitoring.

    All file operations are scoped to a base directory.  Path traversal
    attacks are prevented by resolving all paths and verifying they fall
    within the base directory.

    Parameters
    ----------
    base_dir:
        Root directory for all storage operations.  Created automatically
        if it does not exist.
    min_free_bytes:
        Minimum free disk space to maintain (in bytes).  Write operations
        will raise an error if this threshold would be violated.
    """

    def __init__(
        self,
        base_dir: str = _DEFAULT_BASE_DIR,
        min_free_bytes: int = _MIN_FREE_SPACE_BYTES,
    ) -> None:
        self._base_dir = Path(base_dir).resolve()
        self._min_free_bytes = min_free_bytes
        self._operation_count: int = 0

        # Ensure the base directory exists
        self._base_dir.mkdir(parents=True, exist_ok=True)

        log_event(
            logger,
            "local_disk.init",
            base_dir=str(self._base_dir),
            min_free_mb=round(min_free_bytes / (1024 * 1024), 1),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_path(self, relative_path: str) -> Path:
        """Resolve a relative path to an absolute path within the base directory.

        Prevents path traversal by ensuring the resolved path is a child
        of the base directory.

        Parameters
        ----------
        relative_path:
            Path relative to the base directory.

        Returns
        -------
        Path
            Absolute, resolved path.

        Raises
        ------
        IntegrationError
            If the resolved path escapes the base directory.
        """
        resolved = (self._base_dir / relative_path).resolve()

        # Security: prevent path traversal
        try:
            resolved.relative_to(self._base_dir)
        except ValueError:
            raise IntegrationError(
                f"Path traversal detected: {relative_path!r} resolves outside base directory",
                details={
                    "relative_path": relative_path,
                    "resolved": str(resolved),
                    "base_dir": str(self._base_dir),
                },
            )

        return resolved

    def _check_free_space(self, needed_bytes: int = 0) -> None:
        """Verify there is enough free disk space for a write operation.

        Parameters
        ----------
        needed_bytes:
            Additional bytes that the operation will consume.

        Raises
        ------
        IntegrationError
            If writing would leave less than ``min_free_bytes`` free.
        """
        try:
            disk_usage = shutil.disk_usage(self._base_dir)
            available = disk_usage.free - needed_bytes
            if available < self._min_free_bytes:
                raise IntegrationError(
                    "Insufficient disk space for write operation",
                    details={
                        "free_bytes": disk_usage.free,
                        "needed_bytes": needed_bytes,
                        "min_free_bytes": self._min_free_bytes,
                        "would_leave_free": available,
                    },
                )
        except OSError as exc:
            logger.warning("Could not check disk space: %s", exc)

    def _track_operation(self) -> None:
        """Record that a storage operation was performed."""
        self._operation_count += 1

    @staticmethod
    def _stat_to_file_info(path: Path, base_dir: Path) -> FileInfo:
        """Convert a filesystem stat result into a :class:`FileInfo`.

        Parameters
        ----------
        path:
            Absolute file path.
        base_dir:
            Storage base directory for computing relative paths.

        Returns
        -------
        FileInfo
            File metadata.
        """
        try:
            stat = path.stat()
            relative = str(path.relative_to(base_dir))
            created = datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc)
            modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

            return FileInfo(
                path=relative,
                absolute_path=str(path),
                size_bytes=stat.st_size if not path.is_dir() else 0,
                created_at=created,
                modified_at=modified,
                is_directory=path.is_dir(),
            )
        except OSError as exc:
            return FileInfo(
                path=str(path.relative_to(base_dir)) if base_dir in path.parents else str(path),
                absolute_path=str(path),
            )

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    async def save(
        self,
        relative_path: str,
        *,
        data: Optional[bytes] = None,
        text: Optional[str] = None,
        source_path: Optional[str] = None,
    ) -> FileInfo:
        """Save data to a file within the storage directory.

        Exactly one of *data*, *text*, or *source_path* must be provided.

        Parameters
        ----------
        relative_path:
            Destination path relative to the base directory.
        data:
            Raw bytes to write.
        text:
            Text string to write (UTF-8 encoded).
        source_path:
            Path to a source file to copy into storage.

        Returns
        -------
        FileInfo
            Metadata for the written file.

        Raises
        ------
        IntegrationError
            If no source is provided, path traversal is detected,
            or disk space is insufficient.
        """
        sources_provided = sum(x is not None for x in [data, text, source_path])
        if sources_provided != 1:
            raise IntegrationError(
                "Exactly one of data, text, or source_path must be provided",
                details={"sources_provided": sources_provided},
            )

        target = self._resolve_path(relative_path)

        # Estimate write size for space check
        if data is not None:
            write_size = len(data)
        elif text is not None:
            write_size = len(text.encode("utf-8"))
        else:
            try:
                write_size = os.path.getsize(source_path)  # type: ignore[arg-type]
            except OSError:
                write_size = 0

        self._check_free_space(write_size)

        # Create parent directories
        target.parent.mkdir(parents=True, exist_ok=True)

        log_event(
            logger,
            "local_disk.save",
            path=relative_path,
            size_bytes=write_size,
            source="data" if data is not None else ("text" if text is not None else "copy"),
        )
        self._track_operation()

        try:
            if data is not None:
                target.write_bytes(data)
            elif text is not None:
                target.write_text(text, encoding="utf-8")
            else:
                shutil.copy2(source_path, target)  # type: ignore[arg-type]

            return self._stat_to_file_info(target, self._base_dir)

        except OSError as exc:
            raise IntegrationError(
                f"Failed to save file: {relative_path!r}",
                details={"target": str(target), "error": str(exc)},
                cause=exc,
            ) from exc

    async def load(
        self,
        relative_path: str,
        *,
        as_text: bool = False,
    ) -> bytes | str:
        """Load a file from the storage directory.

        Parameters
        ----------
        relative_path:
            Path relative to the base directory.
        as_text:
            If ``True``, return the content as a UTF-8 string.
            Otherwise, return raw bytes.

        Returns
        -------
        bytes or str
            File content.

        Raises
        ------
        IntegrationError
            If the file does not exist or cannot be read.
        """
        target = self._resolve_path(relative_path)

        if not target.is_file():
            raise IntegrationError(
                f"File not found: {relative_path!r}",
                details={"absolute_path": str(target)},
            )

        log_event(
            logger,
            "local_disk.load",
            path=relative_path,
            as_text=as_text,
        )
        self._track_operation()

        try:
            if as_text:
                return target.read_text(encoding="utf-8")
            return target.read_bytes()
        except OSError as exc:
            raise IntegrationError(
                f"Failed to read file: {relative_path!r}",
                details={"absolute_path": str(target), "error": str(exc)},
                cause=exc,
            ) from exc

    async def list_files(
        self,
        prefix: str = "",
        *,
        recursive: bool = True,
        include_dirs: bool = False,
    ) -> List[FileInfo]:
        """List files within the storage directory.

        Parameters
        ----------
        prefix:
            Subdirectory prefix to filter results.
        recursive:
            If ``True``, include files in subdirectories.
        include_dirs:
            If ``True``, include directory entries in the results.

        Returns
        -------
        list[FileInfo]
            File metadata sorted by path.

        Raises
        ------
        IntegrationError
            If the directory cannot be read.
        """
        target_dir = self._resolve_path(prefix) if prefix else self._base_dir

        if not target_dir.is_dir():
            return []

        log_event(
            logger,
            "local_disk.list_files",
            prefix=prefix,
            recursive=recursive,
        )
        self._track_operation()

        results: List[FileInfo] = []

        try:
            if recursive:
                for path in sorted(target_dir.rglob("*")):
                    if path.is_file() or (include_dirs and path.is_dir()):
                        results.append(self._stat_to_file_info(path, self._base_dir))
            else:
                for path in sorted(target_dir.iterdir()):
                    if path.is_file() or (include_dirs and path.is_dir()):
                        results.append(self._stat_to_file_info(path, self._base_dir))

        except OSError as exc:
            raise IntegrationError(
                f"Failed to list files in {prefix!r}",
                details={"target_dir": str(target_dir), "error": str(exc)},
                cause=exc,
            ) from exc

        return results

    async def delete(self, relative_path: str, *, recursive: bool = False) -> bool:
        """Delete a file or directory from storage.

        Parameters
        ----------
        relative_path:
            Path relative to the base directory.
        recursive:
            If ``True`` and the path is a directory, delete it and
            all contents recursively.

        Returns
        -------
        bool
            ``True`` if the path was found and deleted.

        Raises
        ------
        IntegrationError
            If deletion fails or a non-empty directory is targeted
            without ``recursive=True``.
        """
        target = self._resolve_path(relative_path)

        if not target.exists():
            logger.debug("Delete target does not exist: %s", relative_path)
            return False

        log_event(
            logger,
            "local_disk.delete",
            path=relative_path,
            is_directory=target.is_dir(),
            recursive=recursive,
        )
        self._track_operation()

        try:
            if target.is_dir():
                if recursive:
                    shutil.rmtree(target)
                else:
                    # Only delete if empty
                    if any(target.iterdir()):
                        raise IntegrationError(
                            f"Directory is not empty: {relative_path!r}. "
                            f"Use recursive=True to delete non-empty directories.",
                            details={"absolute_path": str(target)},
                        )
                    target.rmdir()
            else:
                target.unlink()

            return True

        except OSError as exc:
            raise IntegrationError(
                f"Failed to delete: {relative_path!r}",
                details={"absolute_path": str(target), "error": str(exc)},
                cause=exc,
            ) from exc

    async def get_usage(self) -> DiskUsage:
        """Return disk usage statistics for the storage volume and directory.

        Walks the entire storage directory tree to compute the total
        size of managed files, and queries the OS for overall disk usage.

        Returns
        -------
        DiskUsage
            Comprehensive disk usage information.
        """
        log_event(logger, "local_disk.get_usage")
        self._track_operation()

        # Overall disk usage from OS
        try:
            disk = shutil.disk_usage(self._base_dir)
            total_bytes = disk.total
            used_bytes = disk.used
            free_bytes = disk.free
            usage_percent = round((used_bytes / total_bytes) * 100, 2) if total_bytes > 0 else 0.0
        except OSError as exc:
            logger.warning("Could not query disk usage: %s", exc)
            total_bytes = 0
            used_bytes = 0
            free_bytes = 0
            usage_percent = 0.0

        # Storage directory size
        storage_dir_bytes = 0
        storage_file_count = 0
        try:
            for path in self._base_dir.rglob("*"):
                if path.is_file():
                    storage_file_count += 1
                    try:
                        storage_dir_bytes += path.stat().st_size
                    except OSError:
                        pass
        except OSError as exc:
            logger.warning("Could not walk storage directory: %s", exc)

        usage = DiskUsage(
            total_bytes=total_bytes,
            used_bytes=used_bytes,
            free_bytes=free_bytes,
            usage_percent=usage_percent,
            storage_dir_bytes=storage_dir_bytes,
            storage_file_count=storage_file_count,
            below_minimum_free=free_bytes < self._min_free_bytes,
        )

        if usage.below_minimum_free:
            logger.warning(
                "Disk space below minimum threshold: %d MB free (minimum: %d MB)",
                free_bytes // (1024 * 1024),
                self._min_free_bytes // (1024 * 1024),
            )

        return usage

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def base_dir(self) -> Path:
        """Return the resolved base directory path."""
        return self._base_dir

    @property
    def operation_count(self) -> int:
        """Return the total number of storage operations performed."""
        return self._operation_count

    def __repr__(self) -> str:
        return (
            f"LocalDiskStorage(base_dir={str(self._base_dir)!r}, "
            f"operations={self._operation_count})"
        )
