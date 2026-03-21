"""Safety constraints — prompt injection rules and execution audit.

Phase 1: Validate commands against allowed_commands whitelist
and blocked_patterns. Inject safety rules into prompts.
"""

from __future__ import annotations

from mango.config import SecurityConfig


def build_safety_prompt(config: SecurityConfig) -> str:
    """Build the safety rules section to inject into every prompt.

    Phase 1: Generate the safety constraint text from config.
    """
    raise NotImplementedError("Phase 1")


def validate_command(command: str, config: SecurityConfig) -> bool:
    """Check whether a command is allowed by the safety config.

    Returns ``True`` if the command passes all checks.

    Phase 1: Implement whitelist + blocked pattern matching.
    """
    raise NotImplementedError("Phase 1")
