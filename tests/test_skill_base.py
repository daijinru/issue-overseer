"""Tests for prompts built from simplified Issues."""

from __future__ import annotations

from unittest.mock import MagicMock

from agent.models import Issue, TurnContext
from agent.skills.base import GenericSkill


def test_generic_skill_uses_issue_content(monkeypatch):
    settings = MagicMock()
    settings.security.allowed_commands = ["git"]
    settings.security.blocked_patterns = ["rm -rf"]
    monkeypatch.setattr("agent.skills.base.get_settings", lambda: settings)
    ctx = TurnContext(
        issue=Issue(id="i1", content="fix login", project="api"),
        turn_number=1,
        max_turns=1,
    )

    prompt = GenericSkill(MagicMock())._build_prompt(ctx)

    assert "fix login" in prompt
