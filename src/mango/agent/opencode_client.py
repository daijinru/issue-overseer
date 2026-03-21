"""OpenCode HTTP client — communicates with ``opencode serve`` API.

Phase 1: Create sessions, send prompts, handle timeouts and cancellation.
"""

from __future__ import annotations


class OpenCodeClient:
    """HTTP client for the OpenCode serve-mode API.

    Usage (Phase 1)::

        client = OpenCodeClient(base_url="http://localhost:4096", timeout=300)
        session_id = await client.create_session()
        result = await client.send_prompt(session_id, prompt="Fix the login test")
    """

    def __init__(self, base_url: str, timeout: int = 300) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def create_session(self) -> str:
        """Create a new OpenCode session, return session ID."""
        raise NotImplementedError("Phase 1")

    async def send_prompt(self, session_id: str, prompt: str) -> str:
        """Send a prompt to an OpenCode session and return the result."""
        raise NotImplementedError("Phase 1")
