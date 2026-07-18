"""Runtime lifecycle tests for simplified Issues."""

from __future__ import annotations

import asyncio

import pytest

from agent.agent.runtime import AgentRuntime
from agent.db.repos import IssueRepo
from agent.models import IssueCreate, IssueOutcome, IssueStatus


@pytest.mark.asyncio
async def test_start_task_claims_a_pending_issue_before_scheduling(initialized_db, monkeypatch):
    runtime = AgentRuntime()
    issue = await IssueRepo().create(IssueCreate(content="x", project="api"))
    started = asyncio.Event()

    async def hold_task(_issue_id, _cancel_event):
        started.set()

    monkeypatch.setattr(runtime, "_run_task", hold_task)

    await runtime.start_task(issue.id)
    await started.wait()

    saved = await IssueRepo().get(issue.id)
    assert saved is not None
    assert saved.status == IssueStatus.running
    await runtime.client.close()


@pytest.mark.asyncio
async def test_start_task_rejects_a_finished_issue(initialized_db):
    runtime = AgentRuntime()
    issue = await IssueRepo().create(IssueCreate(content="x", project="api"))
    await IssueRepo().finish(issue.id, IssueOutcome.success, "done", None)

    with pytest.raises(ValueError, match="cannot run"):
        await runtime.start_task(issue.id)

    await runtime.client.close()
