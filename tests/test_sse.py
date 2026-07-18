"""SSE endpoint tests for final Issue events."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from agent.server.app import create_app
from agent.server.event_bus import EventBus


@pytest.fixture()
async def sse_client(initialized_db):
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        app.state.event_bus = EventBus()
        runtime = MagicMock()
        runtime.start_task = AsyncMock()
        runtime.cancel_task = AsyncMock(return_value=True)
        runtime.is_running = MagicMock(return_value=False)
        app.state.runtime = runtime
        yield client, app.state.event_bus


@pytest.mark.asyncio
async def test_stream_returns_the_final_task_event(sse_client):
    client, event_bus = sse_client
    issue_id = (await client.post(
        "/api/issues", json={"content": "SSE Test", "project": "api"},
    )).json()["id"]

    async def publish_final_event():
        await asyncio.sleep(0.05)
        event_bus.publish(issue_id, "task_end", {"issue_id": issue_id, "success": True})

    asyncio.create_task(publish_final_event())
    response = await client.get(f"/api/issues/{issue_id}/stream")

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert "event: task_end" in response.text


@pytest.mark.asyncio
async def test_stream_returns_404_for_missing_issue(sse_client):
    client, _ = sse_client

    response = await client.get("/api/issues/nonexistent-id/stream")

    assert response.status_code == 404
