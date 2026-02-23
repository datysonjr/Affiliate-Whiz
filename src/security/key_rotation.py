"""
security.key_rotation
~~~~~~~~~~~~~~~~~~~~~

Automated API key rotation for the OpenClaw system.

Provides a :class:`KeyRotation` manager that tracks API key expiry dates,
schedules rotations, and coordinates key replacement across the system.
When a key is rotated, the old key is archived (for rollback) and the new
key is stored in the :class:`~security.vault.Vault`.

Supported rotation strategies:
    - **Manual**: Operator provides the new key value.
    - **Scheduled**: Keys are flagged for rotation N days before expiry.
    - **Forced**: Immediate rotation triggered by a security incident.

Usage::

    from src.security.key_rotation import KeyRotation
    from src.security.vault import Vault

    vault = Vault()
    vault.unlock("master-key")

    rotation = KeyRotation(vault)
    rotation.schedule_rotation("OPENAI_API_KEY", expires_in_days=30)

    # Check and rotate expired keys
    rotated = rotation.rotate_all()

Design references:
    - ARCHITECTURE.md  Section 8 (Security)
    - AI_RULES.md  Ethical Guidelines (credential lifecycle)
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.core.logger import get_logger, log_event

logger = get_logger("security.key_rotation")

# Default rotation schedule storage
DEFAULT_ROTATION_FILE = "data/key_rotation.json"

# Default warning threshold (days before expiry to start warning)
DEFAULT_WARNING_DAYS = 7


class KeySchedule:
    """Tracks the rotation schedule for a single API key.

    Attributes
    ----------
    key_name:
        Identifier matching the vault key name (e.g. ``"OPENAI_API_KEY"``).
    expires_at:
        UTC ISO-8601 timestamp when the key expires.
    last_rotated:
        UTC ISO-8601 timestamp of the most recent rotation.
    rotation_interval_days:
        Number of days between automatic rotations.
    auto_rotate:
        Whether to automatically rotate on expiry.
    provider:
        Name of the service provider (for logging context).
    """

    __slots__ = (
        "key_name",
        "expires_at",
        "last_rotated",
        "rotation_interval_days",
        "auto_rotate",
        "provider",
    )

    def __init__(
        self,
        key_name: str,
        *,
        expires_at: Optional[str] = None,
        last_rotated: Optional[str] = None,
        rotation_interval_days: int = 90,
        auto_rotate: bool = False,
        provider: str = "",
    ) -> None:
        self.key_name = key_name
        self.expires_at = expires_at
        self.last_rotated = last_rotated
        self.rotation_interval_days = rotation_interval_days
        self.auto_rotate = auto_rotate
        self.provider = provider

    @property
    def is_expired(self) -> bool:
        """Return ``True`` if the key has passed its expiry date."""
        if not self.expires_at:
            return False
        expiry = datetime.fromisoformat(self.expires_at)
        now = datetime.now(timezone.utc)
        return now >= expiry

    @property
    def days_until_expiry(self) -> Optional[float]:
        """Return the number of days until expiry, or ``None`` if no expiry set."""
        if not self.expires_at:
            return None
        expiry = datetime.fromisoformat(self.expires_at)
        now = datetime.now(timezone.utc)
        delta = expiry - now
        return delta.total_seconds() / 86400.0

    @property
    def needs_rotation(self) -> bool:
        """Return ``True`` if the key is expired or within the warning window."""
        days = self.days_until_expiry
        if days is None:
            return False
        return days <= DEFAULT_WARNING_DAYS

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the schedule to a dictionary."""
        return {
            "key_name": self.key_name,
            "expires_at": self.expires_at,
            "last_rotated": self.last_rotated,
            "rotation_interval_days": self.rotation_interval_days,
            "auto_rotate": self.auto_rotate,
            "provider": self.provider,
            "is_expired": self.is_expired,
            "days_until_expiry": (
                round(self.days_until_expiry, 1)
                if self.days_until_expiry is not None
                else None
            ),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KeySchedule":
        """Create a KeySchedule from a dictionary."""
        return cls(
            key_name=data["key_name"],
            expires_at=data.get("expires_at"),
            last_rotated=data.get("last_rotated"),
            rotation_interval_days=data.get("rotation_interval_days", 90),
            auto_rotate=data.get("auto_rotate", False),
            provider=data.get("provider", ""),
        )


class KeyRotation:
    """Manages API key rotation schedules and execution.

    Parameters
    ----------
    vault:
        The :class:`~security.vault.Vault` instance for reading and
        writing secrets.
    storage_path:
        Path to the JSON file where rotation schedules are persisted.
    """

    def __init__(
        self,
        vault: Any,
        storage_path: str = DEFAULT_ROTATION_FILE,
    ) -> None:
        self._vault = vault
        self._storage_path = storage_path
        self._lock = threading.RLock()
        self._schedules: Dict[str, KeySchedule] = {}
        self._rotation_callbacks: Dict[str, Callable[[str, str], Optional[str]]] = {}
        self._load()

    # ------------------------------------------------------------------
    # Schedule management
    # ------------------------------------------------------------------

    def schedule_rotation(
        self,
        key_name: str,
        *,
        expires_in_days: Optional[int] = None,
        expires_at: Optional[str] = None,
        rotation_interval_days: int = 90,
        auto_rotate: bool = False,
        provider: str = "",
    ) -> KeySchedule:
        """Create or update a rotation schedule for an API key.

        Parameters
        ----------
        key_name:
            The key identifier in the vault.
        expires_in_days:
            Number of days from now until the key expires.  Ignored if
            ``expires_at`` is provided.
        expires_at:
            Explicit expiry timestamp (ISO-8601).
        rotation_interval_days:
            Days between automatic rotations (used to compute next expiry
            after rotation).
        auto_rotate:
            If ``True``, the key will be rotated automatically when
            ``rotate_all()`` is called and the key is within the warning
            window.
        provider:
            Service provider name for logging.

        Returns
        -------
        KeySchedule
            The created or updated schedule.
        """
        if expires_at is None and expires_in_days is not None:
            expiry = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
            expires_at = expiry.isoformat()

        with self._lock:
            schedule = KeySchedule(
                key_name=key_name,
                expires_at=expires_at,
                last_rotated=datetime.now(timezone.utc).isoformat(),
                rotation_interval_days=rotation_interval_days,
                auto_rotate=auto_rotate,
                provider=provider,
            )
            self._schedules[key_name] = schedule
            self._save()

        log_event(
            logger,
            "key_rotation.scheduled",
            key=key_name,
            expires_at=expires_at,
            interval_days=rotation_interval_days,
        )
        return schedule

    def get_expiry(self, key_name: str) -> Optional[str]:
        """Return the expiry timestamp for a key.

        Parameters
        ----------
        key_name:
            The key identifier.

        Returns
        -------
        str or None
            ISO-8601 expiry timestamp, or ``None`` if no schedule exists.
        """
        with self._lock:
            schedule = self._schedules.get(key_name)
            if schedule is None:
                return None
            return schedule.expires_at

    def get_schedule(self, key_name: str) -> Optional[Dict[str, Any]]:
        """Return the full schedule for a key as a dictionary.

        Parameters
        ----------
        key_name:
            The key identifier.

        Returns
        -------
        dict or None
            Schedule data, or ``None`` if no schedule exists.
        """
        with self._lock:
            schedule = self._schedules.get(key_name)
            if schedule is None:
                return None
            return schedule.to_dict()

    def list_schedules(self) -> List[Dict[str, Any]]:
        """Return all rotation schedules.

        Returns
        -------
        list[dict]
            All schedules as dictionaries, sorted by expiry date.
        """
        with self._lock:
            schedules = [s.to_dict() for s in self._schedules.values()]
            schedules.sort(
                key=lambda s: s.get("expires_at") or "9999",
            )
            return schedules

    def get_expiring_soon(
        self, days: int = DEFAULT_WARNING_DAYS
    ) -> List[Dict[str, Any]]:
        """Return keys that will expire within the given number of days.

        Parameters
        ----------
        days:
            Warning threshold in days.

        Returns
        -------
        list[dict]
            Schedules for keys expiring soon.
        """
        with self._lock:
            results: List[Dict[str, Any]] = []
            for schedule in self._schedules.values():
                remaining = schedule.days_until_expiry
                if remaining is not None and remaining <= days:
                    results.append(schedule.to_dict())
            return results

    # ------------------------------------------------------------------
    # Rotation execution
    # ------------------------------------------------------------------

    def register_callback(
        self,
        key_name: str,
        callback: Callable[[str, str], Optional[str]],
    ) -> None:
        """Register a callback to generate a new key value during rotation.

        The callback receives ``(key_name, old_value)`` and should return
        the new key value.  If it returns ``None``, the rotation is skipped.

        Parameters
        ----------
        key_name:
            The key this callback applies to.
        callback:
            Function that generates the replacement key.
        """
        self._rotation_callbacks[key_name] = callback

    def rotate_key(
        self,
        key_name: str,
        new_value: Optional[str] = None,
    ) -> bool:
        """Rotate a single API key.

        If ``new_value`` is not provided and a callback is registered for
        this key, the callback is invoked to generate the new value.

        Parameters
        ----------
        key_name:
            The key to rotate.
        new_value:
            The replacement value.  If ``None``, the registered callback
            is used.

        Returns
        -------
        bool
            ``True`` if the key was successfully rotated.

        Raises
        ------
        SecurityError
            If the vault is locked or the key cannot be rotated.
        """
        with self._lock:
            # Get old value for callback
            try:
                old_value = self._vault.get_secret(key_name, default="")
            except Exception:
                old_value = ""

            # Generate new value if not provided
            if new_value is None:
                callback = self._rotation_callbacks.get(key_name)
                if callback is not None:
                    try:
                        new_value = callback(key_name, old_value or "")
                    except Exception as exc:
                        logger.error(
                            "Rotation callback failed for %s: %s",
                            key_name,
                            exc,
                        )
                        return False

            if new_value is None:
                logger.warning("No new value provided for key rotation: %s", key_name)
                return False

            # Store the new value
            self._vault.store_secret(key_name, new_value)

            # Archive the old value (if it existed)
            if old_value:
                archive_key = f"_archived_{key_name}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
                self._vault.store_secret(archive_key, old_value)

            # Update schedule
            now = datetime.now(timezone.utc)
            schedule = self._schedules.get(key_name)
            if schedule is not None:
                schedule.last_rotated = now.isoformat()
                schedule.expires_at = (
                    now + timedelta(days=schedule.rotation_interval_days)
                ).isoformat()
            else:
                schedule = KeySchedule(
                    key_name=key_name,
                    last_rotated=now.isoformat(),
                    expires_at=(now + timedelta(days=90)).isoformat(),
                )
                self._schedules[key_name] = schedule

            self._save()

        log_event(
            logger,
            "key_rotation.rotated",
            key=key_name,
            next_expiry=schedule.expires_at,
        )
        return True

    def rotate_all(self) -> List[str]:
        """Rotate all keys that are expired or within the warning window.

        Only keys with ``auto_rotate=True`` are rotated automatically.
        Keys without auto-rotate are logged as warnings.

        Returns
        -------
        list[str]
            Names of keys that were successfully rotated.
        """
        rotated: List[str] = []
        warnings: List[str] = []

        with self._lock:
            for key_name, schedule in list(self._schedules.items()):
                if not schedule.needs_rotation:
                    continue

                if schedule.auto_rotate:
                    if self.rotate_key(key_name):
                        rotated.append(key_name)
                    else:
                        warnings.append(key_name)
                else:
                    if schedule.is_expired:
                        logger.warning(
                            "Key %s is expired but auto_rotate is disabled",
                            key_name,
                        )
                    else:
                        logger.info(
                            "Key %s expires in %.1f days (auto_rotate disabled)",
                            key_name,
                            schedule.days_until_expiry,
                        )
                    warnings.append(key_name)

        if rotated:
            log_event(
                logger,
                "key_rotation.batch_complete",
                rotated=rotated,
                warnings=warnings,
            )

        return rotated

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self) -> None:
        """Persist rotation schedules to disk."""
        data = {
            "schedules": {
                name: schedule.to_dict() for name, schedule in self._schedules.items()
            },
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        path = Path(self._storage_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with path.open("w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except OSError as exc:
            logger.warning(
                "Failed to save rotation schedules to %s: %s",
                self._storage_path,
                exc,
            )

    def _load(self) -> None:
        """Load rotation schedules from disk."""
        path = Path(self._storage_path)
        if not path.is_file():
            return

        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "Failed to load rotation schedules from %s: %s",
                self._storage_path,
                exc,
            )
            return

        schedules = data.get("schedules", {})
        for name, sched_data in schedules.items():
            self._schedules[name] = KeySchedule.from_dict(sched_data)

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        expired = sum(1 for s in self._schedules.values() if s.is_expired)
        return f"KeyRotation(keys={len(self._schedules)}, expired={expired})"
