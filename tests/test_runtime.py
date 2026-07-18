"""Bridge-backed Issue runtime tests."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from agent.agent.cc_connect_client import CCConnectBridgeError
from agent.db.repos import IssueRepo
from agent.models import IssueCreate, IssueOutcome, IssueStatus


@pytest.mark.asyncio
async def test_runtime_sends_content_to_selected_project(mock_runtime):
    _, runtime = mock_runtime
    issue = await IssueRepo().create(IssueCreate(content="修复登录", project="api"))
    runtime.client.run_task = AsyncMock(return_value="已完成")

    await runtime.start_task(issue.id)
    await runtime.wait_for_task(issue.id)

    runtime.client.run_task.assert_awaited_once_with("api", "修复登录", issue.id)
    assert (await IssueRepo().get(issue.id)).outcome == IssueOutcome.success


@pytest.mark.asyncio
async def test_bridge_failure_finishes_issue_as_error(mock_runtime):
    _, runtime = mock_runtime
    issue = await IssueRepo().create(IssueCreate(content="x", project="api"))
    runtime.client.run_task = AsyncMock(side_effect=CCConnectBridgeError("offline"))

    await runtime.start_task(issue.id)
    await runtime.wait_for_task(issue.id)

    saved = await IssueRepo().get(issue.id)
    assert (saved.status, saved.outcome, saved.error_message) == (
        IssueStatus.finished,
        IssueOutcome.error,
        "offline",
    )


@pytest.mark.asyncio
async def test_cancelling_before_bridge_dispatch_does_not_submit_the_issue(mock_runtime):
    _, runtime = mock_runtime
    issue = await IssueRepo().create(IssueCreate(content="x", project="api"))
    original_get = runtime.issue_repo.get
    issue_loaded = asyncio.Event()
    continue_dispatch = asyncio.Event()

    async def delayed_get(issue_id):
        issue_loaded.set()
        await continue_dispatch.wait()
        return await original_get(issue_id)

    runtime.issue_repo.get = delayed_get
    runtime.client.run_task = AsyncMock(return_value="done")

    await runtime.start_task(issue.id)
    await issue_loaded.wait()
    assert await runtime.cancel_task(issue.id) is True
    continue_dispatch.set()
    await runtime.wait_for_task(issue.id)

    runtime.client.run_task.assert_not_awaited()
    saved = await IssueRepo().get(issue.id)
    assert (saved.status, saved.outcome, saved.error_message) == (
        IssueStatus.finished,
        IssueOutcome.error,
        "任务已取消",
    )
