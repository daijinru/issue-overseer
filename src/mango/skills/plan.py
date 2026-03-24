"""PlanSkill — generates structured execution plans (Specs) without modifying code."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from abc import ABC
from collections.abc import Callable

from mango.agent.opencode_client import OpenCodeClient
from mango.agent.safety import build_safety_prompt
from mango.config import get_settings
from mango.models import TurnContext
from mango.skills.base import BaseSkill

logger = logging.getLogger(__name__)


def extract_spec_json(raw_output: str) -> dict | None:
    """Robustly extract Spec JSON from LLM output.

    Strategies (by priority):
    1. Direct json.loads (ideal case)
    2. Extract ```json ... ``` code block content
    3. Regex match the outermost { ... } block (handles nesting)
    4. All fail → return None
    """
    # Strategy 1: direct parse
    try:
        return json.loads(raw_output.strip())
    except (json.JSONDecodeError, ValueError):
        pass

    # Strategy 2: extract markdown code block
    code_block = re.search(r"```(?:json)?\s*\n(.*?)\n```", raw_output, re.DOTALL)
    if code_block:
        try:
            return json.loads(code_block.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            pass

    # Strategy 3: match outermost { ... } (handle nested braces)
    brace_match = re.search(r"\{", raw_output)
    if brace_match:
        start = brace_match.start()
        depth = 0
        for i in range(start, len(raw_output)):
            if raw_output[i] == "{":
                depth += 1
            elif raw_output[i] == "}":
                depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw_output[start : i + 1])
                except (json.JSONDecodeError, ValueError):
                    break

    return None


def validate_spec(data: dict) -> dict:
    """Validate and normalize Spec fields, accepting loosely.

    Handles both snake_case and camelCase field names.
    """
    return {
        "plan": data.get("plan", data.get("Plan", "")),
        "acceptance_criteria": data.get(
            "acceptance_criteria", data.get("acceptanceCriteria", [])
        ),
        "files_to_modify": data.get(
            "files_to_modify", data.get("filesToModify", [])
        ),
        "estimated_complexity": data.get(
            "estimated_complexity", data.get("complexity", "medium")
        ),
    }


class PlanSkill(BaseSkill):
    """Analyze codebase and generate a structured execution plan (Spec) without modifying code."""

    def __init__(self, client: OpenCodeClient) -> None:
        self.client = client

    async def execute(
        self,
        ctx: TurnContext,
        cwd: str,
        *,
        cancel_event: asyncio.Event | None = None,
        on_event: Callable[[dict], None] | None = None,
    ) -> str:
        prompt = self._build_plan_prompt(ctx)
        return await self.client.run_prompt(
            prompt, cwd=cwd, cancel_event=cancel_event, on_event=on_event
        )

    def _build_plan_prompt(self, ctx: TurnContext, *, strict: bool = False) -> str:
        """Build the prompt for Spec generation.

        Args:
            ctx: Turn context with issue info.
            strict: If True, add extra emphasis on JSON-only output (used for retry).
        """
        sections: list[str] = []

        sections.append(
            f"""## Task: Generate Execution Plan

**Issue**: {ctx.issue.title}
**Description**: {ctx.issue.description}

## Instructions
Analyze the codebase and generate a structured execution plan. Do NOT modify any files.

Output MUST be valid JSON (no markdown, no explanation text outside the JSON):
{{
  "plan": "Description of the approach...",
  "acceptance_criteria": ["Criterion 1", "Criterion 2"],
  "files_to_modify": ["path/to/file.py"],
  "estimated_complexity": "low | medium | high"
}}"""
        )

        if ctx.human_instruction:
            sections.append(
                f"## Additional Instructions from User\n{ctx.human_instruction}"
            )

        if strict:
            sections.append(
                "IMPORTANT: Output ONLY valid JSON, no markdown, no explanation. "
                "The entire response must be parseable by json.loads()."
            )

        return "\n\n".join(sections)

    def build_strict_prompt(self, ctx: TurnContext) -> str:
        """Build a stricter prompt for retry after JSON extraction failure."""
        return self._build_plan_prompt(ctx, strict=True)
