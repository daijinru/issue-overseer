"""HTTP client for communicating with Agent Runtime REST API."""

from __future__ import annotations

import json
import logging
from typing import AsyncIterator

import httpx

logger = logging.getLogger(__name__)


class RuntimeClient:
    """HTTP client wrapping calls to the Agent Runtime REST API.

    The Gateway never imports Runtime code directly — all communication
    happens via HTTP, making it safe for distributed deployments.
    """

    def __init__(self, base_url: str, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout),
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ── Issue operations (mapping to Runtime's existing endpoints) ────

    async def create_issue(
        self,
        title: str,
        description: str = "",
        workspace: str | None = None,
        priority: str = "medium",
    ) -> dict:
        """POST /api/issues — Create a new issue on the Runtime."""
        client = await self._get_client()
        payload: dict = {
            "title": title,
            "description": description,
            "priority": priority,
        }
        if workspace:
            payload["workspace"] = workspace
        resp = await client.post("/api/issues", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def run_issue(self, issue_id: str) -> dict:
        """POST /api/issues/{id}/run — Start agent execution."""
        client = await self._get_client()
        resp = await client.post(f"/api/issues/{issue_id}/run")
        resp.raise_for_status()
        return resp.json()

    async def retry_issue(self, issue_id: str, human_instruction: str) -> dict:
        """POST /api/issues/{id}/retry — Retry with human instruction."""
        client = await self._get_client()
        resp = await client.post(
            f"/api/issues/{issue_id}/retry",
            json={"human_instruction": human_instruction},
        )
        resp.raise_for_status()
        return resp.json()

    async def get_issue(self, issue_id: str) -> dict:
        """GET /api/issues/{id} — Get issue details."""
        client = await self._get_client()
        resp = await client.get(f"/api/issues/{issue_id}")
        resp.raise_for_status()
        return resp.json()

    async def cancel_issue(self, issue_id: str) -> dict:
        """POST /api/issues/{id}/cancel — Cancel a running task."""
        client = await self._get_client()
        resp = await client.post(f"/api/issues/{issue_id}/cancel")
        resp.raise_for_status()
        return resp.json()

    async def get_issue_executions(self, issue_id: str) -> list[dict]:
        """GET /api/issues/{id}/executions — Get execution records."""
        client = await self._get_client()
        resp = await client.get(f"/api/issues/{issue_id}/executions")
        resp.raise_for_status()
        return resp.json()

    # ── SSE stream consumption ───────────────────────────────────────

    async def stream_issue_events(self, issue_id: str) -> AsyncIterator[dict]:
        """Consume the Runtime's SSE stream for an issue.

        GET /api/issues/{id}/stream

        Yields parsed event dicts. Used by GatewayService._wait_for_result()
        to block until a terminal event (task_end / task_cancelled).
        """
        client = await self._get_client()
        # Use a long timeout for SSE streaming — tasks can run for minutes
        stream_timeout = httpx.Timeout(
            connect=self.timeout,
            read=None,  # No read timeout for SSE
            write=self.timeout,
            pool=self.timeout,
        )
        async with client.stream(
            "GET",
            f"/api/issues/{issue_id}/stream",
            timeout=stream_timeout,
        ) as resp:
            resp.raise_for_status()
            current_event_type: str | None = None
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line:
                    # Empty line = end of SSE event
                    current_event_type = None
                    continue
                if line.startswith(":"):
                    # SSE comment (heartbeat)
                    continue
                if line.startswith("event: "):
                    current_event_type = line[7:]
                elif line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                        if current_event_type:
                            data["type"] = current_event_type
                        yield data
                    except json.JSONDecodeError:
                        logger.warning("Failed to parse SSE data: %s", line)

    # ── Health check ─────────────────────────────────────────────────

    async def health_check(self) -> bool:
        """GET /api/health — Check if the Runtime is reachable."""
        try:
            client = await self._get_client()
            resp = await client.get("/api/health")
            return resp.status_code == 200
        except Exception:
            return False
