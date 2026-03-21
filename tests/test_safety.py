"""Tests for the safety module."""

from __future__ import annotations

from mango.agent.safety import (
    build_safety_prompt,
    extract_commands_from_result,
    validate_command,
)
from mango.config import SecurityConfig


def _default_config() -> SecurityConfig:
    return SecurityConfig()


def test_build_safety_prompt_contains_allowed_commands():
    cfg = _default_config()
    prompt = build_safety_prompt(cfg)
    assert "git" in prompt
    assert "python" in prompt
    assert "pytest" in prompt


def test_build_safety_prompt_contains_blocked_patterns():
    cfg = _default_config()
    prompt = build_safety_prompt(cfg)
    assert "sudo" in prompt
    assert "rm -rf /" in prompt


def test_validate_command_allows_git():
    cfg = _default_config()
    assert validate_command("git status", cfg) is True


def test_validate_command_blocks_sudo():
    cfg = _default_config()
    assert validate_command("sudo rm -rf /", cfg) is False


def test_validate_command_blocks_rm_rf():
    cfg = _default_config()
    assert validate_command("rm -rf /", cfg) is False


def test_validate_command_handles_path_prefix():
    cfg = _default_config()
    assert validate_command("/usr/bin/python script.py", cfg) is True


def test_extract_commands_from_result_finds_dollar_prefix():
    text = "some text\n$ git status\nmore text\n$ python test.py"
    commands = extract_commands_from_result(text)
    assert "git status" in commands
    assert "python test.py" in commands


def test_extract_commands_from_result_finds_code_block():
    text = "```bash\ngit add .\ngit commit -m 'test'\n```"
    commands = extract_commands_from_result(text)
    assert "git add ." in commands
    assert "git commit -m 'test'" in commands


def test_extract_commands_empty_string():
    commands = extract_commands_from_result("")
    assert commands == []
