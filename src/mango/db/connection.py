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


@asynccontextmanager
async def get_db_connection() -> AsyncIterator[aiosqlite.Connection]:
    """Yield an aiosqlite connection with row_factory set to Row.

    Usage::

        async with get_db_connection() as db:
            cursor = await db.execute("SELECT * FROM issues")
            rows = await cursor.fetchall()
    """
    settings = get_settings()
    db_path = str(Path(settings.database.path))

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys=ON")
        yield db
