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

# ── Spec field length limits ─────────────────────────────────────────
_MAX_PLAN_CHARS = 2000
_MAX_CRITERION_CHARS = 200
_MAX_CRITERIA_COUNT = 20
_MAX_FILES_COUNT = 50
_MAX_SPEC_TOTAL_CHARS = 10000


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
    """Validate, normalize, and truncate Spec fields.

    Handles both snake_case and camelCase field names.
    Enforces per-field and total length limits to keep the spec
    within a reasonable token budget when injected into prompts.
    """
    plan = str(data.get("plan", data.get("Plan", "")))
    if len(plan) > _MAX_PLAN_CHARS:
        plan = plan[:_MAX_PLAN_CHARS] + "…[truncated]"

    raw_criteria = data.get(
        "acceptance_criteria", data.get("acceptanceCriteria", [])
    )
    if not isinstance(raw_criteria, list):
        raw_criteria = []
    criteria: list[str] = []
    for c in raw_criteria[:_MAX_CRITERIA_COUNT]:
        s = str(c)
        if len(s) > _MAX_CRITERION_CHARS:
            s = s[:_MAX_CRITERION_CHARS] + "…[truncated]"
        criteria.append(s)

    raw_files = data.get("files_to_modify", data.get("filesToModify", []))
    if not isinstance(raw_files, list):
        raw_files = []
    files: list[str] = [str(f) for f in raw_files[:_MAX_FILES_COUNT]]

    complexity = str(
        data.get("estimated_complexity", data.get("complexity", "medium"))
    )

    result = {
        "plan": plan,
        "acceptance_criteria": criteria,
        "files_to_modify": files,
        "estimated_complexity": complexity,
    }

    # Final guard: truncate the entire JSON representation
    serialized = json.dumps(result, ensure_ascii=False)
    if len(serialized) > _MAX_SPEC_TOTAL_CHARS:
        logger.warning(
            "Spec total size %d exceeds %d, truncating fields",
            len(serialized), _MAX_SPEC_TOTAL_CHARS,
        )
        # Progressively shrink: first criteria, then plan
        while len(serialized) > _MAX_SPEC_TOTAL_CHARS and len(result["acceptance_criteria"]) > 1:
            result["acceptance_criteria"].pop()
            serialized = json.dumps(result, ensure_ascii=False)
        if len(serialized) > _MAX_SPEC_TOTAL_CHARS:
            allowed = _MAX_SPEC_TOTAL_CHARS - (len(serialized) - len(result["plan"]))
            if allowed > 0:
                result["plan"] = result["plan"][:allowed] + "…[truncated]"
            else:
                result["plan"] = "…[truncated]"
            serialized = json.dumps(result, ensure_ascii=False)

    return result


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
