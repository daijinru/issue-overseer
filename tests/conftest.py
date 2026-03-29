"""Shared test fixtures for Mango."""

from __future__ import annotations

import subprocess
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
    """AgentRuntime with local git repo + local bare remote, mock opencode.

    Provides a real git repo with a bare remote so ``git push`` works locally
    without network access.  The opencode client is NOT mocked here — tests
    should attach their own mock to ``runtime.client.run_prompt``.

    Yields ``(repo_dir, runtime)`` tuple.
    """
    from agent.agent.runtime import AgentRuntime
    from agent.config import get_settings as _get_settings

    settings = _get_settings()

    # 1. Create local repo with initial commit
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo_dir, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Mango Test"],
        cwd=repo_dir, capture_output=True, check=True,
    )
    (repo_dir / "README.md").write_text("# Test repo")
    subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo_dir, capture_output=True, check=True,
    )

    # 2. Create bare remote and push main
    bare = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", str(bare)],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", str(bare)],
        cwd=repo_dir, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "push", "-u", "origin", "main"],
        cwd=repo_dir, capture_output=True, check=True,
    )

    # 3. Configure settings
    object.__setattr__(settings.project, "workspace", str(repo_dir))
    object.__setattr__(settings.project, "default_branch", "main")
    object.__setattr__(settings.project, "remote", "origin")
    object.__setattr__(settings.project, "pr_base", "main")
    object.__setattr__(settings.agent, "max_turns", 3)
    object.__setattr__(settings.agent, "task_timeout", 60)
    object.__setattr__(settings.opencode, "timeout", 30)

    monkeypatch.setattr("agent.agent.runtime.get_settings", lambda: settings)
    monkeypatch.setattr("agent.agent.context.get_settings", lambda: settings)
    monkeypatch.setattr("agent.skills.base.get_settings", lambda: settings)

    runtime = AgentRuntime()

    yield repo_dir, runtime

    await runtime.client.close()
