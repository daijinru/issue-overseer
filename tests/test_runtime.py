"""Tests for the Agent Runtime."""

from __future__ import annotations

import asyncio
import json
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


# ── Plan flow tests ──


@pytest.mark.asyncio
async def test_plan_flow_success(mock_runtime):
    """Plan flow: open → planning → planned with valid JSON spec."""
    runtime = mock_runtime
    valid_spec = json.dumps({
        "plan": "Fix the authentication bug",
        "acceptance_criteria": ["All tests pass"],
        "files_to_modify": ["auth.py"],
        "estimated_complexity": "medium",
    })
    mock_client = MockOpenCodeClient([valid_spec])
    runtime.client = mock_client
    runtime.plan_skill.client = mock_client

    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="Plan test", description="test"))

    await runtime.start_plan(issue.id)
    task = runtime._running_tasks.get(issue.id)
    if task:
        await task

    updated = await repo.get(issue.id)
    assert updated.status == IssueStatus.planned
    assert updated.spec is not None
    spec_data = json.loads(updated.spec)
    assert spec_data["plan"] == "Fix the authentication bug"
    assert spec_data["acceptance_criteria"] == ["All tests pass"]


@pytest.mark.asyncio
async def test_plan_flow_json_extraction_retry(mock_runtime):
    """Plan flow: first attempt returns non-JSON, retries with strict prompt, succeeds."""
    runtime = mock_runtime
    invalid_output = "Here's my analysis of the code..."
    valid_spec = json.dumps({
        "plan": "Add pagination",
        "acceptance_criteria": ["Page param works"],
        "files_to_modify": ["routes.py"],
        "estimated_complexity": "low",
    })
    mock_client = MockOpenCodeClient([invalid_output, valid_spec])
    runtime.client = mock_client
    runtime.plan_skill.client = mock_client

    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="Retry plan", description="test"))

    await runtime.start_plan(issue.id)
    task = runtime._running_tasks.get(issue.id)
    if task:
        await task

    updated = await repo.get(issue.id)
    assert updated.status == IssueStatus.planned
    assert updated.spec is not None
    # Verify it used 2 calls
    assert mock_client.call_count == 2


@pytest.mark.asyncio
async def test_plan_flow_all_attempts_fail(mock_runtime):
    """Plan flow: JSON extraction fails after all retries → waiting_human."""
    runtime = mock_runtime
    mock_client = MockOpenCodeClient([
        "I can't generate a plan right now.",
        "Still can't generate JSON.",
    ])
    runtime.client = mock_client
    runtime.plan_skill.client = mock_client

    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="Bad plan", description="test"))

    await runtime.start_plan(issue.id)
    task = runtime._running_tasks.get(issue.id)
    if task:
        await task

    updated = await repo.get(issue.id)
    assert updated.status == IssueStatus.waiting_human
    assert updated.failure_reason is not None
    assert "JSON" in updated.failure_reason


@pytest.mark.asyncio
async def test_plan_flow_wrong_status_raises(mock_runtime):
    """Plan flow: starting plan on non-open issue raises ValueError."""
    runtime = mock_runtime
    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="Running issue", description="test"))
    await repo.update_status(issue.id, IssueStatus.running)

    with pytest.raises(ValueError, match="must be 'open' to plan"):
        await runtime.start_plan(issue.id)


@pytest.mark.asyncio
async def test_plan_flow_cancel(mock_runtime):
    """Plan flow: cancel during plan execution → cancelled status.

    The _run_plan method checks cancel_event.is_set() at the top of each
    attempt loop iteration.  We simulate a first attempt that raises
    CancelledError (as if the outer task was cancelled while waiting).
    """
    runtime = mock_runtime

    async def cancelled_run(*args, **kwargs):
        # Simulate the task being cancelled while running
        raise asyncio.CancelledError()

    mock_client = MockOpenCodeClient([])
    mock_client.run_prompt = cancelled_run
    runtime.client = mock_client
    runtime.plan_skill.client = mock_client

    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="Cancel plan", description="test"))

    await runtime.start_plan(issue.id)

    task = runtime._running_tasks.get(issue.id)
    if task:
        try:
            await task
        except asyncio.CancelledError:
            pass

    updated = await repo.get(issue.id)
    assert updated.status == IssueStatus.cancelled


@pytest.mark.asyncio
async def test_plan_flow_emits_events(mock_runtime):
    """Plan flow emits plan_start and plan_end events via EventBus."""
    from mango.server.event_bus import EventBus

    event_bus = EventBus()
    runtime = mock_runtime
    runtime._event_bus = event_bus

    valid_spec = json.dumps({
        "plan": "test", "acceptance_criteria": [],
        "files_to_modify": [], "estimated_complexity": "low",
    })
    mock_client = MockOpenCodeClient([valid_spec])
    runtime.client = mock_client
    runtime.plan_skill.client = mock_client

    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="Event plan", description="test"))
    queue = event_bus.subscribe(issue.id)

    await runtime.start_plan(issue.id)
    task = runtime._running_tasks.get(issue.id)
    if task:
        await task

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    event_types = [e["type"] for e in events]
    assert "plan_start" in event_types
    assert "plan_end" in event_types
    # plan_end should have success=True
    plan_end = next(e for e in events if e["type"] == "plan_end")
    assert plan_end["data"]["success"] is True


@pytest.mark.asyncio
async def test_plan_flow_creates_execution_records(mock_runtime):
    """Plan flow creates execution records in the DB."""
    runtime = mock_runtime
    valid_spec = json.dumps({
        "plan": "test", "acceptance_criteria": [],
        "files_to_modify": [], "estimated_complexity": "low",
    })
    mock_client = MockOpenCodeClient([valid_spec])
    runtime.client = mock_client
    runtime.plan_skill.client = mock_client

    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="Exec record plan", description="test"))

    await runtime.start_plan(issue.id)
    task = runtime._running_tasks.get(issue.id)
    if task:
        await task

    exec_repo = ExecutionRepo()
    executions = await exec_repo.list_by_issue(issue.id)
    assert len(executions) >= 1
    assert executions[0].issue_id == issue.id


# ── Spec injection into execution context ──


@pytest.mark.asyncio
async def test_spec_injected_into_prompt(mock_runtime, tmp_git_repo):
    """When an issue has a spec, it should be included in the execution prompt."""
    runtime = mock_runtime
    mock_client = MockOpenCodeClient(
        ["Task completed successfully."], workspace=tmp_git_repo,
    )
    runtime.client = mock_client
    runtime.skill.client = mock_client
    _mock_push_and_pr(runtime)

    repo = IssueRepo()
    spec_content = json.dumps({
        "plan": "Add input validation",
        "acceptance_criteria": ["Validates email format"],
        "files_to_modify": ["routes.py"],
        "estimated_complexity": "low",
    })
    issue = await repo.create(IssueCreate(title="With spec", description="test"))
    await repo.update_status(issue.id, IssueStatus.planned)
    await repo.update_fields(issue.id, spec=spec_content)

    await runtime.start_task(issue.id)
    task = runtime._running_tasks.get(issue.id)
    if task:
        await task

    # Check that the prompt received by the client includes the spec
    assert len(mock_client.prompts_received) >= 1
    prompt = mock_client.prompts_received[0]
    assert "Add input validation" in prompt or "Spec" in prompt or "Plan" in prompt


# ── Review status tests ──


@pytest.mark.asyncio
async def test_success_flow_transitions_to_review(mock_runtime, tmp_git_repo):
    """Successful task with PR → review status (not done)."""
    runtime = mock_runtime
    mock_client = MockOpenCodeClient(
        ["Task completed."], workspace=tmp_git_repo,
    )
    runtime.client = mock_client
    runtime.skill.client = mock_client
    _mock_push_and_pr(runtime)

    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="To review", description="test"))

    await runtime.start_task(issue.id)
    task = runtime._running_tasks.get(issue.id)
    if task:
        await task

    updated = await repo.get(issue.id)
    assert updated.status == IssueStatus.review
    assert updated.pr_url is not None


# ── Recovery: planning stuck ──


@pytest.mark.asyncio
async def test_recover_from_restart_planning_status(mock_runtime):
    """Issues stuck in 'planning' should also be recovered to 'waiting_human'."""
    runtime = mock_runtime
    repo = IssueRepo()

    issue = await repo.create(IssueCreate(title="Stuck planning", description="stuck"))
    await repo.update_status(issue.id, IssueStatus.planning)

    exec_repo = ExecutionRepo()
    import uuid
    exec_id = str(uuid.uuid4())
    await exec_repo.create(
        execution_id=exec_id, issue_id=issue.id,
        turn_number=1, attempt_number=1,
    )

    await runtime.recover_from_restart()

    updated = await repo.get(issue.id)
    assert updated.status == IssueStatus.waiting_human

    log_repo = ExecutionLogRepo()
    logs = await log_repo.list_by_execution(exec_id)
    assert any("服务重启" in log.message for log in logs)
