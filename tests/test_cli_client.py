"""Tests for MangoClient — mock HTTP responses, verify error handling."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from mango.cli.client import MangoClient, _extract_detail


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def mock_transport():
    """Create a mock httpx transport for testing."""
    return httpx.MockTransport(lambda req: httpx.Response(200, json={}))


def _make_client(handler) -> MangoClient:
    """Create a MangoClient with a custom request handler."""
    transport = httpx.MockTransport(handler)
    client = MangoClient("http://test:18800")
    client._client = httpx.Client(transport=transport, base_url="http://test:18800")
    return client


# ── Health tests ────────────────────────────────────────────────────


class TestHealth:
    def test_health_success(self):
        def handler(request):
            return httpx.Response(200, json={"status": "ok", "version": "0.1.0"})

        client = _make_client(handler)
        result = client.health()
        assert result["status"] == "ok"
        assert result["version"] == "0.1.0"
        client.close()


# ── Issue CRUD tests ────────────────────────────────────────────────


class TestIssueCRUD:
    def test_create_issue(self):
        def handler(request):
            body = json.loads(request.content)
            assert body["title"] == "Fix bug"
            assert body["description"] == "test desc"
            return httpx.Response(201, json={"id": "abc123", "title": "Fix bug", "status": "open"})

        client = _make_client(handler)
        result = client.create_issue("Fix bug", description="test desc")
        assert result["id"] == "abc123"
        client.close()

    def test_create_issue_with_workspace_and_priority(self):
        def handler(request):
            body = json.loads(request.content)
            assert body["workspace"] == "/tmp/repo"
            assert body["priority"] == "high"
            return httpx.Response(201, json={"id": "abc123", "title": "Fix", "status": "open"})

        client = _make_client(handler)
        result = client.create_issue("Fix", workspace="/tmp/repo", priority="high")
        assert result["id"] == "abc123"
        client.close()

    def test_list_issues(self):
        def handler(request):
            return httpx.Response(200, json=[
                {"id": "1", "title": "A", "status": "open"},
                {"id": "2", "title": "B", "status": "done"},
            ])

        client = _make_client(handler)
        result = client.list_issues()
        assert len(result) == 2
        client.close()

    def test_list_issues_with_filters(self):
        def handler(request):
            assert "status=running" in str(request.url)
            return httpx.Response(200, json=[])

        client = _make_client(handler)
        client.list_issues(status="running")
        client.close()

    def test_get_issue(self):
        def handler(request):
            return httpx.Response(200, json={"id": "abc", "title": "Test", "status": "open"})

        client = _make_client(handler)
        result = client.get_issue("abc")
        assert result["title"] == "Test"
        client.close()

    def test_edit_issue(self):
        def handler(request):
            body = json.loads(request.content)
            assert body["title"] == "New title"
            return httpx.Response(200, json={"id": "abc", "title": "New title"})

        client = _make_client(handler)
        result = client.edit_issue("abc", title="New title")
        assert result["title"] == "New title"
        client.close()

    def test_delete_issue(self):
        def handler(request):
            assert request.method == "DELETE"
            return httpx.Response(204)

        client = _make_client(handler)
        client.delete_issue("abc")
        client.close()


# ── Issue action tests ──────────────────────────────────────────────


class TestIssueActions:
    def test_run_issue(self):
        def handler(request):
            assert request.method == "POST"
            assert "/run" in str(request.url)
            return httpx.Response(202, json={"message": "Task started"})

        client = _make_client(handler)
        result = client.run_issue("abc")
        assert result["message"] == "Task started"
        client.close()

    def test_cancel_issue(self):
        def handler(request):
            return httpx.Response(200, json={"message": "Cancel signal sent"})

        client = _make_client(handler)
        result = client.cancel_issue("abc")
        assert "Cancel" in result["message"]
        client.close()

    def test_retry_issue(self):
        def handler(request):
            body = json.loads(request.content)
            assert body.get("human_instruction") == "try harder"
            return httpx.Response(202, json={"message": "Retry started"})

        client = _make_client(handler)
        result = client.retry_issue("abc", instruction="try harder")
        assert result["message"] == "Retry started"
        client.close()

    def test_plan_issue(self):
        def handler(request):
            return httpx.Response(202, json={"message": "Plan generation started"})

        client = _make_client(handler)
        result = client.plan_issue("abc")
        assert "Plan" in result["message"]
        client.close()

    def test_complete_issue(self):
        def handler(request):
            return httpx.Response(200, json={"id": "abc", "status": "done"})

        client = _make_client(handler)
        result = client.complete_issue("abc")
        assert result["status"] == "done"
        client.close()


# ── Spec tests ──────────────────────────────────────────────────────


class TestSpec:
    def test_update_spec(self):
        def handler(request):
            body = json.loads(request.content)
            assert body["spec"] == "new spec content"
            return httpx.Response(200, json={"id": "abc", "spec": "new spec content"})

        client = _make_client(handler)
        result = client.update_spec("abc", "new spec content")
        assert result["spec"] == "new spec content"
        client.close()

    def test_reject_spec(self):
        def handler(request):
            return httpx.Response(200, json={"id": "abc", "status": "open", "spec": None})

        client = _make_client(handler)
        result = client.reject_spec("abc")
        assert result["status"] == "open"
        client.close()


# ── Logs and steps tests ────────────────────────────────────────────


class TestLogsAndSteps:
    def test_get_logs(self):
        def handler(request):
            return httpx.Response(200, json=[
                {"id": 1, "level": "info", "message": "started"},
            ])

        client = _make_client(handler)
        result = client.get_logs("abc")
        assert len(result) == 1
        assert result[0]["message"] == "started"
        client.close()

    def test_get_steps(self):
        def handler(request):
            return httpx.Response(200, json=[
                {"id": 1, "step_type": "tool_use", "tool": "read_file"},
            ])

        client = _make_client(handler)
        result = client.get_steps("abc")
        assert len(result) == 1
        client.close()


# ── Error handling tests ────────────────────────────────────────────


class TestErrorHandling:
    def test_404_exits(self):
        def handler(request):
            return httpx.Response(404, json={"detail": "Issue not found"})

        client = _make_client(handler)
        with pytest.raises(SystemExit):
            client.get_issue("nonexistent")
        client.close()

    def test_409_exits(self):
        def handler(request):
            return httpx.Response(409, json={"detail": "Issue is running, must be 'open' to run"})

        client = _make_client(handler)
        with pytest.raises(SystemExit):
            client.run_issue("abc")
        client.close()

    def test_422_exits(self):
        def handler(request):
            return httpx.Response(422, json={"detail": "No fields to update"})

        client = _make_client(handler)
        with pytest.raises(SystemExit):
            client.edit_issue("abc")
        client.close()

    def test_500_exits(self):
        def handler(request):
            return httpx.Response(500, text="Internal Server Error")

        client = _make_client(handler)
        with pytest.raises(SystemExit):
            client.health()
        client.close()

    def test_connection_error_exits(self):
        client = MangoClient("http://localhost:1")
        client._client = httpx.Client(
            base_url="http://localhost:1",
            transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("fail"))),
        )
        with pytest.raises(SystemExit):
            client.health()
        client.close()


# ── _extract_detail tests ───────────────────────────────────────────


class TestExtractDetail:
    def test_json_detail_string(self):
        resp = httpx.Response(400, json={"detail": "bad request"})
        assert _extract_detail(resp) == "bad request"

    def test_json_detail_list(self):
        resp = httpx.Response(422, json={"detail": [{"msg": "field required"}]})
        assert "field required" in _extract_detail(resp)

    def test_plain_text_fallback(self):
        resp = httpx.Response(500, text="server error")
        assert "server error" in _extract_detail(resp)

    def test_empty_body(self):
        resp = httpx.Response(500, text="")
        assert _extract_detail(resp) == ""
