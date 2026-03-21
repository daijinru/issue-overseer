"""Tests for API routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from mango.db.repos import IssueRepo
from mango.models import IssueCreate, IssueStatus
from mango.server.app import create_app


@pytest.fixture()
async def api_client(initialized_db):
    """HTTP client with a mock AgentRuntime attached."""
    app = create_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Override the runtime created by lifespan with a mock
        mock_runtime = MagicMock()
        mock_runtime.start_task = AsyncMock()
        mock_runtime.cancel_task = AsyncMock(return_value=True)
        mock_runtime.is_running = MagicMock(return_value=False)
        app.state.runtime = mock_runtime
        yield ac


# ── CRUD tests ──


@pytest.mark.asyncio
async def test_create_issue(api_client):
    resp = await api_client.post("/api/issues", json={"title": "Test", "description": "desc"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Test"
    assert data["status"] == "open"


@pytest.mark.asyncio
async def test_list_issues(api_client):
    await api_client.post("/api/issues", json={"title": "A"})
    await api_client.post("/api/issues", json={"title": "B"})
    resp = await api_client.get("/api/issues")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 2


@pytest.mark.asyncio
async def test_list_issues_filter_by_status(api_client):
    await api_client.post("/api/issues", json={"title": "Open Issue"})
    resp = await api_client.get("/api/issues", params={"status": "open"})
    assert resp.status_code == 200
    data = resp.json()
    assert all(i["status"] == "open" for i in data)


@pytest.mark.asyncio
async def test_get_issue(api_client):
    create_resp = await api_client.post("/api/issues", json={"title": "Get me"})
    issue_id = create_resp.json()["id"]
    resp = await api_client.get(f"/api/issues/{issue_id}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Get me"


@pytest.mark.asyncio
async def test_get_issue_404(api_client):
    resp = await api_client.get("/api/issues/nonexistent-id")
    assert resp.status_code == 404


# ── Action tests ──


@pytest.mark.asyncio
async def test_run_issue_returns_202(api_client):
    create_resp = await api_client.post("/api/issues", json={"title": "Run me"})
    issue_id = create_resp.json()["id"]
    resp = await api_client.post(f"/api/issues/{issue_id}/run")
    assert resp.status_code == 202


@pytest.mark.asyncio
async def test_run_issue_already_running_returns_409(api_client):
    create_resp = await api_client.post("/api/issues", json={"title": "Running"})
    issue_id = create_resp.json()["id"]
    # Make runtime report it's running
    api_client._transport.app.state.runtime.is_running.return_value = True
    resp = await api_client.post(f"/api/issues/{issue_id}/run")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_run_issue_wrong_status_returns_409(api_client):
    create_resp = await api_client.post("/api/issues", json={"title": "Done issue"})
    issue_id = create_resp.json()["id"]
    # Set status to done
    repo = IssueRepo()
    await repo.update_status(issue_id, IssueStatus.done)
    resp = await api_client.post(f"/api/issues/{issue_id}/run")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_cancel_issue_not_running_returns_409(api_client):
    create_resp = await api_client.post("/api/issues", json={"title": "Cancel me"})
    issue_id = create_resp.json()["id"]
    api_client._transport.app.state.runtime.cancel_task = AsyncMock(return_value=False)
    resp = await api_client.post(f"/api/issues/{issue_id}/cancel")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_retry_issue_stores_instruction(api_client):
    create_resp = await api_client.post("/api/issues", json={"title": "Retry me"})
    issue_id = create_resp.json()["id"]
    # Set to waiting_human
    repo = IssueRepo()
    await repo.update_status(issue_id, IssueStatus.waiting_human)
    resp = await api_client.post(
        f"/api/issues/{issue_id}/retry",
        json={"human_instruction": "Try harder"},
    )
    assert resp.status_code == 202
    updated = await repo.get(issue_id)
    assert updated.human_instruction == "Try harder"


@pytest.mark.asyncio
async def test_retry_issue_wrong_status_returns_409(api_client):
    create_resp = await api_client.post("/api/issues", json={"title": "Retry bad"})
    issue_id = create_resp.json()["id"]
    # Status is 'open', not 'failed' or 'waiting_human'
    resp = await api_client.post(
        f"/api/issues/{issue_id}/retry",
        json={"human_instruction": "nope"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_get_issue_logs_empty(api_client):
    create_resp = await api_client.post("/api/issues", json={"title": "Logs"})
    issue_id = create_resp.json()["id"]
    resp = await api_client.get(f"/api/issues/{issue_id}/logs")
    assert resp.status_code == 200
    assert resp.json() == []
