"""
security.permissions
~~~~~~~~~~~~~~~~~~~~

Role-based access control (RBAC) for agents and operations in OpenClaw.

Provides a :class:`Permissions` class that manages roles, permissions, and
access checks.  Each agent or operator is assigned one or more roles, and
each role grants a set of permissions (e.g. ``publish.create``,
``config.write``, ``killswitch.engage``).

Roles are hierarchical: ``admin`` includes all permissions, ``operator``
includes most operational permissions, and ``agent`` includes only the
minimum permissions needed for automated pipeline execution.

Usage::

    from src.security.permissions import permissions

    permissions.grant("research_agent", "agent")
    if permissions.check_permission("research_agent", "offers.read"):
        fetch_offers()

Design references:
    - ARCHITECTURE.md  Section 8 (Security)
    - AI_RULES.md  Operational Rule #3 (principle of least privilege)
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, FrozenSet, List, Set

from src.core.errors import SecurityError
from src.core.logger import get_logger, log_event

logger = get_logger("security.permissions")

# Default permissions file
DEFAULT_PERMISSIONS_FILE = "data/permissions.json"


# ---------------------------------------------------------------------------
# Built-in role definitions
# ---------------------------------------------------------------------------

BUILT_IN_ROLES: Dict[str, FrozenSet[str]] = {
    "admin": frozenset(
        {
            # Full system access
            "config.read",
            "config.write",
            "offers.read",
            "offers.write",
            "offers.delete",
            "content.read",
            "content.write",
            "content.delete",
            "publish.create",
            "publish.delete",
            "sites.read",
            "sites.write",
            "sites.delete",
            "campaigns.read",
            "campaigns.write",
            "campaigns.delete",
            "experiments.read",
            "experiments.write",
            "experiments.delete",
            "agents.read",
            "agents.manage",
            "agents.kill",
            "metrics.read",
            "metrics.write",
            "vault.read",
            "vault.write",
            "audit.read",
            "killswitch.engage",
            "killswitch.disengage",
            "system.shutdown",
            "system.restart",
        }
    ),
    "operator": frozenset(
        {
            # Operational access (no system-level or vault writes)
            "config.read",
            "config.write",
            "offers.read",
            "offers.write",
            "content.read",
            "content.write",
            "publish.create",
            "sites.read",
            "sites.write",
            "campaigns.read",
            "campaigns.write",
            "experiments.read",
            "experiments.write",
            "agents.read",
            "agents.manage",
            "metrics.read",
            "audit.read",
            "killswitch.engage",
            "killswitch.disengage",
        }
    ),
    "agent": frozenset(
        {
            # Minimum permissions for automated pipeline agents
            "config.read",
            "offers.read",
            "offers.write",
            "content.read",
            "content.write",
            "publish.create",
            "sites.read",
            "campaigns.read",
            "experiments.read",
            "experiments.write",
            "metrics.read",
            "metrics.write",
        }
    ),
    "viewer": frozenset(
        {
            # Read-only access
            "config.read",
            "offers.read",
            "content.read",
            "sites.read",
            "campaigns.read",
            "experiments.read",
            "metrics.read",
            "audit.read",
        }
    ),
}


class Permissions:
    """Role-based access control manager.

    Manages the mapping of subjects (agent names, user IDs) to roles and
    checks permissions before sensitive operations.

    Parameters
    ----------
    storage_path:
        Path to the JSON file where role assignments are persisted.
        Parent directories are created on first save.
    """

    def __init__(self, storage_path: str = DEFAULT_PERMISSIONS_FILE) -> None:
        self._storage_path = storage_path
        self._lock = threading.RLock()

        # subject -> set of role names
        self._assignments: Dict[str, Set[str]] = {}

        # Custom role definitions (in addition to BUILT_IN_ROLES)
        self._custom_roles: Dict[str, Set[str]] = {}

        # Load persisted assignments
        self._load()

    # ------------------------------------------------------------------
    # Permission checks
    # ------------------------------------------------------------------

    def check_permission(self, subject: str, permission: str) -> bool:
        """Check whether a subject has a specific permission.

        Parameters
        ----------
        subject:
            The entity requesting access (agent name, user ID, etc.).
        permission:
            The permission to check (e.g. ``"publish.create"``).

        Returns
        -------
        bool
            ``True`` if any of the subject's roles grant the permission.
        """
        with self._lock:
            roles = self._assignments.get(subject, set())
            for role_name in roles:
                role_perms = self._get_role_permissions(role_name)
                if permission in role_perms:
                    return True
            return False

    def require_permission(self, subject: str, permission: str) -> None:
        """Assert that a subject has a permission, raising on failure.

        Parameters
        ----------
        subject:
            The entity requesting access.
        permission:
            The required permission.

        Raises
        ------
        SecurityError
            If the subject does not have the required permission.
        """
        if not self.check_permission(subject, permission):
            raise SecurityError(
                f"Permission denied: {subject!r} lacks {permission!r}",
                details={
                    "subject": subject,
                    "permission": permission,
                    "roles": list(self._assignments.get(subject, set())),
                },
            )

    def get_permissions(self, subject: str) -> Set[str]:
        """Return the full set of permissions for a subject.

        Parameters
        ----------
        subject:
            The entity to inspect.

        Returns
        -------
        set[str]
            Union of all permissions from the subject's assigned roles.
        """
        with self._lock:
            roles = self._assignments.get(subject, set())
            all_perms: Set[str] = set()
            for role_name in roles:
                all_perms.update(self._get_role_permissions(role_name))
            return all_perms

    # ------------------------------------------------------------------
    # Role assignment
    # ------------------------------------------------------------------

    def grant(self, subject: str, role: str) -> None:
        """Assign a role to a subject.

        Parameters
        ----------
        subject:
            The entity to grant the role to.
        role:
            Role name (must be a built-in or custom role).

        Raises
        ------
        SecurityError
            If the role is not defined.
        """
        if role not in BUILT_IN_ROLES and role not in self._custom_roles:
            raise SecurityError(
                f"Unknown role: {role!r}",
                details={
                    "available_roles": list(BUILT_IN_ROLES.keys())
                    + list(self._custom_roles.keys()),
                },
            )

        with self._lock:
            if subject not in self._assignments:
                self._assignments[subject] = set()
            self._assignments[subject].add(role)
            self._save()

        log_event(logger, "permission.granted", subject=subject, role=role)

    def revoke(self, subject: str, role: str) -> bool:
        """Remove a role from a subject.

        Parameters
        ----------
        subject:
            The entity to revoke the role from.
        role:
            Role name to remove.

        Returns
        -------
        bool
            ``True`` if the role was found and removed.
        """
        with self._lock:
            roles = self._assignments.get(subject)
            if roles is None or role not in roles:
                return False
            roles.discard(role)
            if not roles:
                del self._assignments[subject]
            self._save()

        log_event(logger, "permission.revoked", subject=subject, role=role)
        return True

    def revoke_all(self, subject: str) -> bool:
        """Remove all roles from a subject.

        Parameters
        ----------
        subject:
            The entity to strip all roles from.

        Returns
        -------
        bool
            ``True`` if the subject had any roles that were removed.
        """
        with self._lock:
            if subject not in self._assignments:
                return False
            del self._assignments[subject]
            self._save()

        log_event(logger, "permission.revoked_all", subject=subject)
        return True

    # ------------------------------------------------------------------
    # Role queries
    # ------------------------------------------------------------------

    def get_roles(self, subject: str) -> List[str]:
        """Return the roles assigned to a subject.

        Parameters
        ----------
        subject:
            The entity to query.

        Returns
        -------
        list[str]
            Role names assigned to the subject.
        """
        with self._lock:
            return sorted(self._assignments.get(subject, set()))

    def list_subjects(self) -> Dict[str, List[str]]:
        """Return all subjects and their role assignments.

        Returns
        -------
        dict[str, list[str]]
            Mapping of subject to sorted list of role names.
        """
        with self._lock:
            return {
                subject: sorted(roles) for subject, roles in self._assignments.items()
            }

    def list_available_roles(self) -> Dict[str, List[str]]:
        """Return all available roles and their permissions.

        Returns
        -------
        dict[str, list[str]]
            Mapping of role name to sorted list of permission strings.
        """
        result: Dict[str, List[str]] = {}
        for name, perms in BUILT_IN_ROLES.items():
            result[name] = sorted(perms)
        for name, perms in self._custom_roles.items():
            result[name] = sorted(perms)
        return result

    # ------------------------------------------------------------------
    # Custom role management
    # ------------------------------------------------------------------

    def define_role(self, name: str, permissions: Set[str]) -> None:
        """Define a custom role with a specific set of permissions.

        Parameters
        ----------
        name:
            Role name (must not conflict with built-in roles).
        permissions:
            Set of permission strings the role grants.

        Raises
        ------
        SecurityError
            If the name conflicts with a built-in role.
        """
        if name in BUILT_IN_ROLES:
            raise SecurityError(f"Cannot redefine built-in role: {name!r}")
        with self._lock:
            self._custom_roles[name] = set(permissions)
            self._save()
        log_event(logger, "role.defined", name=name, permissions=len(permissions))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_role_permissions(self, role_name: str) -> FrozenSet[str] | Set[str]:
        """Look up the permissions for a role name."""
        if role_name in BUILT_IN_ROLES:
            return BUILT_IN_ROLES[role_name]
        return self._custom_roles.get(role_name, set())

    def _save(self) -> None:
        """Persist role assignments and custom roles to disk."""
        data = {
            "assignments": {
                subject: sorted(roles) for subject, roles in self._assignments.items()
            },
            "custom_roles": {
                name: sorted(perms) for name, perms in self._custom_roles.items()
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
                "Failed to save permissions to %s: %s", self._storage_path, exc
            )

    def _load(self) -> None:
        """Load role assignments and custom roles from disk."""
        path = Path(self._storage_path)
        if not path.is_file():
            return

        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "Failed to load permissions from %s: %s", self._storage_path, exc
            )
            return

        assignments = data.get("assignments", {})
        for subject, roles in assignments.items():
            self._assignments[subject] = set(roles)

        custom_roles = data.get("custom_roles", {})
        for name, perms in custom_roles.items():
            self._custom_roles[name] = set(perms)

    def __repr__(self) -> str:
        return (
            f"Permissions(subjects={len(self._assignments)}, "
            f"custom_roles={len(self._custom_roles)})"
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
permissions = Permissions()
