"""Tests for config loading."""

from __future__ import annotations

from agent.config import Settings


def test_default_config_loads():
    """Settings can be instantiated with all defaults (no TOML file)."""
    settings = Settings()
    assert settings.server.port == 18800
    assert settings.agent.max_turns == 3
    assert settings.agent.task_timeout == 1800
    assert settings.opencode.command == "opencode"
    assert settings.opencode.timeout == 300
    assert settings.project.default_branch == "main"
    assert settings.database.path == "./data/mango.db"
    assert settings.context.max_git_diff_lines == 2000
    assert settings.context.max_result_chars == 5000


def test_security_config_has_commands():
    """Security config should have non-empty allowed_commands list."""
    settings = Settings()
    assert len(settings.security.allowed_commands) > 0
    assert "git" in settings.security.allowed_commands
    assert "python" in settings.security.allowed_commands


def test_security_config_has_blocked_patterns():
    """Security config should have non-empty blocked_patterns list."""
    settings = Settings()
    assert len(settings.security.blocked_patterns) > 0
    assert "sudo" in settings.security.blocked_patterns
