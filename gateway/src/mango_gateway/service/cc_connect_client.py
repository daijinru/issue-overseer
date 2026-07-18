"""Minimal cc-connect Bridge Protocol client for Gateway task delivery."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable
from typing import Any

import websockets


class CCConnectBridgeError(RuntimeError):
    """Raised when cc-connect cannot accept or complete a Bridge request."""


class CCConnectBridgeClient:
    """Send one text task through a cc-connect Bridge adapter connection."""

    def __init__(
        self,
        url: str,
        token: str,
        platform: str,
        *,
        timeout: int = 1800,
        connect: Callable[..., Any] | None = None,
        request_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.url = url
        self.token = token
        self.platform = platform
        self.timeout = timeout
        self._connect = connect or websockets.connect
        self._request_id_factory = request_id_factory or (lambda: str(uuid.uuid4()))

    async def send(
        self, session_key: str, content: str, timeout: int | None = None
    ) -> str:
        """Deliver text to cc-connect and wait for its matching final reply."""
        request_id = self._request_id_factory()
        effective_timeout = self.timeout if timeout is None else timeout

        try:
            async with self._connect(
                self.url,
                additional_headers={"X-Bridge-Token": self.token},
            ) as socket:
                await self._register(socket)
                await socket.send(
                    json.dumps(
                        {
                            "type": "message",
                            "msg_id": request_id,
                            "session_key": session_key,
                            "user_id": _user_id_from_session_key(session_key),
                            "content": content,
                            "reply_ctx": request_id,
                        }
                    )
                )
                return await asyncio.wait_for(
                    self._wait_for_reply(socket, request_id),
                    timeout=effective_timeout,
                )
        except TimeoutError as exc:
            raise CCConnectBridgeError("cc-connect reply timed out") from exc
        except CCConnectBridgeError:
            raise
        except Exception as exc:
            raise CCConnectBridgeError(f"cc-connect Bridge error: {exc}") from exc

    async def _register(self, socket: Any) -> None:
        await socket.send(
            json.dumps(
                {
                    "type": "register",
                    "platform": self.platform,
                    "capabilities": ["text"],
                    "metadata": {"protocol_version": 1},
                }
            )
        )
        ack = _parse_frame(await socket.recv())
        if ack.get("type") != "register_ack" or not ack.get("ok"):
            raise CCConnectBridgeError(ack.get("error") or "cc-connect registration failed")

    async def _wait_for_reply(self, socket: Any, request_id: str) -> str:
        while True:
            frame = _parse_frame(await socket.recv())
            if frame.get("type") == "reply" and frame.get("reply_ctx") == request_id:
                content = frame.get("content")
                if not isinstance(content, str):
                    raise CCConnectBridgeError("cc-connect reply has no text content")
                return content
            if frame.get("type") == "error":
                raise CCConnectBridgeError(frame.get("message") or "cc-connect returned an error")


def _parse_frame(payload: str) -> dict[str, Any]:
    try:
        frame = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise CCConnectBridgeError("cc-connect returned invalid JSON") from exc
    if not isinstance(frame, dict):
        raise CCConnectBridgeError("cc-connect returned an invalid Bridge frame")
    return frame


def _user_id_from_session_key(session_key: str) -> str:
    parts = session_key.split(":")
    if len(parts) >= 2 and parts[1]:
        return parts[1]
    return session_key
