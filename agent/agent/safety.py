"""Safety constraints — prompt injection rules and execution audit."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from agent.config import SecurityConfig

_KNOWN_COMMANDS: set[str] = {
    "git", "python", "pytest", "pip", "uv",
    "cat", "ls", "find", "grep", "head", "tail",
    "mkdir", "cp", "mv", "echo", "rm", "sudo",
    "curl", "wget", "chmod", "chown",
}


def build_safety_prompt(config: SecurityConfig) -> str:
    allowed = ", ".join(config.allowed_commands)
    forbidden_lines = "\n".join(f"- {p}" for p in config.blocked_patterns)
    return (
        "## Safety Rules\n"
        f"You may ONLY use these commands: {allowed}\n"
        "\n"
        "STRICTLY FORBIDDEN:\n"
        f"{forbidden_lines}\n"
        "\n"
        "Do NOT use any command not in the allowed list.\n"
        "Do NOT access /etc, /usr, /var, or any system directory.\n"
        "Do NOT make network requests unless the Issue explicitly requires it."
    )


def validate_command(command: str, config: SecurityConfig) -> bool:
    if not command or not command.strip():
        return False
    for pattern in config.blocked_patterns:
        if pattern in command:
            return False
    first_token = command.strip().split()[0]
    base_command = PurePosixPath(first_token).name
    return base_command in config.allowed_commands


def extract_commands_from_result(result: str) -> list[str]:
    if not result:
        return []
    commands: list[str] = []
    in_code_block = False
    for line in result.splitlines():
        stripped = line.strip()
        if re.match(r"^```(bash|sh)\s*$", stripped):
            in_code_block = True
            continue
        if stripped == "```" and in_code_block:
            in_code_block = False
            continue
        if stripped.startswith("$ ") or stripped.startswith("> "):
            cmd = stripped[2:].strip()
            if cmd:
                commands.append(cmd)
            continue
        if in_code_block and stripped:
            first_token = stripped.split()[0]
            base = PurePosixPath(first_token).name
            if base in _KNOWN_COMMANDS:
                commands.append(stripped)
    return commands
