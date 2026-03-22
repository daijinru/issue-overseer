"""SQLite connection management and migration runner."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import aiosqlite

from mango.config import get_settings

logger = logging.getLogger(__name__)

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Shared connection — opened once by init_db(), reused by get_db_connection().
_shared_connection: aiosqlite.Connection | None = None


async def _open_shared_connection() -> None:
    """Open the shared database connection and configure pragmas."""
    global _shared_connection
    settings = get_settings()
    db_path = str(Path(settings.database.path))
    _shared_connection = await aiosqlite.connect(db_path)
    _shared_connection.row_factory = aiosqlite.Row
    await _shared_connection.execute("PRAGMA foreign_keys=ON")
    await _shared_connection.execute("PRAGMA busy_timeout=5000")


async def close_shared_connection() -> None:
    """Close the shared database connection. Call on shutdown."""
    global _shared_connection
    if _shared_connection is not None:
        await _shared_connection.close()
        _shared_connection = None


async def init_db() -> None:
    """Initialize the database: create directories, run pending migrations.

    This is idempotent — safe to call on every startup.
    """
    settings = get_settings()
    db_path = Path(settings.database.path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(str(db_path)) as db:
        # Enable WAL mode for better concurrent read performance
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")

        # Create migration tracking table
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS _migrations (
                filename TEXT PRIMARY KEY,
                applied_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        await db.commit()

        # Discover and apply pending migrations
        applied = {
            row[0]
            async for row in await db.execute("SELECT filename FROM _migrations")
        }

        migration_files = sorted(_MIGRATIONS_DIR.glob("*.sql"))
        for migration_file in migration_files:
            if migration_file.name in applied:
                continue

            logger.info("Applying migration: %s", migration_file.name)
            sql = migration_file.read_text(encoding="utf-8")
            await db.executescript(sql)
            await db.execute(
                "INSERT INTO _migrations (filename) VALUES (?)",
                (migration_file.name,),
            )
            await db.commit()
            logger.info("Migration applied: %s", migration_file.name)

    # Open the shared connection after migrations are done
    await _open_shared_connection()


@asynccontextmanager
async def get_db_connection() -> AsyncIterator[aiosqlite.Connection]:
    """Yield the shared aiosqlite connection with row_factory set to Row.

    Usage::

        async with get_db_connection() as db:
            cursor = await db.execute("SELECT * FROM issues")
            rows = await cursor.fetchall()
    """
    if _shared_connection is None:
        # Fallback: open a one-off connection (e.g. in tests)
        settings = get_settings()
        db_path = str(Path(settings.database.path))
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("PRAGMA busy_timeout=5000")
            yield db
    else:
        yield _shared_connection
