"""Tests for RuntimeClient HTTP client."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mango_gateway.service.runtime_client import RuntimeClient


@pytest.fixture
def runtime_client() -> RuntimeClient:
    return RuntimeClient(base_url="http://localhost:18800", timeout=5)


class TestRuntimeClientInit:
    def test_base_url_trailing_slash_stripped(self):
        client = RuntimeClient(base_url="http://localhost:18800/")
        assert client.base_url == "http://localhost:18800"

    def test_defaults(self):
        client = RuntimeClient(base_url="http://localhost:18800")
        assert client.timeout == 30


class TestRuntimeClientHealthCheck:
    async def test_health_check_success(self, runtime_client: RuntimeClient):
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.is_closed = False
        runtime_client._client = mock_client

        result = await runtime_client.health_check()
        assert result is True
        mock_client.get.assert_called_once_with("/api/health")

    async def test_health_check_failure(self, runtime_client: RuntimeClient):
        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("Connection refused")
        mock_client.is_closed = False
        runtime_client._client = mock_client

        result = await runtime_client.health_check()
        assert result is False


class TestRuntimeClientIssueOps:
    async def test_create_issue(self, runtime_client: RuntimeClient):
        mock_response = MagicMock()
        mock_response.json.return_value = {"id": "issue-123", "title": "Test", "status": "open"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.is_closed = False
        runtime_client._client = mock_client

        result = await runtime_client.create_issue(
            title="Test", description="Test desc", workspace="/tmp/repo"
        )

        assert result["id"] == "issue-123"
        mock_client.post.assert_called_once_with(
            "/api/issues",
            json={
                "title": "Test",
                "description": "Test desc",
                "priority": "medium",
                "workspace": "/tmp/repo",
            },
        )

    async def test_run_issue(self, runtime_client: RuntimeClient):
        mock_response = MagicMock()
        mock_response.json.return_value = {"message": "Task started", "issue_id": "issue-123"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.is_closed = False
        runtime_client._client = mock_client

        result = await runtime_client.run_issue("issue-123")
        assert result["issue_id"] == "issue-123"

    async def test_retry_issue(self, runtime_client: RuntimeClient):
        mock_response = MagicMock()
        mock_response.json.return_value = {"message": "Retry started"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.is_closed = False
        runtime_client._client = mock_client

        result = await runtime_client.retry_issue("issue-123", "Fix the import")
        mock_client.post.assert_called_once_with(
            "/api/issues/issue-123/retry",
            json={"human_instruction": "Fix the import"},
        )

    async def test_get_issue(self, runtime_client: RuntimeClient):
        mock_response = MagicMock()
        mock_response.json.return_value = {"id": "issue-123", "status": "running"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.is_closed = False
        runtime_client._client = mock_client

        result = await runtime_client.get_issue("issue-123")
        assert result["status"] == "running"


class TestRuntimeClientClose:
    async def test_close(self, runtime_client: RuntimeClient):
        mock_client = AsyncMock()
        mock_client.is_closed = False
        runtime_client._client = mock_client

        await runtime_client.close()
        mock_client.aclose.assert_called_once()

    async def test_close_when_no_client(self, runtime_client: RuntimeClient):
        # Should not raise
        await runtime_client.close()
