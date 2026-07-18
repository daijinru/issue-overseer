"""Tests for the simplified Mango CLI client."""

from __future__ import annotations

import json

import httpx

from agent.cli.client import MangoClient


def _make_client(handler) -> MangoClient:
    client = MangoClient("http://test:18800")
    client._client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="http://test:18800"
    )
    return client


def test_create_issue_sends_only_content_and_project():
    def handler(request):
        assert request.url.path == "/api/issues"
        assert json.loads(request.content) == {"content": "fix login", "project": "api"}
        return httpx.Response(201, json={"id": "abc", "content": "fix login", "project": "api", "status": "pending"})

    client = _make_client(handler)
    assert client.create_issue("fix login", "api")["project"] == "api"
    client.close()


def test_list_issues_filters_only_by_status():
    def handler(request):
        assert dict(request.url.params) == {"status": "pending"}
        return httpx.Response(200, json=[])

    client = _make_client(handler)
    assert client.list_issues(status="pending") == []
    client.close()
