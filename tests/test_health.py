"""Tests for the /api/health endpoint."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_health_returns_200(client):
    """GET /api/health should return HTTP 200."""
    response = await client.get("/api/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_health_response_body(client):
    """GET /api/health should return status=ok and version."""
    response = await client.get("/api/health")
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.1.0"
