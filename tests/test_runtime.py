"""Tests for the Agent Runtime."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mango.agent.runtime import AgentRuntime
from mango.db.repos import ExecutionLogRepo, ExecutionRepo, IssueRepo
from mango.models import IssueCreate, IssueStatus


class MockOpenCodeClient:
    """Replaces OpenCodeClient for testing without a real OpenCode server."""

    def __init__(self, responses: list):
        self.responses = responses
        self.call_count = 0
        self.prompts_received: list[str] = []

    async def create_session(self) -> str:
        return "mock-session-id"

    async def send_prompt(self, session_id, prompt, *, cancel_event=None):
        self.prompts_received.append(prompt)
        if self.call_count >= len(self.responses):
            raise Exception("No more mock responses")
        result = self.responses[self.call_count]
        self.call_count += 1
        if isinstance(result, Exception):
            raise result
        return result

    async def close(self):
        pass


@pytest.fixture()
def tmp_git_repo(tmp_path):
    """Create a temporary git repository for testing."""
    import subprocess
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True, check=True)
    # Create initial commit on main
    (repo / "README.md").write_text("# Test")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, capture_output=True, check=True)
    return repo


@pytest.fixture()
async def mock_runtime(initialized_db, tmp_git_repo, monkeypatch):
    """AgentRuntime with mocked OpenCodeClient for testing."""
    from mango.config import get_settings
    settings = get_settings()

    # Use object.__setattr__ since pydantic models are frozen
    object.__setattr__(settings.project, "repo_path", str(tmp_git_repo))
    object.__setattr__(settings.project, "default_branch", "main")
    object.__setattr__(settings.agent, "max_turns", 3)
    object.__setattr__(settings.agent, "task_timeout", 30)
    object.__setattr__(settings.opencode, "timeout", 10)

    monkeypatch.setattr("mango.agent.runtime.get_settings", lambda: settings)
    monkeypatch.setattr("mango.agent.context.get_settings", lambda: settings)
    monkeypatch.setattr("mango.skills.base.get_settings", lambda: settings)

    runtime = AgentRuntime()
    return runtime


@pytest.mark.asyncio
async def test_run_task_success_flow(mock_runtime):
    runtime = mock_runtime
    mock_client = MockOpenCodeClient(["Task completed successfully."])
    runtime.client = mock_client
    runtime.skill.client = mock_client

    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="Fix bug", description="Fix the login bug"))

    await runtime.start_task(issue.id)
    # Wait for task to complete
    task = runtime._running_tasks.get(issue.id)
    if task:
        await task

    updated = await repo.get(issue.id)
    assert updated.status == IssueStatus.done


@pytest.mark.asyncio
async def test_run_task_all_turns_fail(mock_runtime):
    runtime = mock_runtime
    mock_client = MockOpenCodeClient([
        Exception("Error 1"),
        Exception("Error 2"),
        Exception("Error 3"),
    ])
    runtime.client = mock_client
    runtime.skill.client = mock_client

    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="Hard bug", description="Very hard"))

    await runtime.start_task(issue.id)
    task = runtime._running_tasks.get(issue.id)
    if task:
        await task

    updated = await repo.get(issue.id)
    assert updated.status == IssueStatus.waiting_human


@pytest.mark.asyncio
async def test_run_task_cancel(mock_runtime):
    runtime = mock_runtime

    async def slow_send(*args, **kwargs):
        await asyncio.sleep(10)
        return "done"

    mock_client = MockOpenCodeClient([])
    mock_client.send_prompt = slow_send
    runtime.client = mock_client
    runtime.skill.client = mock_client

    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="Cancel me", description="test"))

    await runtime.start_task(issue.id)
    # Give it a moment to start
    await asyncio.sleep(0.1)
    await runtime.cancel_task(issue.id)

    task = runtime._running_tasks.get(issue.id)
    if task:
        try:
            await task
        except asyncio.CancelledError:
            pass

    updated = await repo.get(issue.id)
    assert updated.status == IssueStatus.cancelled


@pytest.mark.asyncio
async def test_run_task_creates_execution_records(mock_runtime):
    runtime = mock_runtime
    mock_client = MockOpenCodeClient(["Success result"])
    runtime.client = mock_client
    runtime.skill.client = mock_client

    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="Record test", description="test"))

    await runtime.start_task(issue.id)
    task = runtime._running_tasks.get(issue.id)
    if task:
        await task

    exec_repo = ExecutionRepo()
    executions = await exec_repo.list_by_issue(issue.id)
    assert len(executions) >= 1
    assert executions[0].issue_id == issue.id

    log_repo = ExecutionLogRepo()
    logs = await log_repo.list_by_issue(issue.id)
    assert len(logs) >= 1


@pytest.mark.asyncio
async def test_run_task_timeout(mock_runtime):
    runtime = mock_runtime
    # Set very short timeout
    object.__setattr__(runtime.settings.opencode, "timeout", 0.1)

    async def slow_send(*args, **kwargs):
        await asyncio.sleep(10)
        return "done"

    mock_client = MockOpenCodeClient([])
    mock_client.send_prompt = slow_send
    mock_client.create_session = MockOpenCodeClient([]).create_session
    runtime.client = mock_client
    runtime.skill.client = mock_client

    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="Timeout test", description="test"))

    await runtime.start_task(issue.id)
    task = runtime._running_tasks.get(issue.id)
    if task:
        await task

    updated = await repo.get(issue.id)
    assert updated.status == IssueStatus.waiting_human
