"""cc-connect Bridge client used by the WisCode Issue runtime."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import websockets


class CCConnectBridgeError(RuntimeError):
    """Raised when cc-connect rejects or cannot complete a request."""


@dataclass(frozen=True)
class ProjectInfo:
    """A project advertised by cc-connect Bridge."""

    name: str


class CCConnectClient:
    """Expose the existing skill client interface through cc-connect Bridge."""

    def __init__(
        self,
        *,
        url: str,
        token: str,
        platform: str,
        timeout: int = 1800,
        connect: Callable[..., Any] | None = None,
    ) -> None:
        self.url = url
        self.token = token
        self.platform = platform
        self.timeout = timeout
        self._connect = connect or websockets.connect

    def _headers(self) -> dict[str, str] | None:
        return {"X-Bridge-Token": self.token} if self.token else None

    async def list_projects(self) -> list[ProjectInfo]:
        """Return the projects advertised in Bridge's capabilities snapshot."""
        try:
            async with self._connect(self.url, additional_headers=self._headers()) as socket:
                await self._register(socket)
                snapshot = await self._recv_frame(socket)
                if snapshot.get("type") == "error":
                    raise CCConnectBridgeError(snapshot.get("message") or "cc-connect returned an error")
                if snapshot.get("type") != "capabilities_snapshot":
                    raise CCConnectBridgeError("cc-connect did not return a capabilities snapshot")

                projects = snapshot.get("projects")
                if not isinstance(projects, list):
                    raise CCConnectBridgeError("cc-connect capabilities snapshot has invalid projects")

                result: list[ProjectInfo] = []
                for project in projects:
                    if not isinstance(project, dict) or not isinstance(project.get("project"), str):
                        raise CCConnectBridgeError("cc-connect capabilities snapshot has an invalid project")
                    result.append(ProjectInfo(name=project["project"]))
                return result
        except CCConnectBridgeError:
            raise
        except Exception as exc:
            raise CCConnectBridgeError(f"cc-connect Bridge error: {exc}") from exc

    async def run_task(self, project: str, content: str, issue_id: str) -> str:
        """Submit an issue to one explicit cc-connect project."""
        request_id = str(uuid.uuid4())
        try:
            async with self._connect(self.url, additional_headers=self._headers()) as socket:
                await self._register(socket)
                await socket.send(json.dumps({
                    "type": "message",
                    "msg_id": request_id,
                    "project": project,
                    "session_key": f"{self.platform}:{issue_id}:issue",
                    "user_id": "issue-overseer",
                    "content": content,
                    "reply_ctx": request_id,
                }))
                return await self._wait_for_reply(socket, request_id, None)
        except CCConnectBridgeError:
            raise
        except Exception as exc:
            raise CCConnectBridgeError(f"cc-connect Bridge error: {exc}") from exc

    async def run_prompt(
        self,
        prompt: str,
        *,
        cwd: str = ".",
        cancel_event: asyncio.Event | None = None,
        on_event: Callable[[dict], None] | None = None,
    ) -> str:
        if cancel_event and cancel_event.is_set():
            raise asyncio.CancelledError("Task cancelled before cc-connect execution")
        request_id = str(uuid.uuid4())
        session_key = f"{self.platform}:{request_id}:issue"
        task_content = (
            f"{prompt}\n\n## Selected Issue Workspace\n"
            f"Work only in this directory: {cwd}"
        )
        if on_event is not None:
            on_event({"step_type": "thinking", "summary": "已提交给 cc-connect / WisCode"})

        try:
            async with self._connect(
                self.url,
                additional_headers=self._headers(),
            ) as socket:
                await self._register(socket)

                await socket.send(json.dumps({
                    "type": "message",
                    "msg_id": request_id,
                    "session_key": session_key,
                    "user_id": "issue-overseer",
                    "content": task_content,
                    "reply_ctx": request_id,
                }))
                return await self._wait_for_reply(socket, request_id, cancel_event)
        except CCConnectBridgeError:
            raise
        except Exception as exc:
            raise CCConnectBridgeError(f"cc-connect Bridge error: {exc}") from exc

    async def _wait_for_reply(self, socket: Any, request_id: str, cancel_event: asyncio.Event | None) -> str:
        while True:
            if cancel_event and cancel_event.is_set():
                raise asyncio.CancelledError("Task cancelled during cc-connect execution")
            frame = await self._recv_frame(socket)
            if frame.get("type") == "reply" and frame.get("reply_ctx") == request_id:
                content = frame.get("content")
                if isinstance(content, str):
                    return content
                raise CCConnectBridgeError("cc-connect reply has no text content")
            if frame.get("type") == "error":
                raise CCConnectBridgeError(frame.get("message") or "cc-connect returned an error")
            if frame.get("type") == "close":
                raise CCConnectBridgeError(frame.get("reason") or "cc-connect Bridge connection closed")

    async def _register(self, socket: Any) -> None:
        await socket.send(json.dumps({
            "type": "register",
            "platform": self.platform,
            "capabilities": ["text"],
            "metadata": {"protocol_version": 1},
        }))
        ack = await self._recv_frame(socket)
        if ack.get("type") == "error":
            raise CCConnectBridgeError(ack.get("message") or "cc-connect returned an error")
        if ack.get("type") != "register_ack" or not ack.get("ok"):
            raise CCConnectBridgeError(ack.get("error") or "cc-connect registration failed")

    async def _recv_frame(self, socket: Any) -> dict[str, Any]:
        try:
            payload = await asyncio.wait_for(socket.recv(), timeout=self.timeout)
        except asyncio.TimeoutError as exc:
            raise CCConnectBridgeError("cc-connect Bridge request timed out") from exc
        return self._parse_frame(payload)

    @staticmethod
    def _parse_frame(payload: str) -> dict[str, Any]:
        try:
            frame = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise CCConnectBridgeError("cc-connect returned invalid JSON") from exc
        if not isinstance(frame, dict):
            raise CCConnectBridgeError("cc-connect returned an invalid Bridge frame")
        return frame

    async def close(self) -> None:
        """Compatibility hook; each request owns and closes its socket."""
