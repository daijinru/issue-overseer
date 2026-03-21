"""Shared test fixtures for Mango."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from mango.config import Settings, get_settings
from mango.db.connection import init_db
from mango.server.app import create_app


@pytest.fixture()
def tmp_settings(tmp_path, monkeypatch):
    """Return a Settings instance with DB in a temporary directory."""
    settings = Settings(
        database={"path": str(tmp_path / "test.db")},
    )

    # Clear the lru_cache so get_settings() returns our test settings
    get_settings.cache_clear()
    monkeypatch.setattr("mango.config.get_settings", lambda: settings)
    monkeypatch.setattr("mango.db.connection.get_settings", lambda: settings)
    monkeypatch.setattr("mango.server.routes.get_db_connection", _make_get_db_connection(settings))

    yield settings

    get_settings.cache_clear()


def _make_get_db_connection(settings: Settings):
    """Create a get_db_connection that uses the test settings."""
    from contextlib import asynccontextmanager
    from pathlib import Path

    import aiosqlite

    @asynccontextmanager
    async def get_db_connection():
        db_path = str(Path(settings.database.path))
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA foreign_keys=ON")
            yield db

    return get_db_connection


@pytest.fixture()
async def initialized_db(tmp_settings):
    """Ensure the test DB is initialized with all tables."""
    await init_db()
    return tmp_settings


@pytest.fixture()
async def client(initialized_db):
    """Async HTTP test client bound to the Mango FastAPI app."""
    app = create_app()

    # Manually run DB init since lifespan may not fire with ASGITransport
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
