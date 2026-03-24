"""Pydantic models and enums for Mango."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from pydantic import BaseModel


# ── Enums ────────────────────────────────────────────────────────────


class IssueStatus(str, Enum):
    open = "open"
    running = "running"
    done = "done"
    failed = "failed"
    waiting_human = "waiting_human"
    cancelled = "cancelled"


class ExecutionStatus(str, Enum):
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    timeout = "timeout"


class LogLevel(str, Enum):
    info = "info"
    warn = "warn"
    error = "error"


# ── DB entity models ────────────────────────────────────────────────


class Issue(BaseModel):
    id: str
    title: str
    description: str = ""
    status: IssueStatus = IssueStatus.open
    branch_name: str | None = None
    human_instruction: str | None = None
    pr_url: str | None = None
    failure_reason: str | None = None
    workspace: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class Execution(BaseModel):
    id: str
    issue_id: str
    turn_number: int
    attempt_number: int
    status: ExecutionStatus = ExecutionStatus.running
    prompt: str | None = None
    result: str | None = None
    error_message: str | None = None
    context_snapshot: str | None = None
    git_diff_snapshot: str | None = None
    duration_ms: int | None = None
    started_at: str | None = None
    finished_at: str | None = None


class ExecutionLog(BaseModel):
    id: int
    execution_id: str
    level: LogLevel = LogLevel.info
    message: str
    created_at: str | None = None


class StepType(str, Enum):
    tool_use = "tool_use"
    text = "text"
    step = "step"


class ExecutionStep(BaseModel):
    id: int
    execution_id: str
    step_type: StepType
    tool: str | None = None
    target: str | None = None
    summary: str | None = None
    created_at: str | None = None


# ── API request models ──────────────────────────────────────────────


class IssueCreate(BaseModel):
    title: str
    description: str = ""
    workspace: str | None = None


class IssueRetry(BaseModel):
    human_instruction: str | None = None
    workspace: str | None = None


# ── Runtime data structures ─────────────────────────────────────────


@dataclass
class TurnContext:
    """Per-turn context passed through the Agent Runtime loop.

    Carries the full context so each turn can make informed decisions
    instead of "blind retries".
    """

    issue: Issue
    turn_number: int
    max_turns: int
    last_result: str | None = None
    last_error: str | None = None
    git_diff: str | None = None
    execution_history: list[dict] = field(default_factory=list)
    human_instruction: str | None = None
