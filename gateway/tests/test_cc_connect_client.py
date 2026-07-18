"""Protocol tests for the cc-connect Bridge client."""

from __future__ import annotations

import json
from collections import deque

import pytest

from mango_gateway.service.cc_connect_client import (
    CCConnectBridgeClient,
    CCConnectBridgeError,
)


class FakeWebSocket:
    def __init__(self, incoming: list[dict]) -> None:
        self.incoming = deque(json.dumps(frame) for frame in incoming)
        self.sent: list[dict] = []

    async def send(self, payload: str) -> None:
        self.sent.append(json.loads(payload))

    async def recv(self) -> str:
        return self.incoming.popleft()


class FakeConnection:
    def __init__(self, socket: FakeWebSocket) -> None:
        self.socket = socket

    async def __aenter__(self) -> FakeWebSocket:
        return self.socket

    async def __aexit__(self, *_: object) -> None:
        return None


async def test_send_registers_then_returns_matching_reply() -> None:
    socket = FakeWebSocket(
        [
            {"type": "register_ack", "ok": True},
            {"type": "reply", "reply_ctx": "other", "content": "ignore"},
            {"type": "reply", "reply_ctx": "request-1", "content": "done"},
        ]
    )

    client = CCConnectBridgeClient(
        url="ws://cc-connect.test/bridge/ws",
        token="bridge-token",
        platform="issue-overseer",
        connect=lambda _url, **_kwargs: FakeConnection(socket),
        request_id_factory=lambda: "request-1",
    )

    assert await client.send("issue-overseer:session-1:user", "implement this") == "done"
    assert socket.sent == [
        {
            "type": "register",
            "platform": "issue-overseer",
            "capabilities": ["text"],
            "metadata": {"protocol_version": 1},
        },
        {
            "type": "message",
            "msg_id": "request-1",
            "session_key": "issue-overseer:session-1:user",
            "user_id": "session-1",
            "content": "implement this",
            "reply_ctx": "request-1",
        },
    ]


async def test_send_rejects_failed_registration() -> None:
    socket = FakeWebSocket([{"type": "register_ack", "ok": False, "error": "unknown platform"}])
    client = CCConnectBridgeClient(
        url="ws://cc-connect.test/bridge/ws",
        token="bridge-token",
        platform="issue-overseer",
        connect=lambda _url, **_kwargs: FakeConnection(socket),
    )

    with pytest.raises(CCConnectBridgeError, match="unknown platform"):
        await client.send("issue-overseer:session-1:user", "implement this")
