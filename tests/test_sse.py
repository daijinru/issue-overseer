"""Tests for SSE streaming endpoint and integration with EventBus."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from agent.db.repos import IssueRepo
from agent.models import IssueCreate, IssueStatus
from agent.server.app import create_app
from agent.server.event_bus import EventBus


@pytest.fixture()
async def sse_client(initialized_db):
    """HTTP client with an EventBus on app.state and a mock runtime."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Set up a real EventBus (the lifespan may not fire under ASGITransport)
        event_bus = EventBus()
        app.state.event_bus = event_bus

        mock_runtime = MagicMock()
        mock_runtime.start_task = AsyncMock()
        mock_runtime.cancel_task = AsyncMock(return_value=True)
        mock_runtime.is_running = MagicMock(return_value=False)
        app.state.runtime = mock_runtime

        yield ac, event_bus


@pytest.mark.asyncio
async def test_stream_endpoint_returns_event_stream(sse_client):
    """GET /api/issues/{id}/stream should return text/event-stream content type."""
    client, event_bus = sse_client
    # Create an issue first
    resp = await client.post("/api/issues", json={"title": "SSE Test"})
    issue_id = resp.json()["id"]

    # Publish a terminal event so the stream closes quickly
    async def _publish_after_delay():
        await asyncio.sleep(0.05)
        event_bus.publish(issue_id, "task_end", {"issue_id": issue_id, "success": True})

    asyncio.create_task(_publish_after_delay())

    resp = await client.get(f"/api/issues/{issue_id}/stream")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_stream_receives_published_events(sse_client):
    """SSE stream should contain events published via EventBus."""
    client, event_bus = sse_client
    resp = await client.post("/api/issues", json={"title": "SSE Events"})
    issue_id = resp.json()["id"]

    async def _publish_events():
        await asyncio.sleep(0.05)
        event_bus.publish(issue_id, "turn_start", {"turn_number": 1, "max_turns": 3})
        await asyncio.sleep(0.02)
        event_bus.publish(issue_id, "turn_end", {"turn_number": 1, "success": True})
        await asyncio.sleep(0.02)
        event_bus.publish(issue_id, "task_end", {"issue_id": issue_id, "success": True})

    asyncio.create_task(_publish_events())

    resp = await client.get(f"/api/issues/{issue_id}/stream")
    body = resp.text

    assert "event: turn_start" in body
    assert "event: turn_end" in body
    assert "event: task_end" in body
    assert '"turn_number": 1' in body


@pytest.mark.asyncio
async def test_stream_404_for_missing_issue(sse_client):
    """SSE endpoint should return 404 for a non-existent issue."""
    client, _ = sse_client
    resp = await client.get("/api/issues/nonexistent-id/stream")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_stream_cleans_up_subscriber(sse_client):
    """After the stream closes, the EventBus should have no lingering subscribers."""
    client, event_bus = sse_client
    resp = await client.post("/api/issues", json={"title": "Cleanup Test"})
    issue_id = resp.json()["id"]

    assert event_bus.subscriber_count(issue_id) == 0

    async def _publish_terminal():
        await asyncio.sleep(0.05)
        event_bus.publish(issue_id, "task_end", {"issue_id": issue_id, "success": True})

    asyncio.create_task(_publish_terminal())

    await client.get(f"/api/issues/{issue_id}/stream")

    # After stream closes, subscriber should have been cleaned up
    assert event_bus.subscriber_count(issue_id) == 0


@pytest.mark.asyncio
async def test_stream_receives_opencode_step_events(sse_client):
    """SSE stream should contain opencode_step events published via EventBus."""
    client, event_bus = sse_client
    resp = await client.post("/api/issues", json={"title": "Step Events"})
    issue_id = resp.json()["id"]

    async def _publish_events():
        await asyncio.sleep(0.05)
        event_bus.publish(issue_id, "opencode_step", {
            "step_type": "tool_use", "tool": "read", "target": "main.py",
        })
        await asyncio.sleep(0.02)
        event_bus.publish(issue_id, "opencode_step", {
            "step_type": "text", "summary": "Analyzing the code...",
        })
        await asyncio.sleep(0.02)
        event_bus.publish(issue_id, "task_end", {"issue_id": issue_id, "success": True})

    asyncio.create_task(_publish_events())

    resp = await client.get(f"/api/issues/{issue_id}/stream")
    body = resp.text

    assert "event: opencode_step" in body
    assert '"tool": "read"' in body
    assert '"target": "main.py"' in body
    assert "Analyzing the code" in body
    assert "event: task_end" in body
