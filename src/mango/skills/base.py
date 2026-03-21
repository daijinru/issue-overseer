"""Base Skill — the ability unit of the Agent."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

from mango.agent.opencode_client import OpenCodeClient
from mango.agent.safety import build_safety_prompt
from mango.config import get_settings
from mango.models import TurnContext


class BaseSkill(ABC):
    @abstractmethod
    async def execute(self, ctx: TurnContext, cwd: str, *,
                      session_id: str, cancel_event: asyncio.Event | None = None) -> str:
        ...


class GenericSkill(BaseSkill):
    def __init__(self, client: OpenCodeClient) -> None:
        self.client = client

    async def execute(self, ctx: TurnContext, cwd: str, *,
                      session_id: str, cancel_event: asyncio.Event | None = None) -> str:
        prompt = self._build_prompt(ctx)
        return await self.client.send_prompt(session_id, prompt, cancel_event=cancel_event)

    def _build_prompt(self, ctx: TurnContext) -> str:
        settings = get_settings()
        safety = build_safety_prompt(settings.security)
        sections: list[str] = []
        sections.append(f"## Task\n**{ctx.issue.title}**\n{ctx.issue.description}")
        sections.append(safety)
        sections.append(f"## Progress\nThis is turn {ctx.turn_number} of {ctx.max_turns}.")
        if ctx.last_error:
            sections.append(f"## Previous Error\n```\n{ctx.last_error}\n```")
        if ctx.last_result:
            sections.append(f"## Previous Result\n{ctx.last_result}")
        if ctx.git_diff:
            sections.append(f"## Current Changes (git diff)\n```diff\n{ctx.git_diff}\n```")
        if ctx.execution_history:
            history_lines = []
            for h in ctx.execution_history:
                history_lines.append(f"- Turn {h.get('turn')}: {h.get('status')} — {h.get('summary', 'N/A')}")
            sections.append("## Execution History\n" + "\n".join(history_lines))
        if ctx.human_instruction:
            sections.append(f"## Additional Instructions from User\n{ctx.human_instruction}")
        return "\n\n".join(sections)
