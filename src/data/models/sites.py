"""
data.models.sites
~~~~~~~~~~~~~~~~~

Site model and CRUD operations for the OpenClaw system.

A site represents an individual affiliate website (e.g. a WordPress blog)
that publishes monetised content under a specific niche.  Sites are owned
by campaigns and tracked for traffic, post count, and revenue metrics so
the orchestrator can make allocation and scaling decisions.

Design references:
    - ARCHITECTURE.md  Section 5 (Data Layer)
    - config/sites.yaml  (site definitions)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.core.logger import get_logger, log_event

logger = get_logger("data.models.sites")

# SQL for the sites table -- executed by Database.migrate() or directly in tests.
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sites (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    domain       TEXT    NOT NULL UNIQUE,
    niche_id     TEXT    NOT NULL,
    cms_type     TEXT    NOT NULL DEFAULT 'wordpress',
    status       TEXT    NOT NULL DEFAULT 'provisioning',
    posts_count  INTEGER NOT NULL DEFAULT 0,
    traffic      INTEGER NOT NULL DEFAULT 0,
    revenue      REAL    NOT NULL DEFAULT 0.0,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""


@dataclass
class Site:
    """Represents a single affiliate website in the OpenClaw network.

    Attributes
    ----------
    id:
        Auto-incremented primary key (``None`` before first save).
    domain:
        Fully qualified domain name (e.g. ``"best-home-office.com"``).
    niche_id:
        Identifier linking the site to its target niche (from ``niches.yaml``).
    cms_type:
        Content management system type -- ``wordpress``, ``ghost``,
        ``static``, or ``headless``.
    status:
        Lifecycle status -- ``provisioning``, ``active``, ``paused``,
        ``decommissioned``.
    posts_count:
        Total number of published posts on the site.
    traffic:
        Estimated monthly organic traffic (sessions).
    revenue:
        Cumulative affiliate revenue earned in USD.
    created_at:
        UTC timestamp when the record was created.
    updated_at:
        UTC timestamp of the most recent update.
    """

    id: Optional[int] = None
    domain: str = ""
    niche_id: str = ""
    cms_type: str = "wordpress"
    status: str = "provisioning"
    posts_count: int = 0
    traffic: int = 0
    revenue: float = 0.0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    @property
    def revenue_per_post(self) -> float:
        """Return average revenue per published post.

        Returns ``0.0`` when no posts have been published.
        """
        if self.posts_count <= 0:
            return 0.0
        return self.revenue / self.posts_count

    @property
    def traffic_per_post(self) -> float:
        """Return average monthly traffic per published post."""
        if self.posts_count <= 0:
            return 0.0
        return self.traffic / self.posts_count

    @property
    def is_active(self) -> bool:
        """Return ``True`` if the site is in an active publishing state."""
        return self.status == "active"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the site to a plain dictionary."""
        return asdict(self)


class SiteRepository:
    """CRUD operations for :class:`Site` records.

    All methods accept a *database* handle (``data.db.Database``) which must
    already be connected.

    Parameters
    ----------
    db:
        An initialised ``Database`` instance.
    """

    def __init__(self, db: Any) -> None:
        self._db = db

    def ensure_table(self) -> None:
        """Create the ``sites`` table if it does not exist."""
        self._db.execute(CREATE_TABLE_SQL)

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(self, site: Site) -> Site:
        """Insert a new site and return it with its generated ``id``.

        Parameters
        ----------
        site:
            A ``Site`` instance.  The ``id`` field is ignored.

        Returns
        -------
        Site
            The same instance with ``id``, ``created_at``, and ``updated_at``
            populated.

        Raises
        ------
        DatabaseError
            If the insert fails (e.g. duplicate domain).
        """
        now = datetime.now(timezone.utc).isoformat()

        cursor = self._db.execute(
            """
            INSERT INTO sites
                (domain, niche_id, cms_type, status, posts_count,
                 traffic, revenue, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                site.domain,
                site.niche_id,
                site.cms_type,
                site.status,
                site.posts_count,
                site.traffic,
                site.revenue,
                now,
                now,
            ),
        )

        site.id = cursor.lastrowid
        site.created_at = now
        site.updated_at = now
        log_event(logger, "site.created", id=site.id, domain=site.domain)
        return site

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_by_id(self, site_id: int) -> Optional[Site]:
        """Fetch a single site by primary key.

        Returns
        -------
        Site or None
            The site if found, otherwise ``None``.
        """
        row = self._db.fetch_one(
            "SELECT * FROM sites WHERE id = ?", (site_id,)
        )
        if row is None:
            return None
        return self._row_to_site(row)

    def get_by_domain(self, domain: str) -> Optional[Site]:
        """Fetch a single site by its unique domain name.

        Returns
        -------
        Site or None
            The site if found, otherwise ``None``.
        """
        row = self._db.fetch_one(
            "SELECT * FROM sites WHERE domain = ?", (domain,)
        )
        if row is None:
            return None
        return self._row_to_site(row)

    def list_all(
        self,
        *,
        status: Optional[str] = None,
        niche_id: Optional[str] = None,
        cms_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Site]:
        """Return sites matching optional filters.

        Parameters
        ----------
        status:
            Filter by status (e.g. ``"active"``).
        niche_id:
            Filter by niche identifier.
        cms_type:
            Filter by CMS type (e.g. ``"wordpress"``).
        limit:
            Maximum rows to return.
        offset:
            Number of rows to skip (for pagination).

        Returns
        -------
        list[Site]
            Matching sites ordered by ``id`` descending.
        """
        clauses: List[str] = []
        params: List[Any] = []

        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if niche_id is not None:
            clauses.append("niche_id = ?")
            params.append(niche_id)
        if cms_type is not None:
            clauses.append("cms_type = ?")
            params.append(cms_type)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM sites {where} ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self._db.fetch_all(sql, params)
        return [self._row_to_site(r) for r in rows]

    def count(self, *, status: Optional[str] = None) -> int:
        """Return the total number of sites, optionally filtered by status.

        Parameters
        ----------
        status:
            If provided, only count sites with this status.

        Returns
        -------
        int
            Number of matching sites.
        """
        if status is not None:
            row = self._db.fetch_one(
                "SELECT COUNT(*) AS cnt FROM sites WHERE status = ?",
                (status,),
            )
        else:
            row = self._db.fetch_one("SELECT COUNT(*) AS cnt FROM sites")
        return int(row["cnt"]) if row else 0

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(self, site: Site) -> Site:
        """Persist changes to an existing site.

        Parameters
        ----------
        site:
            A ``Site`` with a valid ``id``.

        Returns
        -------
        Site
            The updated site with a refreshed ``updated_at`` timestamp.
        """
        now = datetime.now(timezone.utc).isoformat()

        self._db.execute(
            """
            UPDATE sites
               SET domain = ?, niche_id = ?, cms_type = ?, status = ?,
                   posts_count = ?, traffic = ?, revenue = ?, updated_at = ?
             WHERE id = ?
            """,
            (
                site.domain,
                site.niche_id,
                site.cms_type,
                site.status,
                site.posts_count,
                site.traffic,
                site.revenue,
                now,
                site.id,
            ),
        )

        site.updated_at = now
        log_event(logger, "site.updated", id=site.id)
        return site

    def update_metrics(
        self,
        site_id: int,
        *,
        posts_count: Optional[int] = None,
        traffic: Optional[int] = None,
        revenue: Optional[float] = None,
    ) -> None:
        """Update traffic and revenue metrics for a site without overwriting
        other fields.

        Parameters
        ----------
        site_id:
            Primary key of the site to update.
        posts_count:
            New post count (skipped if ``None``).
        traffic:
            New monthly traffic estimate (skipped if ``None``).
        revenue:
            New cumulative revenue (skipped if ``None``).
        """
        sets: List[str] = []
        params: List[Any] = []

        if posts_count is not None:
            sets.append("posts_count = ?")
            params.append(posts_count)
        if traffic is not None:
            sets.append("traffic = ?")
            params.append(traffic)
        if revenue is not None:
            sets.append("revenue = ?")
            params.append(revenue)

        if not sets:
            return

        sets.append("updated_at = ?")
        params.append(datetime.now(timezone.utc).isoformat())
        params.append(site_id)

        sql = f"UPDATE sites SET {', '.join(sets)} WHERE id = ?"
        self._db.execute(sql, params)
        log_event(logger, "site.metrics_updated", id=site_id)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete(self, site_id: int) -> bool:
        """Delete a site by primary key.

        Parameters
        ----------
        site_id:
            The site's ``id``.

        Returns
        -------
        bool
            ``True`` if a row was deleted, ``False`` if no such site.
        """
        cursor = self._db.execute(
            "DELETE FROM sites WHERE id = ?", (site_id,)
        )
        deleted = cursor.rowcount > 0
        if deleted:
            log_event(logger, "site.deleted", id=site_id)
        return deleted

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_site(row: Dict[str, Any]) -> Site:
        """Convert a database row dict into a ``Site`` dataclass."""
        return Site(
            id=row["id"],
            domain=row["domain"],
            niche_id=row["niche_id"],
            cms_type=row.get("cms_type", "wordpress"),
            status=row["status"],
            posts_count=row.get("posts_count", 0),
            traffic=row.get("traffic", 0),
            revenue=row.get("revenue", 0.0),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )
