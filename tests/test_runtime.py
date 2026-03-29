"""Tests for the Agent Runtime."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.agent.runtime import AgentRuntime
from agent.db.repos import ExecutionLogRepo, ExecutionRepo, IssueRepo
from agent.models import ExecutionStatus, IssueCreate, IssueStatus


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
    from agent.config import get_settings
    settings = get_settings()

    # Use object.__setattr__ since pydantic models are frozen
    object.__setattr__(settings.project, "workspace", str(tmp_git_repo))
    object.__setattr__(settings.project, "default_branch", "main")
    object.__setattr__(settings.project, "remote", "origin")
    object.__setattr__(settings.project, "pr_base", "main")
    object.__setattr__(settings.agent, "max_turns", 3)
    object.__setattr__(settings.agent, "task_timeout", 30)
    object.__setattr__(settings.opencode, "timeout", 10)

    monkeypatch.setattr("agent.agent.runtime.get_settings", lambda: settings)
    monkeypatch.setattr("agent.agent.context.get_settings", lambda: settings)
    monkeypatch.setattr("agent.skills.base.get_settings", lambda: settings)

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


# ── Workspace resolution tests ──


def test_resolve_workspace_prefers_child_over_distant_parent(mock_runtime, tmp_path):
    """When workspace is a parent dir containing a git repo child,
    _resolve_workspace should find the child, NOT walk up to an
    unrelated .git in an ancestor directory."""
    import subprocess

    runtime = mock_runtime

    # Create structure: tmp_path/parent_dir/real_repo (git repo)
    parent_dir = tmp_path / "parent_dir"
    parent_dir.mkdir()
    real_repo = parent_dir / "my-project"
    real_repo.mkdir()
    subprocess.run(["git", "init"], cwd=real_repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=real_repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=real_repo, capture_output=True, check=True)
    (real_repo / "README.md").write_text("# Hello")
    subprocess.run(["git", "add", "."], cwd=real_repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=real_repo, capture_output=True, check=True)

    # Create a FAKE .git directory in an ancestor (simulates /Users/foo/.git)
    fake_git = tmp_path / ".git"
    fake_git.mkdir()  # empty .git dir — not a real repo

    # Issue workspace points to parent_dir (not the repo itself)
    from agent.models import Issue, IssuePriority
    issue = Issue(
        id="test-ws-id", title="Test", description="",
        status=IssueStatus.open, priority=IssuePriority.medium,
        workspace=str(parent_dir),
    )

    resolved = runtime._resolve_workspace(issue)
    # Should find the child repo, NOT the fake ancestor .git
    assert resolved == str(real_repo), f"Expected {real_repo}, got {resolved}"


def test_resolve_workspace_exact_match(mock_runtime, tmp_path):
    """When workspace IS the git repo, return it directly."""
    import subprocess

    runtime = mock_runtime
    repo = tmp_path / "exact_repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True, check=True)
    (repo / "f.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True, check=True)

    from agent.models import Issue, IssuePriority
    issue = Issue(
        id="test-ws-exact", title="Test", description="",
        status=IssueStatus.open, priority=IssuePriority.medium,
        workspace=str(repo),
    )
    assert runtime._resolve_workspace(issue) == str(repo)


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
    from agent.server.event_bus import EventBus

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
    from agent.server.event_bus import EventBus

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


# ── Plan timeout tests ──


@pytest.mark.asyncio
async def test_plan_flow_timeout_retries_then_fails(mock_runtime):
    """Plan flow: timeout on both attempts → waiting_human with '超时' reason."""
    runtime = mock_runtime
    # Set very short plan_timeout to trigger timeout
    object.__setattr__(runtime.settings.agent, "plan_timeout", 0.1)

    call_count = 0

    async def slow_run(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(10)
        return "done"

    mock_client = MockOpenCodeClient([])
    mock_client.run_prompt = slow_run
    runtime.client = mock_client
    runtime.plan_skill.client = mock_client

    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="Plan timeout", description="test"))

    await runtime.start_plan(issue.id)
    task = runtime._running_tasks.get(issue.id)
    if task:
        await task

    updated = await repo.get(issue.id)
    assert updated.status == IssueStatus.waiting_human
    assert updated.failure_reason is not None
    assert "超时" in updated.failure_reason
    # Should have retried (2 attempts total)
    assert call_count == 2


# ── Integration: plan flow with large stderr (deadlock prevention) ──


class LargeStderrMockClient:
    """MockOpenCodeClient that simulates OpenCode producing large stderr output.

    Uses the real ``OpenCodeClient.run_prompt`` streaming loop by spawning a
    subprocess that writes lots of stderr before emitting stdout.  This would
    previously deadlock because stderr pipe buffer filled up while the parent
    only read stdout.

    For test simplicity we don't spawn a real subprocess; instead we return
    canned results but the *important thing* is that the plan flow's
    ``validate_spec`` is exercised end-to-end.
    """

    def __init__(self, spec_json: str):
        self._spec_json = spec_json
        self.call_count = 0
        self.prompts_received: list[str] = []

    async def run_prompt(self, prompt, *, cwd=".", cancel_event=None, on_event=None):
        self.prompts_received.append(prompt)
        self.call_count += 1
        return self._spec_json

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_plan_flow_with_large_spec_truncated(mock_runtime):
    """Plan flow: oversized spec fields are truncated by validate_spec."""
    from agent.skills.plan import _MAX_PLAN_CHARS, _MAX_SPEC_TOTAL_CHARS

    runtime = mock_runtime
    oversized_spec = json.dumps({
        "plan": "x" * (_MAX_PLAN_CHARS + 1000),
        "acceptance_criteria": [f"criterion {i}" for i in range(30)],
        "files_to_modify": ["src/client.py"],
        "estimated_complexity": "high",
    })
    mock_client = LargeStderrMockClient(oversized_spec)
    runtime.client = mock_client
    runtime.plan_skill.client = mock_client

    repo = IssueRepo()
    issue = await repo.create(IssueCreate(
        title="实现 SSE 流处理的 HTTP 客户端方法",
        description="需要实现一个支持 SSE (Server-Sent Events) 流处理的 HTTP 客户端方法，"
                    "能够连接到 SSE 端点并实时解析事件流。",
    ))

    await runtime.start_plan(issue.id)
    task = runtime._running_tasks.get(issue.id)
    if task:
        await task

    updated = await repo.get(issue.id)
    assert updated.status == IssueStatus.planned
    assert updated.spec is not None

    spec_data = json.loads(updated.spec)
    # plan field should have been truncated
    assert len(spec_data["plan"]) <= _MAX_PLAN_CHARS + len("…[truncated]")
    assert spec_data["plan"].endswith("…[truncated]")
    # criteria count should have been capped
    from agent.skills.plan import _MAX_CRITERIA_COUNT
    assert len(spec_data["acceptance_criteria"]) <= _MAX_CRITERIA_COUNT
    # total size should be within limit
    assert len(json.dumps(spec_data, ensure_ascii=False)) <= _MAX_SPEC_TOTAL_CHARS


@pytest.mark.asyncio
async def test_plan_flow_realistic_issue_produces_valid_spec(mock_runtime):
    """Plan flow end-to-end: realistic issue → valid, properly-bounded spec.

    Simulates the full _run_plan path with an issue like the user would create,
    verifying the spec is stored correctly and all fields are present.
    """
    runtime = mock_runtime
    realistic_spec = json.dumps({
        "plan": (
            "实现 SSE 流处理的 HTTP 客户端方法。主要步骤：\n"
            "1. 在 src/mango/agent/opencode_client.py 中添加 SSE 连接方法\n"
            "2. 使用 aiohttp 或 httpx 的流式响应支持\n"
            "3. 解析 SSE 事件格式 (event: / data: / id: / retry:)\n"
            "4. 添加自动重连逻辑和错误处理\n"
            "5. 编写完整的单元测试"
        ),
        "acceptance_criteria": [
            "能够连接到 SSE 端点并保持长连接",
            "正确解析 event、data、id、retry 字段",
            "支持自动重连（带退避策略）",
            "连接超时和错误有明确的异常处理",
            "单元测试覆盖正常流、断连重连、解析错误场景",
        ],
        "files_to_modify": [
            "src/mango/agent/opencode_client.py",
            "src/mango/agent/sse_client.py",
            "tests/test_sse_client.py",
        ],
        "estimated_complexity": "medium",
    })

    mock_client = LargeStderrMockClient(realistic_spec)
    runtime.client = mock_client
    runtime.plan_skill.client = mock_client

    repo = IssueRepo()
    issue = await repo.create(IssueCreate(
        title="实现 SSE 流处理的 HTTP 客户端方法",
        description="需要实现一个支持 SSE (Server-Sent Events) 流处理的 HTTP 客户端方法，"
                    "能够连接到 SSE 端点并实时解析事件流。要求支持自动重连和错误处理。",
    ))

    await runtime.start_plan(issue.id)
    task = runtime._running_tasks.get(issue.id)
    if task:
        await task

    updated = await repo.get(issue.id)
    assert updated.status == IssueStatus.planned
    assert updated.spec is not None

    spec_data = json.loads(updated.spec)
    # All 4 standard keys present
    assert set(spec_data.keys()) == {
        "plan", "acceptance_criteria", "files_to_modify", "estimated_complexity",
    }
    # Content integrity — no truncation on a normal-sized spec
    assert "SSE" in spec_data["plan"]
    assert len(spec_data["acceptance_criteria"]) == 5
    assert len(spec_data["files_to_modify"]) == 3
    assert spec_data["estimated_complexity"] == "medium"
    # Verify it's within total size limit
    from agent.skills.plan import _MAX_SPEC_TOTAL_CHARS
    assert len(json.dumps(spec_data, ensure_ascii=False)) <= _MAX_SPEC_TOTAL_CHARS

    # Execution record should have been created
    exec_repo = ExecutionRepo()
    executions = await exec_repo.list_by_issue(issue.id)
    assert len(executions) >= 1
    assert executions[0].status == ExecutionStatus.completed
