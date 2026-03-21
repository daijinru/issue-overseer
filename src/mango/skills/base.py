"""Base Skill — the ability unit of the Agent.

A Skill converts an Issue + TurnContext into a prompt and sends it
to OpenCode for execution. MVP uses this base class directly;
specific Skills (fix_test_failure, write_feature, etc.) extend it later.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from mango.models import TurnContext


class BaseSkill(ABC):
    """Abstract base class for all Skills.

    Subclasses implement ``execute()`` to:
    1. Build a prompt from the TurnContext
    2. Call OpenCode via the HTTP client
    3. Return the result text
    """

    @abstractmethod
    async def execute(self, ctx: TurnContext, cwd: str) -> str:
        """Execute this Skill against the given context.

        Args:
            ctx: The current turn's context (issue, history, diff, etc.)
            cwd: Working directory (the target repository root)

        Returns:
            The result text from OpenCode.
        """
        ...
