"""Agent Runtime — runTask → runTurn → runAttempt loop.

Phase 1: Full implementation of the three-layer execution loop
with timeout control, cancel tokens, and TurnContext propagation.
"""

from __future__ import annotations


class AgentRuntime:
    """Orchestrates the full lifecycle of an Issue execution.

    Responsibilities (Phase 1):
    - Load Issue from DB
    - Create git branch ``agent/{issue_id}``
    - Enter Turn loop (max_turns iterations)
    - Each Turn: build TurnContext → Skill constructs prompt → runAttempt
    - On success: git commit to branch, update Issue status to ``done``
    - On failure: update Issue status to ``failed`` / ``waiting_human``
    """

    pass
