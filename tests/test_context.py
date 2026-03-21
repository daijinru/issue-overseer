"""Tests for the TurnContext builder."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mango.agent.context import build_turn_context
from mango.models import Issue, IssueStatus


def _make_issue(**kwargs) -> Issue:
    defaults = dict(id="issue-1", title="Test Issue", description="desc", status=IssueStatus.open)
    defaults.update(kwargs)
    return Issue(**defaults)


@pytest.fixture(autouse=True)
def _mock_settings(monkeypatch):
    mock_settings = MagicMock()
    mock_settings.context.max_git_diff_lines = 10
    mock_settings.context.max_result_chars = 100
    monkeypatch.setattr("mango.agent.context.get_settings", lambda: mock_settings)


def test_build_turn_context_passthrough_no_truncation():
    issue = _make_issue()
    ctx = build_turn_context(issue=issue, turn_number=1, max_turns=3, git_diff="line1\nline2")
    assert ctx.issue == issue
    assert ctx.turn_number == 1
    assert ctx.max_turns == 3
    assert ctx.git_diff == "line1\nline2"


def test_git_diff_truncation_when_exceeds_limit():
    diff = "\n".join(f"line{i}" for i in range(20))
    ctx = build_turn_context(issue=_make_issue(), turn_number=1, max_turns=3, git_diff=diff)
    assert "[truncated: 10 more lines]" in ctx.git_diff


def test_git_diff_no_truncation_at_exact_limit():
    diff = "\n".join(f"line{i}" for i in range(10))
    ctx = build_turn_context(issue=_make_issue(), turn_number=1, max_turns=3, git_diff=diff)
    assert "[truncated" not in ctx.git_diff


def test_last_result_truncation_when_exceeds_limit():
    result = "x" * 200
    ctx = build_turn_context(issue=_make_issue(), turn_number=1, max_turns=3, last_result=result)
    assert ctx.last_result.endswith("[truncated]")
    assert len(ctx.last_result) < 200


def test_none_values_preserved():
    ctx = build_turn_context(issue=_make_issue(), turn_number=1, max_turns=3)
    assert ctx.last_result is None
    assert ctx.last_error is None
    assert ctx.git_diff is None
    assert ctx.human_instruction is None


def test_execution_history_defaults_to_empty_list():
    ctx = build_turn_context(issue=_make_issue(), turn_number=1, max_turns=3)
    assert ctx.execution_history == []


def test_truncation_message_includes_line_count():
    # 15 lines = 5 over the limit of 10
    diff = "\n".join(f"line{i}" for i in range(15))
    ctx = build_turn_context(issue=_make_issue(), turn_number=1, max_turns=3, git_diff=diff)
    assert "[truncated: 5 more lines]" in ctx.git_diff
