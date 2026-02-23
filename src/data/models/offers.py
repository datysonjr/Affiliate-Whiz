"""
data.models.offers
~~~~~~~~~~~~~~~~~~

Offer database model and CRUD operations for the OpenClaw system.

This module provides the *persistence layer* for affiliate offers.  It
complements :mod:`domains.offers.models` (which defines the in-memory
domain model with scoring logic) by mapping offers to a SQLite table
with full CRUD support.

Each offer record stores the essential fields needed for pipeline decisions:
commission rate, composite score, quality tier, and active/inactive flag.
The research agent writes offers here after discovery, and the content
pipeline reads them when selecting which products to promote.

Design references:
    - ARCHITECTURE.md  Section 5 (Data Layer)
    - domains/offers/models.py  (domain-level Offer and OfferScore)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.core.logger import get_logger, log_event

logger = get_logger("data.models.offers")

# SQL for the offers table -- executed by Database.migrate() or directly in tests.
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS offers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    merchant        TEXT    NOT NULL,
    network         TEXT    NOT NULL DEFAULT '',
    commission_rate REAL    NOT NULL DEFAULT 0.0,
    score           REAL    NOT NULL DEFAULT 0.0,
    tier            TEXT    NOT NULL DEFAULT 'D',
    active          INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_offers_merchant ON offers(merchant);
CREATE INDEX IF NOT EXISTS idx_offers_tier ON offers(tier);
CREATE INDEX IF NOT EXISTS idx_offers_active ON offers(active);
"""


@dataclass
class OfferRecord:
    """Database-level representation of an affiliate offer.

    This is a flat, persistence-oriented model suitable for SQLite storage.
    For the richer domain model with scoring sub-components, see
    :class:`domains.offers.models.Offer`.

    Attributes
    ----------
    id:
        Auto-incremented primary key (``None`` before first save).
    name:
        Human-readable offer or product name.
    merchant:
        Name of the merchant or brand behind the offer.
    network:
        Affiliate network that surfaced this offer (e.g. ``"ShareASale"``).
    commission_rate:
        Commission percentage as a decimal (e.g. 0.08 for 8%).
    score:
        Composite quality score on a 0-100 scale.
    tier:
        Quality tier classification -- ``A``, ``B``, ``C``, or ``D``.
    active:
        Whether the offer is currently accepting affiliates.
    created_at:
        UTC timestamp when the record was created.
    updated_at:
        UTC timestamp of the most recent update.
    """

    id: Optional[int] = None
    name: str = ""
    merchant: str = ""
    network: str = ""
    commission_rate: float = 0.0
    score: float = 0.0
    tier: str = "D"
    active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    @property
    def is_promotable(self) -> bool:
        """Return ``True`` if the offer is active and tier A, B, or C."""
        return self.active and self.tier in ("A", "B", "C")

    @property
    def commission_pct(self) -> str:
        """Return the commission rate as a human-readable percentage string."""
        return f"{self.commission_rate * 100:.1f}%"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the offer record to a plain dictionary."""
        data = asdict(self)
        data["active"] = bool(data["active"])
        return data


class OfferRepository:
    """CRUD operations for :class:`OfferRecord` records.

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
        """Create the ``offers`` table and indexes if they do not exist."""
        self._db.execute(CREATE_TABLE_SQL)

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(self, offer: OfferRecord) -> OfferRecord:
        """Insert a new offer and return it with its generated ``id``.

        Parameters
        ----------
        offer:
            An ``OfferRecord`` instance.  The ``id`` field is ignored.

        Returns
        -------
        OfferRecord
            The same instance with ``id``, ``created_at``, and ``updated_at``
            populated.

        Raises
        ------
        DatabaseError
            If the insert fails.
        """
        now = datetime.now(timezone.utc).isoformat()

        cursor = self._db.execute(
            """
            INSERT INTO offers
                (name, merchant, network, commission_rate, score, tier,
                 active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                offer.name,
                offer.merchant,
                offer.network,
                offer.commission_rate,
                offer.score,
                offer.tier,
                int(offer.active),
                now,
                now,
            ),
        )

        offer.id = cursor.lastrowid
        offer.created_at = now
        offer.updated_at = now
        log_event(
            logger, "offer.created",
            id=offer.id, name=offer.name, merchant=offer.merchant,
        )
        return offer

    def create_many(self, offers: List[OfferRecord]) -> List[OfferRecord]:
        """Bulk-insert multiple offers.

        Parameters
        ----------
        offers:
            List of ``OfferRecord`` instances to insert.

        Returns
        -------
        list[OfferRecord]
            The same instances with generated ``id`` fields populated.
        """
        created: List[OfferRecord] = []
        for offer in offers:
            created.append(self.create(offer))
        log_event(logger, "offer.bulk_created", count=len(created))
        return created

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_by_id(self, offer_id: int) -> Optional[OfferRecord]:
        """Fetch a single offer by primary key.

        Returns
        -------
        OfferRecord or None
            The offer if found, otherwise ``None``.
        """
        row = self._db.fetch_one(
            "SELECT * FROM offers WHERE id = ?", (offer_id,)
        )
        if row is None:
            return None
        return self._row_to_offer(row)

    def get_by_merchant(self, merchant: str) -> List[OfferRecord]:
        """Fetch all offers from a specific merchant.

        Parameters
        ----------
        merchant:
            Merchant name to filter by.

        Returns
        -------
        list[OfferRecord]
            All matching offers.
        """
        rows = self._db.fetch_all(
            "SELECT * FROM offers WHERE merchant = ? ORDER BY score DESC",
            (merchant,),
        )
        return [self._row_to_offer(r) for r in rows]

    def list_all(
        self,
        *,
        tier: Optional[str] = None,
        network: Optional[str] = None,
        active_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> List[OfferRecord]:
        """Return offers matching optional filters.

        Parameters
        ----------
        tier:
            Filter by quality tier (e.g. ``"A"``).
        network:
            Filter by affiliate network name.
        active_only:
            If ``True``, only return active offers.
        limit:
            Maximum rows to return.
        offset:
            Number of rows to skip (for pagination).

        Returns
        -------
        list[OfferRecord]
            Matching offers ordered by score descending.
        """
        clauses: List[str] = []
        params: List[Any] = []

        if tier is not None:
            clauses.append("tier = ?")
            params.append(tier)
        if network is not None:
            clauses.append("network = ?")
            params.append(network)
        if active_only:
            clauses.append("active = 1")

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM offers {where} ORDER BY score DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self._db.fetch_all(sql, params)
        return [self._row_to_offer(r) for r in rows]

    def list_promotable(self, *, limit: int = 50) -> List[OfferRecord]:
        """Return active offers in tiers A, B, or C, ordered by score.

        This is the primary query used by the content pipeline when
        selecting which offers to write about.

        Parameters
        ----------
        limit:
            Maximum number of offers to return.

        Returns
        -------
        list[OfferRecord]
            Promotable offers sorted by score descending.
        """
        rows = self._db.fetch_all(
            """
            SELECT * FROM offers
             WHERE active = 1 AND tier IN ('A', 'B', 'C')
             ORDER BY score DESC
             LIMIT ?
            """,
            (limit,),
        )
        return [self._row_to_offer(r) for r in rows]

    def count(self, *, active_only: bool = False) -> int:
        """Return the total number of offers.

        Parameters
        ----------
        active_only:
            If ``True``, only count active offers.

        Returns
        -------
        int
            Number of matching offers.
        """
        if active_only:
            row = self._db.fetch_one(
                "SELECT COUNT(*) AS cnt FROM offers WHERE active = 1"
            )
        else:
            row = self._db.fetch_one("SELECT COUNT(*) AS cnt FROM offers")
        return int(row["cnt"]) if row else 0

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(self, offer: OfferRecord) -> OfferRecord:
        """Persist changes to an existing offer.

        Parameters
        ----------
        offer:
            An ``OfferRecord`` with a valid ``id``.

        Returns
        -------
        OfferRecord
            The updated offer with a refreshed ``updated_at`` timestamp.
        """
        now = datetime.now(timezone.utc).isoformat()

        self._db.execute(
            """
            UPDATE offers
               SET name = ?, merchant = ?, network = ?, commission_rate = ?,
                   score = ?, tier = ?, active = ?, updated_at = ?
             WHERE id = ?
            """,
            (
                offer.name,
                offer.merchant,
                offer.network,
                offer.commission_rate,
                offer.score,
                offer.tier,
                int(offer.active),
                now,
                offer.id,
            ),
        )

        offer.updated_at = now
        log_event(logger, "offer.updated", id=offer.id)
        return offer

    def deactivate(self, offer_id: int) -> bool:
        """Mark an offer as inactive.

        Parameters
        ----------
        offer_id:
            The offer's ``id``.

        Returns
        -------
        bool
            ``True`` if the offer was found and deactivated.
        """
        now = datetime.now(timezone.utc).isoformat()
        cursor = self._db.execute(
            "UPDATE offers SET active = 0, updated_at = ? WHERE id = ?",
            (now, offer_id),
        )
        if cursor.rowcount > 0:
            log_event(logger, "offer.deactivated", id=offer_id)
            return True
        return False

    def activate(self, offer_id: int) -> bool:
        """Mark an offer as active.

        Parameters
        ----------
        offer_id:
            The offer's ``id``.

        Returns
        -------
        bool
            ``True`` if the offer was found and activated.
        """
        now = datetime.now(timezone.utc).isoformat()
        cursor = self._db.execute(
            "UPDATE offers SET active = 1, updated_at = ? WHERE id = ?",
            (now, offer_id),
        )
        if cursor.rowcount > 0:
            log_event(logger, "offer.activated", id=offer_id)
            return True
        return False

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete(self, offer_id: int) -> bool:
        """Delete an offer by primary key.

        Parameters
        ----------
        offer_id:
            The offer's ``id``.

        Returns
        -------
        bool
            ``True`` if a row was deleted, ``False`` if no such offer.
        """
        cursor = self._db.execute(
            "DELETE FROM offers WHERE id = ?", (offer_id,)
        )
        deleted = cursor.rowcount > 0
        if deleted:
            log_event(logger, "offer.deleted", id=offer_id)
        return deleted

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_offer(row: Dict[str, Any]) -> OfferRecord:
        """Convert a database row dict into an ``OfferRecord`` dataclass."""
        return OfferRecord(
            id=row["id"],
            name=row["name"],
            merchant=row["merchant"],
            network=row.get("network", ""),
            commission_rate=row.get("commission_rate", 0.0),
            score=row.get("score", 0.0),
            tier=row.get("tier", "D"),
            active=bool(row.get("active", 1)),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )
