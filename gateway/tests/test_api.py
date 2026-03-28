"""Tests for Gateway API endpoints."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

# Set test DB path before importing app
_test_db_dir = tempfile.mkdtemp()
os.environ["DATABASE__PATH"] = str(Path(_test_db_dir) / "test_api.db")

from mango_gateway.server.app import create_app
from mango_gateway.db.connection import init_db, close_shared_connection
from mango_gateway.service.runtime_client import RuntimeClient


@pytest.fixture
async def app():
    """Create a test app with mocked Runtime."""
    test_app = create_app()

    # Override lifespan manually for tests
    await init_db()

    mock_runtime = AsyncMock(spec=RuntimeClient)
    mock_runtime.health_check.return_value = True
    mock_runtime.create_issue.return_value = {
        "id": "api-test-issue",
        "title": "Test",
        "status": "open",
    }
    mock_runtime.run_issue.return_value = {"message": "Started", "issue_id": "api-test-issue"}
    mock_runtime.get_issue.return_value = {
        "id": "api-test-issue",
        "status": "running",
        "pr_url": None,
        "failure_reason": None,
    }
    mock_runtime.get_issue_executions.return_value = []

    from mango_gateway.config import get_settings
    from mango_gateway.service.gateway import GatewayService

    settings = get_settings()
    gateway = GatewayService(runtime_client=mock_runtime, settings=settings)
    test_app.state.gateway = gateway

    yield test_app

    await close_shared_connection()


@pytest.fixture
async def client(app):
    """Create an async HTTP test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestHealthEndpoint:
    async def test_health(self, client: AsyncClient):
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["runtime_ok"] is True


class TestSessionEndpoints:
    async def test_create_session(self, client: AsyncClient):
        resp = await client.post(
            "/api/gateway/sessions",
            json={"source": "cli", "source_id": "user-1"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["source"] == "cli"
        assert data["status"] == "active"
        return data["id"]

    async def test_get_session(self, client: AsyncClient):
        # Create first
        create_resp = await client.post(
            "/api/gateway/sessions", json={"source": "api"}
        )
        session_id = create_resp.json()["id"]

        # Get
        resp = await client.get(f"/api/gateway/sessions/{session_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == session_id

    async def test_get_nonexistent_session(self, client: AsyncClient):
        resp = await client.get("/api/gateway/sessions/nonexistent")
        assert resp.status_code == 404

    async def test_close_session(self, client: AsyncClient):
        create_resp = await client.post(
            "/api/gateway/sessions", json={"source": "api"}
        )
        session_id = create_resp.json()["id"]

        resp = await client.post(f"/api/gateway/sessions/{session_id}/close")
        assert resp.status_code == 200
        assert resp.json()["status"] == "closed"


class TestMessageEndpoint:
    async def test_send_message_creates_session_and_issue(self, client: AsyncClient):
        resp = await client.post(
            "/api/gateway/messages",
            json={"content": "帮我写代码", "workspace": "/tmp/repo"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] is not None
        assert data["issue_id"] == "api-test-issue"
        assert data["issue_status"] == "running"

    async def test_send_message_with_existing_session(self, client: AsyncClient):
        # Create session first
        create_resp = await client.post(
            "/api/gateway/sessions", json={"source": "api"}
        )
        session_id = create_resp.json()["id"]

        resp = await client.post(
            "/api/gateway/messages",
            json={"content": "帮我修 bug", "session_id": session_id},
        )
        assert resp.status_code == 200
        assert resp.json()["session_id"] == session_id

    async def test_send_message_invalid_session(self, client: AsyncClient):
        resp = await client.post(
            "/api/gateway/messages",
            json={"content": "test", "session_id": "nonexistent"},
        )
        assert resp.status_code == 404

    async def test_get_session_messages(self, client: AsyncClient):
        # Send a message to create session + messages
        send_resp = await client.post(
            "/api/gateway/messages",
            json={"content": "帮我写函数"},
        )
        session_id = send_resp.json()["session_id"]

        # Get messages
        resp = await client.get(f"/api/gateway/sessions/{session_id}/messages")
        assert resp.status_code == 200
        messages = resp.json()
        assert len(messages) == 2  # user + assistant
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "帮我写函数"
        assert messages[1]["role"] == "assistant"
