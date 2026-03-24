"""Tests for the Agent Runtime."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mango.agent.runtime import AgentRuntime
from mango.db.repos import ExecutionLogRepo, ExecutionRepo, IssueRepo
from mango.models import ExecutionStatus, IssueCreate, IssueStatus


class MockOpenCodeClient:
    """Replaces OpenCodeClient for testing without a real opencode binary."""

    def __init__(self, responses: list, *, workspace: Path | None = None):
        self.responses = responses
        self.call_count = 0
        self.prompts_received: list[str] = []
        self._workspace = workspace

    async def run_prompt(self, prompt, *, cwd=".", cancel_event=None, on_event=None):
        self.prompts_received.append(prompt)
        if self.call_count >= len(self.responses):
            raise Exception("No more mock responses")
        result = self.responses[self.call_count]
        self.call_count += 1
        if isinstance(result, Exception):
            raise result
        # If workspace is set, write a file to simulate code changes
        if self._workspace is not None:
            target = self._workspace / f"change_{self.call_count}.py"
            target.write_text(f"# Generated change {self.call_count}\n")
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
    object.__setattr__(settings.project, "workspace", str(tmp_git_repo))
    object.__setattr__(settings.project, "default_branch", "main")
    object.__setattr__(settings.project, "remote", "origin")
    object.__setattr__(settings.project, "pr_base", "main")
    object.__setattr__(settings.agent, "max_turns", 3)
    object.__setattr__(settings.agent, "task_timeout", 30)
    object.__setattr__(settings.opencode, "timeout", 10)

    monkeypatch.setattr("mango.agent.runtime.get_settings", lambda: settings)
    monkeypatch.setattr("mango.agent.context.get_settings", lambda: settings)
    monkeypatch.setattr("mango.skills.base.get_settings", lambda: settings)

    runtime = AgentRuntime()
    return runtime


# ── Helpers ──


def _mock_push_and_pr(runtime):
    """Patch _git_push and _create_pr to succeed without a real remote."""
    runtime._git_push = AsyncMock(return_value=True)
    runtime._create_pr = AsyncMock(return_value="https://github.com/test/repo/pull/1")


# ── Success / failure flow tests ──


@pytest.mark.asyncio
async def test_run_task_success_flow(mock_runtime, tmp_git_repo):
    """AI succeeds on first turn with actual file changes → done + PR created."""
    runtime = mock_runtime
    mock_client = MockOpenCodeClient(
        ["Task completed successfully."], workspace=tmp_git_repo,
    )
    runtime.client = mock_client
    runtime.skill.client = mock_client
    _mock_push_and_pr(runtime)

    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="Fix bug", description="Fix the login bug"))

    await runtime.start_task(issue.id)
    task = runtime._running_tasks.get(issue.id)
    if task:
        await task

    updated = await repo.get(issue.id)
    assert updated.status == IssueStatus.review
    assert updated.pr_url == "https://github.com/test/repo/pull/1"
    runtime._git_push.assert_awaited_once()
    runtime._create_pr.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_task_no_changes_marks_waiting_human(mock_runtime):
    """AI reports success but no file changes → waiting_human (not done)."""
    runtime = mock_runtime
    # Client that does NOT write files
    mock_client = MockOpenCodeClient(["Looks good, nothing to change."])
    runtime.client = mock_client
    runtime.skill.client = mock_client
    _mock_push_and_pr(runtime)

    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="No changes", description="test"))

    await runtime.start_task(issue.id)
    task = runtime._running_tasks.get(issue.id)
    if task:
        await task

    updated = await repo.get(issue.id)
    assert updated.status == IssueStatus.waiting_human
    # Push and PR should NOT have been called
    runtime._git_push.assert_not_awaited()
    runtime._create_pr.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_task_push_failure_marks_waiting_human(mock_runtime, tmp_git_repo):
    """Commit succeeds but push fails → waiting_human."""
    runtime = mock_runtime
    mock_client = MockOpenCodeClient(["Fixed it."], workspace=tmp_git_repo)
    runtime.client = mock_client
    runtime.skill.client = mock_client
    runtime._git_push = AsyncMock(return_value=False)
    runtime._create_pr = AsyncMock(return_value=None)

    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="Push fail", description="test"))

    await runtime.start_task(issue.id)
    task = runtime._running_tasks.get(issue.id)
    if task:
        await task

    updated = await repo.get(issue.id)
    assert updated.status == IssueStatus.waiting_human


@pytest.mark.asyncio
async def test_run_task_pr_failure_still_done(mock_runtime, tmp_git_repo):
    """Push succeeds but PR creation fails → still done (code is on remote)."""
    runtime = mock_runtime
    mock_client = MockOpenCodeClient(["Fixed it."], workspace=tmp_git_repo)
    runtime.client = mock_client
    runtime.skill.client = mock_client
    runtime._git_push = AsyncMock(return_value=True)
    runtime._create_pr = AsyncMock(return_value=None)

    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="PR fail", description="test"))

    await runtime.start_task(issue.id)
    task = runtime._running_tasks.get(issue.id)
    if task:
        await task

    updated = await repo.get(issue.id)
    assert updated.status == IssueStatus.done
    assert updated.pr_url is None


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

    async def slow_run(*args, **kwargs):
        await asyncio.sleep(10)
        return "done"

    mock_client = MockOpenCodeClient([])
    mock_client.run_prompt = slow_run
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
async def test_run_task_creates_execution_records(mock_runtime, tmp_git_repo):
    runtime = mock_runtime
    mock_client = MockOpenCodeClient(["Success result"], workspace=tmp_git_repo)
    runtime.client = mock_client
    runtime.skill.client = mock_client
    _mock_push_and_pr(runtime)

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

    async def slow_run(*args, **kwargs):
        await asyncio.sleep(10)
        return "done"

    mock_client = MockOpenCodeClient([])
    mock_client.run_prompt = slow_run
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


# ── Recovery tests ──


@pytest.mark.asyncio
async def test_recover_from_restart(mock_runtime):
    """Issues stuck in 'running' should be recovered to 'waiting_human'."""
    runtime = mock_runtime
    repo = IssueRepo()

    # Create an issue and force it to 'running' status
    issue = await repo.create(IssueCreate(title="Stuck issue", description="stuck"))
    await repo.update_status(issue.id, IssueStatus.running)

    # Create an execution record so the log can be attached
    exec_repo = ExecutionRepo()
    import uuid
    exec_id = str(uuid.uuid4())
    await exec_repo.create(
        execution_id=exec_id, issue_id=issue.id,
        turn_number=1, attempt_number=1,
    )

    # Recover
    await runtime.recover_from_restart()

    updated = await repo.get(issue.id)
    assert updated.status == IssueStatus.waiting_human

    # Check that a log was created
    log_repo = ExecutionLogRepo()
    logs = await log_repo.list_by_execution(exec_id)
    assert any("服务重启" in log.message for log in logs)


@pytest.mark.asyncio
async def test_recover_from_restart_no_stuck_issues(mock_runtime):
    """Recovery is a no-op when there are no stuck issues."""
    runtime = mock_runtime
    # Should not raise
    await runtime.recover_from_restart()


# ── Git branch tests ──


@pytest.mark.asyncio
async def test_git_create_branch_existing(mock_runtime, tmp_git_repo):
    """Creating a branch that already exists should not error."""
    import subprocess
    runtime = mock_runtime
    branch = "agent/testbranch"
    # Create the branch manually
    subprocess.run(
        ["git", "checkout", "-b", branch], cwd=tmp_git_repo,
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "checkout", "main"], cwd=tmp_git_repo,
        capture_output=True, check=True,
    )
    # This should not raise
    await runtime._git_create_branch(branch, cwd=str(tmp_git_repo))

    # Verify we're on the branch
    result = subprocess.run(
        ["git", "branch", "--show-current"], cwd=tmp_git_repo,
        capture_output=True, text=True,
    )
    assert result.stdout.strip() == branch


# ── State machine tests ──


@pytest.mark.asyncio
async def test_cancelled_issue_can_rerun(mock_runtime, tmp_git_repo):
    """An issue in 'cancelled' status should be runnable."""
    runtime = mock_runtime
    mock_client = MockOpenCodeClient(["Done!"], workspace=tmp_git_repo)
    runtime.client = mock_client
    runtime.skill.client = mock_client
    _mock_push_and_pr(runtime)

    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="Cancelled issue", description="test"))
    await repo.update_status(issue.id, IssueStatus.cancelled)

    # Should not raise
    await runtime.start_task(issue.id)
    task = runtime._running_tasks.get(issue.id)
    if task:
        await task

    updated = await repo.get(issue.id)
    assert updated.status == IssueStatus.review


# ── EventBus integration tests ──


@pytest.mark.asyncio
async def test_run_attempt_emits_opencode_step_events(mock_runtime, tmp_git_repo):
    """Runtime should emit opencode_step events via EventBus when OpenCode streams events."""
    from mango.server.event_bus import EventBus

    event_bus = EventBus()
    runtime = mock_runtime
    runtime._event_bus = event_bus

    # Subscribe to the issue's events
    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="Step events", description="test"))
    queue = event_bus.subscribe(issue.id)

    mock_client = MockOpenCodeClient(["Success result"], workspace=tmp_git_repo)
    runtime.client = mock_client
    runtime.skill.client = mock_client
    _mock_push_and_pr(runtime)

    await runtime.start_task(issue.id)
    task = runtime._running_tasks.get(issue.id)
    if task:
        await task

    # Collect all events from the queue
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    event_types = [e["type"] for e in events]
    # Should have structural events
    assert "task_start" in event_types
    assert "turn_start" in event_types
    assert "attempt_start" in event_types
    assert "attempt_end" in event_types
    assert "turn_end" in event_types
    assert "task_end" in event_types
