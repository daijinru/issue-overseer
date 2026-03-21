"""OpenCode HTTP client — communicates with ``opencode serve`` API."""

from __future__ import annotations

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)


class OpenCodeClient:
    """HTTP client for the OpenCode serve-mode API."""

    def __init__(self, base_url: str, timeout: int = 300) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._http: httpx.AsyncClient | None = None

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout))
        return self._http

    async def close(self) -> None:
        if self._http and not self._http.is_closed:
            await self._http.aclose()

    async def create_session(self) -> str:
        http = await self._get_http()
        resp = await http.post(f"{self.base_url}/session")
        resp.raise_for_status()
        data = resp.json()
        session_id = data["id"]
        logger.info("OpenCode session created: %s", session_id)
        return session_id

    async def send_prompt(
        self,
        session_id: str,
        prompt: str,
        *,
        cancel_event: asyncio.Event | None = None,
    ) -> str:
        http = await self._get_http()
        if cancel_event and cancel_event.is_set():
            raise asyncio.CancelledError("Task cancelled before sending prompt")
        resp = await http.post(
            f"{self.base_url}/session/{session_id}/message",
            json={"parts": [{"type": "text", "text": prompt}]},
        )
        resp.raise_for_status()
        data = resp.json()
        parts = data.get("parts", [])
        result_text = "\n".join(
            p.get("text", "") for p in parts if p.get("type") == "text"
        )
        return result_text
