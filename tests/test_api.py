"""Tests for the simplified Issue API."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from agent.db.repos import IssueRepo
from agent.agent.cc_connect_client import CCConnectBridgeError, ProjectInfo
from agent.models import IssueCreate, IssueOutcome, IssueStatus
from agent.server.app import create_app


@pytest.fixture()
async def api_client(initialized_db):
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        runtime = MagicMock()
        runtime.start_task = AsyncMock()
        runtime.cancel_task = AsyncMock(return_value=True)
        runtime.is_running = MagicMock(return_value=False)
        runtime.list_projects = AsyncMock(return_value=[])
        app.state.runtime = runtime
        yield client


@pytest.mark.asyncio
async def test_create_issue_persists_project(api_client):
    response = await api_client.post(
        "/api/issues", json={"content": "修复登录", "project": "api"}
    )

    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    assert response.json()["project"] == "api"


@pytest.mark.asyncio
async def test_issue_api_exposes_only_simplified_fields(api_client):
    response = await api_client.post(
        "/api/issues", json={"content": "修复登录", "project": "api"}
    )

    assert response.status_code == 201
    assert set(response.json()) == {
        "id", "content", "project", "status", "outcome", "result",
        "error_message", "created_at", "updated_at", "finished_at",
    }


@pytest.mark.asyncio
async def test_create_issue_requires_content_and_project(api_client):
    response = await api_client.post("/api/issues", json={"title": "legacy"})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_run_issue_starts_pending_issue(api_client):
    created = await api_client.post(
        "/api/issues", json={"content": "修复登录", "project": "api"}
    )
    issue_id = created.json()["id"]

    response = await api_client.post(f"/api/issues/{issue_id}/run")

    assert response.status_code == 202
    api_client._transport.app.state.runtime.start_task.assert_awaited_once_with(issue_id)


@pytest.mark.asyncio
async def test_list_projects_returns_bridge_projects(api_client):
    api_client._transport.app.state.runtime.list_projects = AsyncMock(
        return_value=[ProjectInfo(name="api")]
    )

    response = await api_client.get("/api/cc-connect/projects")

    assert response.status_code == 200
    assert response.json() == {"projects": [{"name": "api"}]}


@pytest.mark.asyncio
async def test_list_projects_returns_service_unavailable_when_bridge_is_offline(api_client):
    api_client._transport.app.state.runtime.list_projects = AsyncMock(
        side_effect=CCConnectBridgeError("offline")
    )

    response = await api_client.get("/api/cc-connect/projects")

    assert response.status_code == 503
    assert response.json()["detail"] == "offline"


@pytest.mark.asyncio
async def test_run_issue_rejects_finished_issue(api_client):
    issue = await IssueRepo().create(IssueCreate(content="x", project="api"))
    await IssueRepo().finish(issue.id, IssueOutcome.success, "done", None)

    response = await api_client.post(f"/api/issues/{issue.id}/run")

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_run_issue_translates_a_concurrent_claim_loss_to_conflict(api_client):
    created = await api_client.post(
        "/api/issues", json={"content": "修复登录", "project": "api"}
    )
    api_client._transport.app.state.runtime.start_task = AsyncMock(
        side_effect=ValueError("Issue is in status IssueStatus.running, cannot run")
    )

    response = await api_client.post(f"/api/issues/{created.json()['id']}/run")

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_finish_keeps_error_as_terminal_outcome(initialized_db):
    issue = await IssueRepo().create(IssueCreate(content="x", project="api"))
    await IssueRepo().finish(
        issue.id, IssueOutcome.error, None, "Bridge disconnected"
    )

    saved = await IssueRepo().get(issue.id)
    assert saved is not None
    assert (saved.status, saved.outcome) == (
        IssueStatus.finished,
        IssueOutcome.error,
    )
    assert saved.error_message == "Bridge disconnected"
    assert saved.finished_at is not None


@pytest.mark.asyncio
async def test_start_only_transitions_pending_issue_once(initialized_db):
    issue = await IssueRepo().create(IssueCreate(content="x", project="api"))

    assert await IssueRepo().start(issue.id) is True
    assert await IssueRepo().start(issue.id) is False

    saved = await IssueRepo().get(issue.id)
    assert saved is not None
    assert saved.status == IssueStatus.running


def test_retired_issue_routes_are_not_registered(api_client):
    paths = {
        route.path
        for route in api_client._transport.app.routes
        if hasattr(route, "path")
    }

    assert "/api/issues/{issue_id}/retry" not in paths
    assert "/api/issues/{issue_id}/complete" not in paths
    assert "/api/issues/{issue_id}/plan" not in paths
    assert "/api/issues/{issue_id}/spec" not in paths
    assert "/api/issues/{issue_id}/reject-spec" not in paths
