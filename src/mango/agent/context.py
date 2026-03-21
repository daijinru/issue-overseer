"""TurnContext builder — assembles per-turn context for the Agent Runtime.

Phase 1: Build TurnContext from Issue + execution history + git diff,
with truncation strategies for large diffs and results.
"""

from __future__ import annotations

from mango.models import Issue, TurnContext


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
    """Build a TurnContext with truncation applied.

    Phase 1: Implement truncation strategies:
    - git_diff > max_git_diff_lines → keep first N lines + ``[truncated]``
    - last_result > max_result_chars → summarize
    """
    raise NotImplementedError("Phase 1")
