"""Protocol tests for the cc-connect Bridge client."""

from __future__ import annotations

import asyncio
import json
from collections import deque

import pytest

from agent.agent.cc_connect_client import CCConnectBridgeError, CCConnectClient


class FakeSocket:
    def __init__(self, incoming: list[dict]) -> None:
        self.incoming = deque(json.dumps(frame) for frame in incoming)
        self.sent: list[dict] = []
        self.connect_headers: dict[str, str] | None = None

    async def __aenter__(self) -> FakeSocket:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def send(self, payload: str) -> None:
        self.sent.append(json.loads(payload))

    async def recv(self) -> str:
        return self.incoming.popleft()


class UnrelatedReplySocket(FakeSocket):
    async def recv(self) -> str:
        if self.incoming:
            return await super().recv()
        await asyncio.sleep(0.005)
        return json.dumps({"type": "reply", "reply_ctx": "other", "content": "ignore"})


def bridge_client_replying(reply: str, request_id: str, monkeypatch: pytest.MonkeyPatch) -> tuple[CCConnectClient, FakeSocket]:
    socket = FakeSocket([
        {"type": "register_ack", "ok": True},
        {"type": "reply", "reply_ctx": "other", "content": "ignore"},
        {"type": "reply", "reply_ctx": request_id, "content": reply},
    ])
    monkeypatch.setattr("agent.agent.cc_connect_client.uuid.uuid4", lambda: request_id)
    client = CCConnectClient(
        url="ws://bridge",
        token="",
        platform="issue-overseer",
        connect=lambda _url, **kwargs: _connect(socket, **kwargs),
    )
    return client, socket


def _connect(socket: FakeSocket, **kwargs: object) -> FakeSocket:
    socket.connect_headers = kwargs.get("additional_headers")  # type: ignore[assignment]
    return socket


@pytest.mark.asyncio
async def test_list_projects_reads_capabilities_snapshot() -> None:
    socket = FakeSocket([
        {"type": "register_ack", "ok": True},
        {"type": "capabilities_snapshot", "projects": [{"project": "api"}]},
    ])
    client = CCConnectClient(
        url="ws://bridge",
        token="",
        platform="issue-overseer",
        connect=lambda _url, **kwargs: _connect(socket, **kwargs),
    )

    assert [project.name for project in await client.list_projects()] == ["api"]
    assert socket.connect_headers is None
    assert socket.sent[0]["metadata"] == {
        "control_plane": ["capabilities_snapshot_v1"],
    }


@pytest.mark.asyncio
async def test_run_task_sends_project_and_stable_issue_session(monkeypatch: pytest.MonkeyPatch) -> None:
    client, socket = bridge_client_replying("done", request_id="r1", monkeypatch=monkeypatch)

    assert await client.run_task("api", "fix login", "issue-1") == "done"
    assert socket.sent[1]["project"] == "api"
    assert socket.sent[1]["session_key"] == "issue-overseer:issue-1:issue"


@pytest.mark.asyncio
async def test_run_task_surfaces_error_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    socket = FakeSocket([
        {"type": "register_ack", "ok": True},
        {"type": "error", "message": "project unavailable"},
    ])
    monkeypatch.setattr("agent.agent.cc_connect_client.uuid.uuid4", lambda: "r1")
    client = CCConnectClient(
        url="ws://bridge", token="", platform="issue-overseer",
        connect=lambda _url, **kwargs: _connect(socket, **kwargs),
    )

    with pytest.raises(CCConnectBridgeError, match="project unavailable"):
        await client.run_task("api", "fix login", "issue-1")


@pytest.mark.asyncio
async def test_list_projects_surfaces_malformed_frame() -> None:
    socket = FakeSocket([{"type": "register_ack", "ok": True}])
    socket.incoming.append("not-json")
    client = CCConnectClient(
        url="ws://bridge", token="", platform="issue-overseer",
        connect=lambda _url, **kwargs: _connect(socket, **kwargs),
    )

    with pytest.raises(CCConnectBridgeError, match="invalid JSON"):
        await client.list_projects()


@pytest.mark.asyncio
async def test_run_task_surfaces_close_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    socket = FakeSocket([
        {"type": "register_ack", "ok": True},
        {"type": "close", "reason": "server shutdown"},
    ])
    monkeypatch.setattr("agent.agent.cc_connect_client.uuid.uuid4", lambda: "r1")
    client = CCConnectClient(
        url="ws://bridge", token="", platform="issue-overseer",
        connect=lambda _url, **kwargs: _connect(socket, **kwargs),
    )

    with pytest.raises(CCConnectBridgeError, match="server shutdown"):
        await client.run_task("api", "fix login", "issue-1")


@pytest.mark.asyncio
async def test_run_task_uses_one_deadline_for_unrelated_replies(monkeypatch: pytest.MonkeyPatch) -> None:
    socket = UnrelatedReplySocket([{"type": "register_ack", "ok": True}])
    monkeypatch.setattr("agent.agent.cc_connect_client.uuid.uuid4", lambda: "r1")
    client = CCConnectClient(
        url="ws://bridge", token="", platform="issue-overseer", timeout=0.02,
        connect=lambda _url, **kwargs: _connect(socket, **kwargs),
    )

    with pytest.raises(CCConnectBridgeError, match="timed out"):
        await asyncio.wait_for(client.run_task("api", "fix login", "issue-1"), timeout=0.1)
