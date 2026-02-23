"""
data.db
~~~~~~~

SQLite database layer for the OpenClaw system.

Provides a :class:`Database` class that wraps Python's built-in ``sqlite3``
module with connection pooling (via a simple reusable-connection pool),
automatic migration support, and convenience methods for common query
patterns.  All database interactions in OpenClaw flow through this single
class so connection lifecycle, WAL mode, and schema versioning are managed
in one place.

Design references:
    - ARCHITECTURE.md  Section 5 (Data Layer)
    - core/constants.py  DEFAULT_DB_PATH
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Sequence, Tuple

from src.core.constants import DEFAULT_DB_PATH
from src.core.errors import OpenClawError
from src.core.logger import get_logger, log_event

logger = get_logger("data.db")


class DatabaseError(OpenClawError):
    """Raised when a database operation fails."""


class MigrationError(DatabaseError):
    """Raised when a schema migration fails."""


class Database:
    """SQLite database manager with connection pooling and migration support.

    The pool is a simple thread-local connection cache -- each thread gets its
    own ``sqlite3.Connection`` so there is no contention.  WAL mode is enabled
    on every connection to allow concurrent readers while a single writer is
    active.

    Parameters
    ----------
    db_path:
        Filesystem path to the SQLite database file.  Parent directories are
        created automatically.  Defaults to ``DEFAULT_DB_PATH`` from
        ``core.constants``.
    pool_size:
        Maximum number of cached connections.  In practice each thread holds
        one connection, so this acts as a soft upper bound.
    """

    def __init__(
        self,
        db_path: str = DEFAULT_DB_PATH,
        pool_size: int = 5,
    ) -> None:
        self._db_path = db_path
        self._pool_size = pool_size
        self._local = threading.local()
        self._lock = threading.Lock()
        self._pool: List[sqlite3.Connection] = []
        self._connected = False
        self._migrations_dir: str = os.path.join(
            os.path.dirname(__file__), "migrations"
        )

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Initialise the database file and enable WAL mode.

        Creates parent directories and the ``_schema_version`` metadata table
        if they do not yet exist.  Safe to call multiple times.

        Raises
        ------
        DatabaseError
            If the database file cannot be created or opened.
        """
        try:
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            conn = self._get_connection()
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS _schema_version (
                    version     INTEGER PRIMARY KEY,
                    applied_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                    description TEXT    NOT NULL DEFAULT ''
                )
                """
            )
            conn.commit()
            self._connected = True
            log_event(logger, "db.connected", path=self._db_path)
        except sqlite3.Error as exc:
            raise DatabaseError(
                f"Failed to connect to database at {self._db_path}",
                cause=exc,
            ) from exc

    def disconnect(self) -> None:
        """Close all pooled connections and release resources.

        After calling this method, any further query will require a new
        ``connect()`` call.
        """
        with self._lock:
            for conn in self._pool:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass
            self._pool.clear()

        # Close the thread-local connection if present.
        local_conn: sqlite3.Connection | None = getattr(self._local, "connection", None)
        if local_conn is not None:
            try:
                local_conn.close()
            except sqlite3.Error:
                pass
            self._local.connection = None

        self._connected = False
        log_event(logger, "db.disconnected", path=self._db_path)

    def _get_connection(self) -> sqlite3.Connection:
        """Return a connection for the current thread, creating one if needed.

        Connections are stored in ``threading.local`` storage so each thread
        reuses the same handle without mutex overhead.

        Returns
        -------
        sqlite3.Connection
            A ready-to-use connection with ``Row`` row factory.
        """
        conn: Optional[sqlite3.Connection] = getattr(self._local, "connection", None)
        if conn is not None:
            return conn

        # Try to grab one from the pool first.
        with self._lock:
            if self._pool:
                conn = self._pool.pop()
                self._local.connection = conn
                return conn

        # Create a new connection.
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        self._local.connection = conn
        return conn

    def _return_connection(self, conn: sqlite3.Connection) -> None:
        """Return a connection to the pool (called on thread teardown)."""
        with self._lock:
            if len(self._pool) < self._pool_size:
                self._pool.append(conn)
            else:
                conn.close()

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager that wraps a block in an explicit transaction.

        On successful exit the transaction is committed; on exception it is
        rolled back.

        Yields
        ------
        sqlite3.Connection
            The active connection within the transaction.

        Example
        -------
        ::

            with db.transaction() as conn:
                conn.execute("INSERT INTO sites ...")
                conn.execute("UPDATE campaigns ...")
        """
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def execute(
        self,
        sql: str,
        params: Sequence[Any] = (),
    ) -> sqlite3.Cursor:
        """Execute a single SQL statement and return the cursor.

        Parameters
        ----------
        sql:
            SQL statement, optionally with ``?`` placeholders.
        params:
            Values to bind to the placeholders.

        Returns
        -------
        sqlite3.Cursor
            The cursor after execution; callers can inspect
            ``lastrowid`` or ``rowcount``.

        Raises
        ------
        DatabaseError
            On any SQLite error.
        """
        conn = self._get_connection()
        try:
            cursor = conn.execute(sql, params)
            conn.commit()
            return cursor
        except sqlite3.Error as exc:
            conn.rollback()
            raise DatabaseError(
                f"Execute failed: {sql[:120]}",
                details={"sql": sql, "params": list(params)},
                cause=exc,
            ) from exc

    def fetch_one(
        self,
        sql: str,
        params: Sequence[Any] = (),
    ) -> Optional[Dict[str, Any]]:
        """Execute a query and return the first row as a dictionary.

        Parameters
        ----------
        sql:
            SELECT statement.
        params:
            Bind values.

        Returns
        -------
        dict or None
            Column-name-keyed dictionary for the first result row, or
            ``None`` if the query returned no rows.
        """
        conn = self._get_connection()
        try:
            cursor = conn.execute(sql, params)
            row = cursor.fetchone()
            if row is None:
                return None
            return dict(row)
        except sqlite3.Error as exc:
            raise DatabaseError(
                f"fetch_one failed: {sql[:120]}",
                details={"sql": sql, "params": list(params)},
                cause=exc,
            ) from exc

    def fetch_all(
        self,
        sql: str,
        params: Sequence[Any] = (),
    ) -> List[Dict[str, Any]]:
        """Execute a query and return all rows as a list of dictionaries.

        Parameters
        ----------
        sql:
            SELECT statement.
        params:
            Bind values.

        Returns
        -------
        list[dict]
            One dict per result row keyed by column name.  Empty list when
            the query matches nothing.
        """
        conn = self._get_connection()
        try:
            cursor = conn.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as exc:
            raise DatabaseError(
                f"fetch_all failed: {sql[:120]}",
                details={"sql": sql, "params": list(params)},
                cause=exc,
            ) from exc

    # ------------------------------------------------------------------
    # Migration support
    # ------------------------------------------------------------------

    def migrate(self, migrations_dir: Optional[str] = None) -> int:
        """Apply all pending migrations from the migrations directory.

        Migration files must follow the naming convention
        ``NNN_description.sql`` where ``NNN`` is a zero-padded integer
        version number (e.g. ``001_create_sites.sql``).  Files are applied
        in numeric order and each one is recorded in ``_schema_version``
        so it is never re-applied.

        Parameters
        ----------
        migrations_dir:
            Override the default migrations directory.  Defaults to
            ``src/data/migrations/``.

        Returns
        -------
        int
            Number of migrations that were applied in this call.

        Raises
        ------
        MigrationError
            If a migration file cannot be read or its SQL fails to execute.
        """
        target_dir = migrations_dir or self._migrations_dir

        if not os.path.isdir(target_dir):
            logger.info(
                "Migrations directory %s not found -- nothing to apply.", target_dir
            )
            return 0

        # Discover SQL files.
        migration_files: List[Tuple[int, str, str]] = []
        for filename in sorted(os.listdir(target_dir)):
            if not filename.endswith(".sql"):
                continue
            parts = filename.split("_", 1)
            if not parts[0].isdigit():
                continue
            version = int(parts[0])
            filepath = os.path.join(target_dir, filename)
            migration_files.append((version, filename, filepath))

        if not migration_files:
            logger.info("No migration files found in %s.", target_dir)
            return 0

        # Determine already-applied versions.
        applied_versions: set[int] = set()
        try:
            rows = self.fetch_all("SELECT version FROM _schema_version")
            applied_versions = {row["version"] for row in rows}
        except DatabaseError:
            pass  # Table may not exist yet on very first run.

        applied_count = 0
        conn = self._get_connection()

        for version, filename, filepath in migration_files:
            if version in applied_versions:
                continue

            try:
                with open(filepath, "r", encoding="utf-8") as fh:
                    sql = fh.read()
            except OSError as exc:
                raise MigrationError(
                    f"Cannot read migration file {filepath}",
                    cause=exc,
                ) from exc

            try:
                conn.executescript(sql)
                conn.execute(
                    "INSERT INTO _schema_version (version, description) VALUES (?, ?)",
                    (version, filename),
                )
                conn.commit()
                applied_count += 1
                log_event(
                    logger,
                    "db.migration.applied",
                    version=version,
                    filename=filename,
                )
            except sqlite3.Error as exc:
                conn.rollback()
                raise MigrationError(
                    f"Migration {filename} failed",
                    details={"version": version, "filename": filename},
                    cause=exc,
                ) from exc

        log_event(
            logger,
            "db.migrate.complete",
            applied=applied_count,
            total_available=len(migration_files),
        )
        return applied_count

    def get_schema_version(self) -> int:
        """Return the highest applied migration version number.

        Returns
        -------
        int
            Current schema version, or ``0`` if no migrations have been run.
        """
        row = self.fetch_one(
            "SELECT COALESCE(MAX(version), 0) AS version FROM _schema_version"
        )
        return int(row["version"]) if row else 0

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"Database(path={self._db_path!r}, "
            f"connected={self._connected}, "
            f"pool_size={self._pool_size})"
        )
