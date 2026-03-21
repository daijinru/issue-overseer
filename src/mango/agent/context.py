"""TurnContext builder — assembles per-turn context for the Agent Runtime."""

from __future__ import annotations

from mango.config import get_settings
from mango.models import Issue, TurnContext


def _truncate_by_lines(text: str | None, max_lines: int) -> str | None:
    if text is None:
        return None
    lines = text.split("\n")
    if len(lines) <= max_lines:
        return text
    remaining = len(lines) - max_lines
    return "\n".join(lines[:max_lines]) + f"\n[truncated: {remaining} more lines]"


def _truncate_by_chars(text: str | None, max_chars: int) -> str | None:
    if text is None:
        return None
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n[truncated]"


def build_turn_context(
    *,
    issue: Issue,
    turn_number: int,
    max_turns: int,
    last_result: str | None = None,
    last_error: str | None = None,
    git_diff: str | None = None,
    execution_history: list[dict] | None = None,
    human_instruction: str | None = None,
) -> TurnContext:
    ctx_cfg = get_settings().context
    truncated_diff = _truncate_by_lines(git_diff, ctx_cfg.max_git_diff_lines)
    truncated_result = _truncate_by_chars(last_result, ctx_cfg.max_result_chars)
    return TurnContext(
        issue=issue,
        turn_number=turn_number,
        max_turns=max_turns,
        last_result=truncated_result,
        last_error=last_error,
        git_diff=truncated_diff,
        execution_history=execution_history or [],
        human_instruction=human_instruction,
    )
