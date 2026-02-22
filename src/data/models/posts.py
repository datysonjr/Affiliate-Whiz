"""
data.models.posts
~~~~~~~~~~~~~~~~~

Post model and CRUD operations for the OpenClaw system.

A post represents a single piece of affiliate content published on a site.
Posts are created by the content pipeline, reviewed by quality-gate policies,
and tracked for performance (clicks, revenue) after publishing.  The
``content_hash`` field enables duplicate detection so the system never
publishes substantially identical articles.

Design references:
    - ARCHITECTURE.md  Section 5 (Data Layer)
    - core/constants.py  ContentStatus
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.core.logger import get_logger, log_event

logger = get_logger("data.models.posts")

# SQL for the posts table -- executed by Database.migrate() or directly in tests.
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS posts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    title          TEXT    NOT NULL,
    slug           TEXT    NOT NULL,
    site_id        INTEGER NOT NULL,
    status         TEXT    NOT NULL DEFAULT 'draft',
    content_hash   TEXT    NOT NULL DEFAULT '',
    word_count     INTEGER NOT NULL DEFAULT 0,
    published_at   TEXT,
    clicks         INTEGER NOT NULL DEFAULT 0,
    revenue        REAL    NOT NULL DEFAULT 0.0,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_posts_site_id ON posts(site_id);
CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status);
CREATE INDEX IF NOT EXISTS idx_posts_slug ON posts(slug);
CREATE INDEX IF NOT EXISTS idx_posts_content_hash ON posts(content_hash);
"""


@dataclass
class Post:
    """Represents a single published or draft article.

    Attributes
    ----------
    id:
        Auto-incremented primary key (``None`` before first save).
    title:
        Article headline.
    slug:
        URL-safe slug derived from the title (e.g. ``"best-standing-desks-2025"``).
    site_id:
        Foreign key to the :class:`~data.models.sites.Site` this post
        belongs to.
    status:
        Content lifecycle status -- ``draft``, ``review``, ``approved``,
        ``published``, ``unpublished``, ``archived``.
    content_hash:
        SHA-256 hash of the article body used for duplicate detection.
    word_count:
        Total word count of the article content.
    published_at:
        UTC timestamp when the post was published (``None`` if still in draft).
    clicks:
        Total affiliate link clicks tracked for this post.
    revenue:
        Total affiliate revenue attributed to this post in USD.
    created_at:
        UTC timestamp when the record was created.
    updated_at:
        UTC timestamp of the most recent update.
    """

    id: Optional[int] = None
    title: str = ""
    slug: str = ""
    site_id: int = 0
    status: str = "draft"
    content_hash: str = ""
    word_count: int = 0
    published_at: Optional[str] = None
    clicks: int = 0
    revenue: float = 0.0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    @property
    def revenue_per_click(self) -> float:
        """Return revenue per click (EPC).

        Returns ``0.0`` when no clicks have been tracked.
        """
        if self.clicks <= 0:
            return 0.0
        return self.revenue / self.clicks

    @property
    def is_published(self) -> bool:
        """Return ``True`` if the post has been published."""
        return self.status == "published"

    @staticmethod
    def compute_content_hash(content: str) -> str:
        """Compute a SHA-256 hash of the given content string.

        This is used for duplicate detection: two posts with the same
        ``content_hash`` are considered substantially identical.

        Parameters
        ----------
        content:
            The full article body text.

        Returns
        -------
        str
            Hex-encoded SHA-256 digest.
        """
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the post to a plain dictionary."""
        return asdict(self)


class PostRepository:
    """CRUD operations for :class:`Post` records.

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
        """Create the ``posts`` table and indexes if they do not exist."""
        self._db.execute(CREATE_TABLE_SQL)

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(self, post: Post) -> Post:
        """Insert a new post and return it with its generated ``id``.

        Parameters
        ----------
        post:
            A ``Post`` instance.  The ``id`` field is ignored.

        Returns
        -------
        Post
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
            INSERT INTO posts
                (title, slug, site_id, status, content_hash, word_count,
                 published_at, clicks, revenue, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                post.title,
                post.slug,
                post.site_id,
                post.status,
                post.content_hash,
                post.word_count,
                post.published_at,
                post.clicks,
                post.revenue,
                now,
                now,
            ),
        )

        post.id = cursor.lastrowid
        post.created_at = now
        post.updated_at = now
        log_event(logger, "post.created", id=post.id, title=post.title)
        return post

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_by_id(self, post_id: int) -> Optional[Post]:
        """Fetch a single post by primary key.

        Returns
        -------
        Post or None
            The post if found, otherwise ``None``.
        """
        row = self._db.fetch_one(
            "SELECT * FROM posts WHERE id = ?", (post_id,)
        )
        if row is None:
            return None
        return self._row_to_post(row)

    def get_by_slug(self, slug: str, site_id: int) -> Optional[Post]:
        """Fetch a post by slug within a specific site.

        Parameters
        ----------
        slug:
            The URL slug to search for.
        site_id:
            The site that owns the post.

        Returns
        -------
        Post or None
            The post if found, otherwise ``None``.
        """
        row = self._db.fetch_one(
            "SELECT * FROM posts WHERE slug = ? AND site_id = ?",
            (slug, site_id),
        )
        if row is None:
            return None
        return self._row_to_post(row)

    def find_by_content_hash(self, content_hash: str) -> List[Post]:
        """Find all posts with the given content hash (duplicate detection).

        Parameters
        ----------
        content_hash:
            SHA-256 hex digest to search for.

        Returns
        -------
        list[Post]
            All posts matching the hash.  Empty list if none found.
        """
        rows = self._db.fetch_all(
            "SELECT * FROM posts WHERE content_hash = ?", (content_hash,)
        )
        return [self._row_to_post(r) for r in rows]

    def list_all(
        self,
        *,
        site_id: Optional[int] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Post]:
        """Return posts matching optional filters.

        Parameters
        ----------
        site_id:
            Filter by site.
        status:
            Filter by status (e.g. ``"published"``).
        limit:
            Maximum rows to return.
        offset:
            Number of rows to skip (for pagination).

        Returns
        -------
        list[Post]
            Matching posts ordered by ``id`` descending.
        """
        clauses: List[str] = []
        params: List[Any] = []

        if site_id is not None:
            clauses.append("site_id = ?")
            params.append(site_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM posts {where} ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self._db.fetch_all(sql, params)
        return [self._row_to_post(r) for r in rows]

    def count(
        self,
        *,
        site_id: Optional[int] = None,
        status: Optional[str] = None,
    ) -> int:
        """Return the total number of posts matching optional filters.

        Parameters
        ----------
        site_id:
            If provided, only count posts for this site.
        status:
            If provided, only count posts with this status.

        Returns
        -------
        int
            Number of matching posts.
        """
        clauses: List[str] = []
        params: List[Any] = []

        if site_id is not None:
            clauses.append("site_id = ?")
            params.append(site_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT COUNT(*) AS cnt FROM posts {where}"

        row = self._db.fetch_one(sql, params)
        return int(row["cnt"]) if row else 0

    def get_top_performers(
        self,
        *,
        site_id: Optional[int] = None,
        limit: int = 10,
    ) -> List[Post]:
        """Return the top-performing posts ranked by revenue.

        Parameters
        ----------
        site_id:
            Optional site filter.
        limit:
            Number of posts to return.

        Returns
        -------
        list[Post]
            Posts sorted by revenue descending.
        """
        if site_id is not None:
            sql = (
                "SELECT * FROM posts WHERE site_id = ? AND status = 'published' "
                "ORDER BY revenue DESC LIMIT ?"
            )
            params: List[Any] = [site_id, limit]
        else:
            sql = (
                "SELECT * FROM posts WHERE status = 'published' "
                "ORDER BY revenue DESC LIMIT ?"
            )
            params = [limit]

        rows = self._db.fetch_all(sql, params)
        return [self._row_to_post(r) for r in rows]

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(self, post: Post) -> Post:
        """Persist changes to an existing post.

        Parameters
        ----------
        post:
            A ``Post`` with a valid ``id``.

        Returns
        -------
        Post
            The updated post with a refreshed ``updated_at`` timestamp.
        """
        now = datetime.now(timezone.utc).isoformat()

        self._db.execute(
            """
            UPDATE posts
               SET title = ?, slug = ?, site_id = ?, status = ?,
                   content_hash = ?, word_count = ?, published_at = ?,
                   clicks = ?, revenue = ?, updated_at = ?
             WHERE id = ?
            """,
            (
                post.title,
                post.slug,
                post.site_id,
                post.status,
                post.content_hash,
                post.word_count,
                post.published_at,
                post.clicks,
                post.revenue,
                now,
                post.id,
            ),
        )

        post.updated_at = now
        log_event(logger, "post.updated", id=post.id)
        return post

    def publish(self, post_id: int) -> Optional[Post]:
        """Mark a post as published and record the publication timestamp.

        Parameters
        ----------
        post_id:
            The post's ``id``.

        Returns
        -------
        Post or None
            The updated post, or ``None`` if the post was not found.
        """
        now = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            """
            UPDATE posts
               SET status = 'published', published_at = ?, updated_at = ?
             WHERE id = ?
            """,
            (now, now, post_id),
        )
        log_event(logger, "post.published", id=post_id)
        return self.get_by_id(post_id)

    def update_performance(
        self,
        post_id: int,
        *,
        clicks: Optional[int] = None,
        revenue: Optional[float] = None,
    ) -> None:
        """Update click and revenue metrics for a post.

        Parameters
        ----------
        post_id:
            Primary key of the post to update.
        clicks:
            New total click count (skipped if ``None``).
        revenue:
            New total revenue (skipped if ``None``).
        """
        sets: List[str] = []
        params: List[Any] = []

        if clicks is not None:
            sets.append("clicks = ?")
            params.append(clicks)
        if revenue is not None:
            sets.append("revenue = ?")
            params.append(revenue)

        if not sets:
            return

        sets.append("updated_at = ?")
        params.append(datetime.now(timezone.utc).isoformat())
        params.append(post_id)

        sql = f"UPDATE posts SET {', '.join(sets)} WHERE id = ?"
        self._db.execute(sql, params)
        log_event(logger, "post.performance_updated", id=post_id)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete(self, post_id: int) -> bool:
        """Delete a post by primary key.

        Parameters
        ----------
        post_id:
            The post's ``id``.

        Returns
        -------
        bool
            ``True`` if a row was deleted, ``False`` if no such post.
        """
        cursor = self._db.execute(
            "DELETE FROM posts WHERE id = ?", (post_id,)
        )
        deleted = cursor.rowcount > 0
        if deleted:
            log_event(logger, "post.deleted", id=post_id)
        return deleted

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_post(row: Dict[str, Any]) -> Post:
        """Convert a database row dict into a ``Post`` dataclass."""
        return Post(
            id=row["id"],
            title=row["title"],
            slug=row["slug"],
            site_id=row["site_id"],
            status=row["status"],
            content_hash=row.get("content_hash", ""),
            word_count=row.get("word_count", 0),
            published_at=row.get("published_at"),
            clicks=row.get("clicks", 0),
            revenue=row.get("revenue", 0.0),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )
