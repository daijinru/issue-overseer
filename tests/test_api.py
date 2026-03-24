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
    # Status is 'open', not 'waiting_human'
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


# ── New Kanban endpoints tests ──


@pytest.mark.asyncio
async def test_create_issue_with_priority(api_client):
    resp = await api_client.post(
        "/api/issues", json={"title": "High priority", "priority": "high"}
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["priority"] == "high"


@pytest.mark.asyncio
async def test_create_issue_default_priority(api_client):
    resp = await api_client.post("/api/issues", json={"title": "Default"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["priority"] == "medium"


@pytest.mark.asyncio
async def test_complete_issue_review_to_done(api_client):
    create_resp = await api_client.post("/api/issues", json={"title": "Complete me"})
    issue_id = create_resp.json()["id"]
    repo = IssueRepo()
    await repo.update_status(issue_id, IssueStatus.review)
    resp = await api_client.post(f"/api/issues/{issue_id}/complete")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "done"


@pytest.mark.asyncio
async def test_complete_issue_wrong_status_returns_409(api_client):
    create_resp = await api_client.post("/api/issues", json={"title": "Not review"})
    issue_id = create_resp.json()["id"]
    # Status is 'open', not 'review'
    resp = await api_client.post(f"/api/issues/{issue_id}/complete")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_edit_issue_title_description_priority(api_client):
    create_resp = await api_client.post("/api/issues", json={"title": "Edit me"})
    issue_id = create_resp.json()["id"]
    resp = await api_client.patch(
        f"/api/issues/{issue_id}",
        json={"title": "Edited", "description": "New desc", "priority": "high"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Edited"
    assert data["description"] == "New desc"
    assert data["priority"] == "high"


@pytest.mark.asyncio
async def test_edit_issue_wrong_status_returns_409(api_client):
    create_resp = await api_client.post("/api/issues", json={"title": "Running"})
    issue_id = create_resp.json()["id"]
    repo = IssueRepo()
    await repo.update_status(issue_id, IssueStatus.running)
    resp = await api_client.patch(
        f"/api/issues/{issue_id}", json={"title": "Nope"}
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_edit_issue_no_fields_returns_422(api_client):
    create_resp = await api_client.post("/api/issues", json={"title": "No fields"})
    issue_id = create_resp.json()["id"]
    resp = await api_client.patch(f"/api/issues/{issue_id}", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_delete_issue_open(api_client):
    create_resp = await api_client.post("/api/issues", json={"title": "Delete me"})
    issue_id = create_resp.json()["id"]
    resp = await api_client.delete(f"/api/issues/{issue_id}")
    assert resp.status_code == 204
    # Verify it's gone
    resp = await api_client.get(f"/api/issues/{issue_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_issue_wrong_status_returns_409(api_client):
    create_resp = await api_client.post("/api/issues", json={"title": "Running"})
    issue_id = create_resp.json()["id"]
    repo = IssueRepo()
    await repo.update_status(issue_id, IssueStatus.running)
    resp = await api_client.delete(f"/api/issues/{issue_id}")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_run_issue_planned_status(api_client):
    """A planned issue should be runnable."""
    create_resp = await api_client.post("/api/issues", json={"title": "Planned"})
    issue_id = create_resp.json()["id"]
    repo = IssueRepo()
    await repo.update_status(issue_id, IssueStatus.planned)
    resp = await api_client.post(f"/api/issues/{issue_id}/run")
    assert resp.status_code == 202


@pytest.mark.asyncio
async def test_list_issues_filter_by_priority(api_client):
    await api_client.post("/api/issues", json={"title": "High", "priority": "high"})
    await api_client.post("/api/issues", json={"title": "Low", "priority": "low"})
    resp = await api_client.get("/api/issues", params={"priority": "high"})
    assert resp.status_code == 200
    data = resp.json()
    assert all(i["priority"] == "high" for i in data)


# ── Plan / Spec endpoint tests ──


@pytest.mark.asyncio
async def test_plan_issue_returns_202(api_client):
    """POST /plan on an open issue triggers spec generation."""
    create_resp = await api_client.post("/api/issues", json={"title": "Plan me"})
    issue_id = create_resp.json()["id"]
    mock_runtime = api_client._transport.app.state.runtime
    mock_runtime.start_plan = AsyncMock()
    resp = await api_client.post(f"/api/issues/{issue_id}/plan")
    assert resp.status_code == 202
    mock_runtime.start_plan.assert_awaited_once_with(issue_id)


@pytest.mark.asyncio
async def test_plan_issue_wrong_status_returns_409(api_client):
    """POST /plan on a non-open issue returns 409."""
    create_resp = await api_client.post("/api/issues", json={"title": "Running"})
    issue_id = create_resp.json()["id"]
    repo = IssueRepo()
    await repo.update_status(issue_id, IssueStatus.running)
    resp = await api_client.post(f"/api/issues/{issue_id}/plan")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_plan_issue_already_running_returns_409(api_client):
    """POST /plan while issue is actively running returns 409."""
    create_resp = await api_client.post("/api/issues", json={"title": "Busy"})
    issue_id = create_resp.json()["id"]
    api_client._transport.app.state.runtime.is_running.return_value = True
    api_client._transport.app.state.runtime.start_plan = AsyncMock()
    resp = await api_client.post(f"/api/issues/{issue_id}/plan")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_plan_issue_404(api_client):
    """POST /plan on non-existent issue returns 404."""
    resp = await api_client.post("/api/issues/nonexistent-id/plan")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_spec_planned_status(api_client):
    """PUT /spec updates spec content when issue is planned."""
    create_resp = await api_client.post("/api/issues", json={"title": "Spec edit"})
    issue_id = create_resp.json()["id"]
    repo = IssueRepo()
    await repo.update_status(issue_id, IssueStatus.planned)
    await repo.update_fields(issue_id, spec='{"plan": "old"}')

    new_spec = '{"plan": "updated plan", "acceptance_criteria": ["new criterion"]}'
    resp = await api_client.put(
        f"/api/issues/{issue_id}/spec", json={"spec": new_spec}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["spec"] == new_spec


@pytest.mark.asyncio
async def test_update_spec_wrong_status_returns_409(api_client):
    """PUT /spec on a non-planned issue returns 409."""
    create_resp = await api_client.post("/api/issues", json={"title": "Open"})
    issue_id = create_resp.json()["id"]
    # Status is 'open', not 'planned'
    resp = await api_client.put(
        f"/api/issues/{issue_id}/spec", json={"spec": '{"plan": "test"}'}
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_reject_spec_planned_to_open(api_client):
    """POST /reject-spec returns issue from planned → open and clears spec."""
    create_resp = await api_client.post("/api/issues", json={"title": "Reject"})
    issue_id = create_resp.json()["id"]
    repo = IssueRepo()
    await repo.update_status(issue_id, IssueStatus.planned)
    await repo.update_fields(issue_id, spec='{"plan": "rejected"}')

    resp = await api_client.post(f"/api/issues/{issue_id}/reject-spec")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "open"
    assert data["spec"] is None


@pytest.mark.asyncio
async def test_reject_spec_wrong_status_returns_409(api_client):
    """POST /reject-spec on a non-planned issue returns 409."""
    create_resp = await api_client.post("/api/issues", json={"title": "Open"})
    issue_id = create_resp.json()["id"]
    resp = await api_client.post(f"/api/issues/{issue_id}/reject-spec")
    assert resp.status_code == 409


# ── Extended status transition tests ──


@pytest.mark.asyncio
async def test_run_issue_cancelled_status(api_client):
    """A cancelled issue should be runnable."""
    create_resp = await api_client.post("/api/issues", json={"title": "Cancelled"})
    issue_id = create_resp.json()["id"]
    repo = IssueRepo()
    await repo.update_status(issue_id, IssueStatus.cancelled)
    resp = await api_client.post(f"/api/issues/{issue_id}/run")
    assert resp.status_code == 202


@pytest.mark.asyncio
async def test_run_issue_waiting_human_status(api_client):
    """A waiting_human issue should be runnable via /run (not just /retry)."""
    create_resp = await api_client.post("/api/issues", json={"title": "WH"})
    issue_id = create_resp.json()["id"]
    repo = IssueRepo()
    await repo.update_status(issue_id, IssueStatus.waiting_human)
    resp = await api_client.post(f"/api/issues/{issue_id}/run")
    assert resp.status_code == 202


@pytest.mark.asyncio
async def test_run_issue_review_status_returns_409(api_client):
    """An issue in review status should not be runnable."""
    create_resp = await api_client.post("/api/issues", json={"title": "Review"})
    issue_id = create_resp.json()["id"]
    repo = IssueRepo()
    await repo.update_status(issue_id, IssueStatus.review)
    resp = await api_client.post(f"/api/issues/{issue_id}/run")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_delete_issue_done_status(api_client):
    """An issue in done status should be deletable."""
    create_resp = await api_client.post("/api/issues", json={"title": "Done del"})
    issue_id = create_resp.json()["id"]
    repo = IssueRepo()
    await repo.update_status(issue_id, IssueStatus.done)
    resp = await api_client.delete(f"/api/issues/{issue_id}")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_issue_waiting_human(api_client):
    """An issue in waiting_human status should be deletable."""
    create_resp = await api_client.post("/api/issues", json={"title": "WH del"})
    issue_id = create_resp.json()["id"]
    repo = IssueRepo()
    await repo.update_status(issue_id, IssueStatus.waiting_human)
    resp = await api_client.delete(f"/api/issues/{issue_id}")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_issue_cancelled(api_client):
    """An issue in cancelled status should be deletable."""
    create_resp = await api_client.post("/api/issues", json={"title": "C del"})
    issue_id = create_resp.json()["id"]
    repo = IssueRepo()
    await repo.update_status(issue_id, IssueStatus.cancelled)
    resp = await api_client.delete(f"/api/issues/{issue_id}")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_issue_planning_returns_409(api_client):
    """An issue in planning status should NOT be deletable."""
    create_resp = await api_client.post("/api/issues", json={"title": "Planning"})
    issue_id = create_resp.json()["id"]
    repo = IssueRepo()
    await repo.update_status(issue_id, IssueStatus.planning)
    resp = await api_client.delete(f"/api/issues/{issue_id}")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_edit_issue_planned_status_allowed(api_client):
    """An issue in planned status should be editable."""
    create_resp = await api_client.post("/api/issues", json={"title": "Planned edit"})
    issue_id = create_resp.json()["id"]
    repo = IssueRepo()
    await repo.update_status(issue_id, IssueStatus.planned)
    resp = await api_client.patch(
        f"/api/issues/{issue_id}", json={"title": "Edited planned"}
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Edited planned"


@pytest.mark.asyncio
async def test_issue_response_includes_spec_field(api_client):
    """GET /issues/:id returns spec field in the response."""
    create_resp = await api_client.post("/api/issues", json={"title": "Spec test"})
    issue_id = create_resp.json()["id"]
    data = create_resp.json()
    assert "spec" in data
    assert data["spec"] is None  # initially None

    # Set spec
    repo = IssueRepo()
    await repo.update_status(issue_id, IssueStatus.planned)
    spec_content = '{"plan": "test plan"}'
    await repo.update_fields(issue_id, spec=spec_content)

    resp = await api_client.get(f"/api/issues/{issue_id}")
    assert resp.status_code == 200
    assert resp.json()["spec"] == spec_content


@pytest.mark.asyncio
async def test_issue_response_includes_priority_field(api_client):
    """GET /issues/:id returns priority field in the response."""
    resp = await api_client.post(
        "/api/issues", json={"title": "Prio test", "priority": "low"}
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["priority"] == "low"


@pytest.mark.asyncio
async def test_get_issue_executions(api_client):
    """GET /issues/:id/executions returns execution list."""
    create_resp = await api_client.post("/api/issues", json={"title": "Exec list"})
    issue_id = create_resp.json()["id"]
    resp = await api_client.get(f"/api/issues/{issue_id}/executions")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_issue_steps(api_client):
    """GET /issues/:id/steps returns steps list."""
    create_resp = await api_client.post("/api/issues", json={"title": "Steps list"})
    issue_id = create_resp.json()["id"]
    resp = await api_client.get(f"/api/issues/{issue_id}/steps")
    assert resp.status_code == 200
    assert resp.json() == []
