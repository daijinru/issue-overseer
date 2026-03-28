"""Pydantic models for Mango Gateway."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


# ── Enums ────────────────────────────────────────────────────────────


class SessionStatus(str, Enum):
    active = "active"
    closed = "closed"
    expired = "expired"


class MessageRole(str, Enum):
    user = "user"
    assistant = "assistant"
    system = "system"


# ── DB entity models ────────────────────────────────────────────────


class Session(BaseModel):
    id: str
    source: str = "api"
    source_id: str | None = None
    current_issue_id: str | None = None
    status: SessionStatus = SessionStatus.active
    runtime_url: str = ""
    metadata: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    closed_at: str | None = None


class Message(BaseModel):
    id: int
    session_id: str
    role: MessageRole
    content: str
    issue_id: str | None = None
    metadata: str | None = None
    created_at: str | None = None


# ── API request models ──────────────────────────────────────────────


class SessionCreate(BaseModel):
    source: str = "api"
    source_id: str | None = None
    metadata: dict | None = None


class GatewayMessageSend(BaseModel):
    content: str
    session_id: str | None = None
    source: str = "api"
    source_id: str | None = None
    wait: bool = False
    timeout: int = 1800
    workspace: str | None = None
    priority: str = "medium"


class GatewayReply(BaseModel):
    session_id: str
    message_id: int
    issue_id: str
    issue_status: str
    result: str | None = None
    pr_url: str | None = None
    failure_reason: str | None = None
