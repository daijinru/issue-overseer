"""Pydantic models and enums for Mango."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────────────────────────────


class IssueStatus(str, Enum):
    pending = "pending"
    running = "running"
    finished = "finished"


class IssueOutcome(str, Enum):
    success = "success"
    error = "error"


# ── DB entity models ────────────────────────────────────────────────


class Issue(BaseModel):
    id: str
    content: str
    project: str
    status: IssueStatus = IssueStatus.pending
    outcome: IssueOutcome | None = None
    result: str | None = None
    error_message: str | None = Field(
        default=None,
        validation_alias="failure_reason",
    )
    created_at: str | None = None
    updated_at: str | None = None
    finished_at: str | None = None


# ── API request models ──────────────────────────────────────────────


class IssueCreate(BaseModel):
    content: str
    project: str
