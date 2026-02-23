"""
data.models.campaigns
~~~~~~~~~~~~~~~~~~~~~

Campaign model and CRUD operations for the OpenClaw system.

A campaign is a top-level organisational unit that groups one or more sites
under a shared niche, budget, and schedule.  The orchestrator creates campaigns
based on the niche configuration and tracks their financial performance
(budget vs. actual spend vs. revenue) over time.

Design references:
    - ARCHITECTURE.md  Section 5 (Data Layer)
    - config/niches.yaml  (niche definitions that seed campaigns)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.core.logger import get_logger, log_event

logger = get_logger("data.models.campaigns")

# SQL for the campaigns table -- executed by Database.migrate() or
# directly in tests.
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS campaigns (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL UNIQUE,
    niche_id     TEXT    NOT NULL,
    sites        TEXT    NOT NULL DEFAULT '[]',
    status       TEXT    NOT NULL DEFAULT 'draft',
    start_date   TEXT,
    budget       REAL    NOT NULL DEFAULT 0.0,
    actual_spend REAL    NOT NULL DEFAULT 0.0,
    revenue      REAL    NOT NULL DEFAULT 0.0,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""


@dataclass
class Campaign:
    """Represents a single affiliate marketing campaign.

    Attributes
    ----------
    id:
        Auto-incremented primary key (``None`` before first save).
    name:
        Human-readable campaign name (unique).
    niche_id:
        Foreign-key reference to the target niche (from ``niches.yaml``).
    sites:
        List of site IDs associated with this campaign.
    status:
        Lifecycle status -- ``draft``, ``active``, ``paused``, ``completed``,
        or ``archived``.
    start_date:
        The date the campaign was activated.
    budget:
        Total allocated budget in USD.
    actual_spend:
        Running total of money spent so far.
    revenue:
        Running total of affiliate revenue earned.
    created_at:
        UTC timestamp when the record was created.
    updated_at:
        UTC timestamp of the most recent update.
    """

    id: Optional[int] = None
    name: str = ""
    niche_id: str = ""
    sites: List[int] = field(default_factory=list)
    status: str = "draft"
    start_date: Optional[str] = None
    budget: float = 0.0
    actual_spend: float = 0.0
    revenue: float = 0.0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    @property
    def roi(self) -> float:
        """Return the current return on investment as a percentage.

        Returns ``0.0`` if no spend has been recorded yet.
        """
        if self.actual_spend <= 0:
            return 0.0
        return ((self.revenue - self.actual_spend) / self.actual_spend) * 100.0

    @property
    def budget_remaining(self) -> float:
        """Return the unspent portion of the budget."""
        return max(0.0, self.budget - self.actual_spend)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the campaign to a plain dictionary.

        The ``sites`` field is left as a Python list (not JSON-encoded).
        """
        data = asdict(self)
        return data


class CampaignRepository:
    """CRUD operations for :class:`Campaign` records.

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
        """Create the ``campaigns`` table if it does not exist."""
        self._db.execute(CREATE_TABLE_SQL)

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(self, campaign: Campaign) -> Campaign:
        """Insert a new campaign and return it with its generated ``id``.

        Parameters
        ----------
        campaign:
            A ``Campaign`` instance.  The ``id`` field is ignored.

        Returns
        -------
        Campaign
            The same instance with ``id``, ``created_at``, and ``updated_at``
            populated.

        Raises
        ------
        DatabaseError
            If the insert fails (e.g. duplicate name).
        """
        now = datetime.now(timezone.utc).isoformat()
        sites_json = json.dumps(campaign.sites)

        cursor = self._db.execute(
            """
            INSERT INTO campaigns
                (name, niche_id, sites, status, start_date, budget,
                 actual_spend, revenue, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.name,
                campaign.niche_id,
                sites_json,
                campaign.status,
                campaign.start_date,
                campaign.budget,
                campaign.actual_spend,
                campaign.revenue,
                now,
                now,
            ),
        )

        campaign.id = cursor.lastrowid
        campaign.created_at = now
        campaign.updated_at = now
        log_event(logger, "campaign.created", id=campaign.id, name=campaign.name)
        return campaign

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_by_id(self, campaign_id: int) -> Optional[Campaign]:
        """Fetch a single campaign by primary key.

        Returns
        -------
        Campaign or None
            The campaign if found, otherwise ``None``.
        """
        row = self._db.fetch_one(
            "SELECT * FROM campaigns WHERE id = ?", (campaign_id,)
        )
        if row is None:
            return None
        return self._row_to_campaign(row)

    def get_by_name(self, name: str) -> Optional[Campaign]:
        """Fetch a single campaign by its unique name.

        Returns
        -------
        Campaign or None
            The campaign if found, otherwise ``None``.
        """
        row = self._db.fetch_one(
            "SELECT * FROM campaigns WHERE name = ?", (name,)
        )
        if row is None:
            return None
        return self._row_to_campaign(row)

    def list_all(
        self,
        *,
        status: Optional[str] = None,
        niche_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Campaign]:
        """Return campaigns matching optional filters.

        Parameters
        ----------
        status:
            Filter by status (e.g. ``"active"``).
        niche_id:
            Filter by niche identifier.
        limit:
            Maximum rows to return.
        offset:
            Number of rows to skip (for pagination).

        Returns
        -------
        list[Campaign]
            Matching campaigns ordered by ``id`` descending.
        """
        clauses: List[str] = []
        params: List[Any] = []

        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if niche_id is not None:
            clauses.append("niche_id = ?")
            params.append(niche_id)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM campaigns {where} ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self._db.fetch_all(sql, params)
        return [self._row_to_campaign(r) for r in rows]

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(self, campaign: Campaign) -> Campaign:
        """Persist changes to an existing campaign.

        Parameters
        ----------
        campaign:
            A ``Campaign`` with a valid ``id``.

        Returns
        -------
        Campaign
            The updated campaign with a refreshed ``updated_at`` timestamp.
        """
        now = datetime.now(timezone.utc).isoformat()
        sites_json = json.dumps(campaign.sites)

        self._db.execute(
            """
            UPDATE campaigns
               SET name = ?, niche_id = ?, sites = ?, status = ?,
                   start_date = ?, budget = ?, actual_spend = ?,
                   revenue = ?, updated_at = ?
             WHERE id = ?
            """,
            (
                campaign.name,
                campaign.niche_id,
                sites_json,
                campaign.status,
                campaign.start_date,
                campaign.budget,
                campaign.actual_spend,
                campaign.revenue,
                now,
                campaign.id,
            ),
        )

        campaign.updated_at = now
        log_event(logger, "campaign.updated", id=campaign.id)
        return campaign

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete(self, campaign_id: int) -> bool:
        """Delete a campaign by primary key.

        Parameters
        ----------
        campaign_id:
            The campaign's ``id``.

        Returns
        -------
        bool
            ``True`` if a row was deleted, ``False`` if no such campaign.
        """
        cursor = self._db.execute(
            "DELETE FROM campaigns WHERE id = ?", (campaign_id,)
        )
        deleted = cursor.rowcount > 0
        if deleted:
            log_event(logger, "campaign.deleted", id=campaign_id)
        return deleted

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_campaign(row: Dict[str, Any]) -> Campaign:
        """Convert a database row dict into a ``Campaign`` dataclass."""
        sites = row.get("sites", "[]")
        if isinstance(sites, str):
            sites = json.loads(sites)

        return Campaign(
            id=row["id"],
            name=row["name"],
            niche_id=row["niche_id"],
            sites=sites,
            status=row["status"],
            start_date=row.get("start_date"),
            budget=row.get("budget", 0.0),
            actual_spend=row.get("actual_spend", 0.0),
            revenue=row.get("revenue", 0.0),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )
