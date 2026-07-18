"""Shared test fixtures for Mango."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from agent.config import Settings, get_settings
from agent.db.connection import init_db
from agent.server.app import create_app

# Exclude fixture data directories from pytest collection
collect_ignore_glob = [str(Path(__file__).parent / "fixtures" / "**")]


@pytest.fixture()
def tmp_settings(tmp_path, monkeypatch):
    """Return a Settings instance with DB in a temporary directory."""
    settings = Settings(
        database={"path": str(tmp_path / "test.db")},
    )

    # Clear the lru_cache so get_settings() returns our test settings
    get_settings.cache_clear()
    monkeypatch.setattr("agent.config.get_settings", lambda: settings)
    monkeypatch.setattr("agent.db.connection.get_settings", lambda: settings)
    monkeypatch.setattr("agent.db.repos.get_db_connection", _make_get_db_connection(settings))
    monkeypatch.setattr("agent.server.routes.get_db_connection", _make_get_db_connection(settings))

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


@pytest.fixture()
async def mock_runtime(initialized_db, tmp_path, monkeypatch):
    """AgentRuntime backed by a temporary database and Bridge client mock."""
    from agent.agent.runtime import AgentRuntime
    from agent.config import get_settings as _get_settings

    settings = _get_settings()

    monkeypatch.setattr("agent.agent.runtime.get_settings", lambda: settings)

    runtime = AgentRuntime()

    yield tmp_path, runtime

    await runtime.client.close()
