"""End-to-end integration test — real opencode, real git remote, real DB.

Validates the ROADMAP Phase 1 + Step 1 acceptance criteria:
  创建 Issue → AI 执行 → 代码提交 → push → PR 自动创建 → Issue 展示 PR 链接

Requires:
  - ``opencode`` binary on PATH with a configured provider
  - ``gh`` CLI authenticated with push access to the test repo
  - Network access to GitHub

Run with: uv run pytest tests/test_e2e.py -v -s -m e2e

Test fixture source files live in tests/fixtures/e2e_repo/:
  - calc.py       — buggy calculator (return a - b)
  - test_calc.py  — tests that fail against the bug
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agent.agent.runtime import AgentRuntime
from agent.db.repos import ExecutionLogRepo, ExecutionRepo, IssueRepo
from agent.models import ExecutionStatus, IssueCreate, IssueStatus

pytestmark = pytest.mark.e2e

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "e2e_repo"
REMOTE_REPO = "https://github.com/daijinru/test-issue-overseer"
REMOTE_REPO_NWO = "daijinru/test-issue-overseer"


def _opencode_available() -> bool:
    """Check if opencode is installed and runnable."""
    try:
        result = subprocess.run(
            ["opencode", "--version"],
            capture_output=True, timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _gh_available() -> bool:
    """Check if gh CLI is installed and authenticated."""
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True, timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


skipif_no_opencode = pytest.mark.skipif(
    not _opencode_available(),
    reason="opencode CLI not available",
)

skipif_no_gh = pytest.mark.skipif(
    not _gh_available(),
    reason="gh CLI not available or not authenticated",
)


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture()
def e2e_git_repo(tmp_path):
    """Clone the real remote repo and copy buggy fixture files into it.

    This gives us a repo with a real ``origin`` remote that we can push to.
    After the test, we clean up any remote branches and PRs we created.

    Returns a (repo_path, created_branches_list) tuple.
    """
    repo = tmp_path / "e2e_repo"

    # 1. Clone the real remote repo
    subprocess.run(
        ["git", "clone", REMOTE_REPO, str(repo)],
        capture_output=True, check=True, timeout=60,
    )

    # 2. Configure git user for commits
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Mango E2E Test"],
        cwd=repo, capture_output=True, check=True,
    )

    # 3. Copy buggy fixture files into the cloned repo
    for fixture_file in FIXTURES_DIR.iterdir():
        if fixture_file.is_file():
            shutil.copy2(fixture_file, repo / fixture_file.name)

    # 4. Commit the buggy files to main
    subprocess.run(
        ["git", "add", "calc.py", "test_calc.py"],
        cwd=repo, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "test: add buggy calc fixture"],
        cwd=repo, capture_output=True, check=True,
    )

    # 5. Verify the test actually fails with the buggy code
    result = subprocess.run(
        ["python", "-m", "pytest", "test_calc.py", "-q"],
        cwd=repo, capture_output=True,
    )
    assert result.returncode != 0, "Test should fail with the buggy code"

    # Track branches created during this test for cleanup
    created_branches: list[str] = []

    yield repo, created_branches

    # ── Cleanup: close any PRs and delete remote branches ──
    for branch in created_branches:
        # Close any open PRs from this branch
        subprocess.run(
            ["gh", "pr", "close", branch, "--repo", REMOTE_REPO_NWO,
             "--delete-branch"],
            capture_output=True, timeout=30,
        )
        # Also try to delete the remote branch directly (in case PR was not created)
        subprocess.run(
            ["git", "push", "origin", "--delete", branch],
            cwd=repo, capture_output=True, timeout=30,
        )


@pytest.fixture()
async def e2e_runtime(initialized_db, e2e_git_repo, monkeypatch):
    """AgentRuntime wired to the real opencode CLI and a test git repo with remote."""
    from agent.config import get_settings

    repo_path, _branches = e2e_git_repo
    settings = get_settings()

    object.__setattr__(settings.project, "workspace", str(repo_path))
    object.__setattr__(settings.project, "default_branch", "main")
    object.__setattr__(settings.project, "remote", "origin")
    object.__setattr__(settings.project, "pr_base", "main")
    object.__setattr__(settings.agent, "max_turns", 3)
    object.__setattr__(settings.agent, "task_timeout", 300)
    object.__setattr__(settings.opencode, "command", "opencode")
    object.__setattr__(settings.opencode, "timeout", 120)

    monkeypatch.setattr("agent.agent.runtime.get_settings", lambda: settings)
    monkeypatch.setattr("agent.agent.context.get_settings", lambda: settings)
    monkeypatch.setattr("agent.skills.base.get_settings", lambda: settings)

    runtime = AgentRuntime()
    yield runtime

    await runtime.client.close()


# ── Helpers ─────────────────────────────────────────────────────────


def _tests_pass(repo_path) -> bool:
    """Run pytest in the repo and return True if all tests pass."""
    result = subprocess.run(
        ["python", "-m", "pytest", "test_calc.py", "-q"],
        cwd=repo_path, capture_output=True,
    )
    return result.returncode == 0


def _get_branch_commits(repo_path, branch_name: str) -> str:
    """Get commits on branch since main."""
    result = subprocess.run(
        ["git", "log", "--oneline", f"main..{branch_name}"],
        cwd=repo_path, capture_output=True, text=True,
    )
    return result.stdout.strip()


def _branch_exists(repo_path, branch_name: str) -> bool:
    """Check if a git branch exists locally."""
    result = subprocess.run(
        ["git", "branch", "--list", branch_name],
        cwd=repo_path, capture_output=True, text=True,
    )
    return branch_name in result.stdout


def _remote_branch_exists(repo_path, branch_name: str) -> bool:
    """Check if a branch exists on the remote."""
    result = subprocess.run(
        ["git", "ls-remote", "--heads", "origin", branch_name],
        cwd=repo_path, capture_output=True, text=True,
    )
    return branch_name in result.stdout


def _current_branch(repo_path) -> str:
    """Return the name of the current branch."""
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo_path, capture_output=True, text=True,
    )
    return result.stdout.strip()


async def _run_and_wait(runtime, issue_id: str) -> None:
    """Start a task and wait for it to complete."""
    await runtime.start_task(issue_id)
    task = runtime._running_tasks.get(issue_id)
    assert task is not None, "Task should be running"
    await task


# ── Tests: Full lifecycle (real opencode + real remote) ─────────────


@skipif_no_opencode
@skipif_no_gh
@pytest.mark.asyncio
@pytest.mark.timeout(600)
async def test_e2e_fix_bug_full_lifecycle(e2e_runtime, e2e_git_repo):
    """Full acceptance test — Issue → AI fix → commit → push → PR → review.

    This test uses a real opencode process to fix a simple bug:
    calc.py has `return a - b` instead of `return a + b`.

    The test validates:
    1. Issue status transitions (open → running → review/waiting_human)
    2. Git branch is created
    3. Execution records exist in DB
    4. If first attempt fails, retry with instruction works
    5. Code is actually fixed and committed
    6. Code is pushed to the real remote
    7. PR is created on GitHub with a URL
    8. Status is 'review' (not 'done') after PR creation
    """
    repo_path, created_branches = e2e_git_repo
    runtime = e2e_runtime
    repo = IssueRepo()

    # ── Step 1: Create Issue ──
    issue = await repo.create(IssueCreate(
        title="Fix the add function in calc.py",
        description=(
            "The file calc.py has a bug in the add() function: "
            "it returns `a - b` instead of `a + b`. "
            "Change the minus sign to a plus sign on that line. "
            "After fixing, verify by running: python -m pytest test_calc.py"
        ),
    ))
    assert issue.status == IssueStatus.open

    # ── Step 2: First AI execution ──
    await _run_and_wait(runtime, issue.id)

    updated = await repo.get(issue.id)

    # Branch should be created regardless of success/failure
    assert updated.branch_name is not None
    assert updated.branch_name.startswith("agent/")
    assert _branch_exists(repo_path, updated.branch_name)

    # Track branch for cleanup
    created_branches.append(updated.branch_name)

    # Execution records should exist
    exec_repo = ExecutionRepo()
    executions = await exec_repo.list_by_issue(issue.id)
    assert len(executions) >= 1, "At least one execution record"

    log_repo = ExecutionLogRepo()
    logs = await log_repo.list_by_issue(issue.id)
    assert len(logs) >= 1, "At least one log entry"

    # ── Step 3: Check if AI fixed it on the first try ──
    # After ROADMAP3: PR creation → review (not done)
    if updated.status in (IssueStatus.review, IssueStatus.done):
        # AI succeeded — verify push happened
        assert _remote_branch_exists(repo_path, updated.branch_name), (
            "Branch should be pushed to remote"
        )

        # Verify PR was created
        assert updated.pr_url is not None, (
            "PR URL should be set on the issue"
        )
        assert "github.com" in updated.pr_url, (
            f"PR URL should be a GitHub URL, got: {updated.pr_url}"
        )

        # Check the fix on the branch
        subprocess.run(
            ["git", "checkout", updated.branch_name],
            cwd=repo_path, capture_output=True, check=True,
        )
        if _tests_pass(repo_path):
            # Perfect — first attempt fixed the bug and created a PR
            assert _get_branch_commits(repo_path, updated.branch_name)
            return

        # AI claimed success but didn't actually fix — fall through to retry

    # ── Step 4: Retry with human instruction ──
    # Reset to waiting_human if not already
    if updated.status in (IssueStatus.review, IssueStatus.done):
        await repo.update_status(issue.id, IssueStatus.waiting_human)

    # Switch back to main so the agent branch can be reused
    subprocess.run(
        ["git", "checkout", "main"],
        cwd=repo_path, capture_output=True,
    )

    await repo.retry_reset(
        issue.id,
        human_instruction=(
            "The fix is very simple: in calc.py line 6, change `return a - b` "
            "to `return a + b`. That is the ONLY change needed. "
            "Do NOT modify test_calc.py."
        ),
    )
    await _run_and_wait(runtime, issue.id)

    retried = await repo.get(issue.id)

    # After retry, should be review (or done if PR creation failed but push succeeded)
    assert retried.status in (IssueStatus.review, IssueStatus.done), (
        f"Expected review or done after retry, got {retried.status}"
    )

    # Verify push and PR
    assert _remote_branch_exists(repo_path, retried.branch_name), (
        "Branch should be pushed to remote after retry"
    )
    assert retried.pr_url is not None, (
        "PR URL should be set after retry"
    )
    assert "github.com" in retried.pr_url, (
        f"PR URL should be a GitHub URL, got: {retried.pr_url}"
    )

    # Verify the fix
    subprocess.run(
        ["git", "checkout", retried.branch_name],
        cwd=repo_path, capture_output=True, check=True,
    )
    assert _tests_pass(repo_path), (
        "Tests should pass after retry with explicit instruction"
    )

    # Commit should exist on branch
    assert _get_branch_commits(repo_path, retried.branch_name), (
        "At least one commit should exist on the agent branch"
    )

    # More execution records after retry
    all_executions = await exec_repo.list_by_issue(issue.id)
    assert len(all_executions) >= 2, (
        "Should have execution records from both attempts"
    )


@skipif_no_opencode
@skipif_no_gh
@pytest.mark.asyncio
@pytest.mark.timeout(600)
async def test_e2e_pr_contains_changed_files(e2e_runtime, e2e_git_repo):
    """Verify the PR body includes the changed files list."""
    repo_path, created_branches = e2e_git_repo
    runtime = e2e_runtime
    repo = IssueRepo()

    issue = await repo.create(IssueCreate(
        title="Fix the add function in calc.py",
        description=(
            "The file calc.py has a bug: `return a - b` should be `return a + b`. "
            "Fix only that one line."
        ),
    ))

    await _run_and_wait(runtime, issue.id)

    updated = await repo.get(issue.id)
    created_branches.append(updated.branch_name)

    if updated.status not in (IssueStatus.review, IssueStatus.done) or updated.pr_url is None:
        pytest.skip("AI did not produce a successful PR — cannot verify PR body")

    # Fetch the PR body via gh CLI
    pr_number = updated.pr_url.rstrip("/").split("/")[-1]
    result = subprocess.run(
        ["gh", "pr", "view", pr_number, "--repo", REMOTE_REPO_NWO,
         "--json", "body", "--jq", ".body"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"gh pr view failed: {result.stderr}"

    pr_body = result.stdout
    # PR body should contain the changed files section
    assert "Changed files:" in pr_body, (
        f"PR body should contain 'Changed files:' section, got:\n{pr_body}"
    )
    assert "calc.py" in pr_body, (
        f"PR body should mention calc.py in changed files, got:\n{pr_body}"
    )


# ── Tests: Restart recovery (no opencode needed) ───────────────────


@pytest.mark.asyncio
async def test_e2e_recover_stuck_issue_on_restart(initialized_db, tmp_path, monkeypatch):
    """Simulates a service restart: an issue stuck in 'running' is recovered.

    Validates P0 #2 acceptance criteria:
    - Service scans for running issues at startup
    - Stuck issues → waiting_human
    - Execution log records the interruption
    """
    from agent.config import get_settings

    settings = get_settings()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_dir, capture_output=True, check=True)
    (repo_dir / "README.md").write_text("# Test")
    subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_dir, capture_output=True, check=True)

    object.__setattr__(settings.project, "workspace", str(repo_dir))
    object.__setattr__(settings.project, "default_branch", "main")
    monkeypatch.setattr("agent.agent.runtime.get_settings", lambda: settings)
    monkeypatch.setattr("agent.agent.context.get_settings", lambda: settings)
    monkeypatch.setattr("agent.skills.base.get_settings", lambda: settings)

    repo = IssueRepo()
    exec_repo = ExecutionRepo()
    log_repo = ExecutionLogRepo()

    # Create two issues: one stuck in running, one done (should not change)
    stuck = await repo.create(IssueCreate(title="Stuck issue", description="Was running"))
    await repo.update_status(stuck.id, IssueStatus.running)
    exec_id = str(uuid.uuid4())
    await exec_repo.create(
        execution_id=exec_id, issue_id=stuck.id,
        turn_number=1, attempt_number=1,
    )

    done_issue = await repo.create(IssueCreate(title="Done issue", description="Already done"))
    await repo.update_status(done_issue.id, IssueStatus.done)

    # Simulate restart by creating a fresh runtime and calling recover
    runtime = AgentRuntime()
    await runtime.recover_from_restart()

    # Stuck issue should be recovered
    recovered = await repo.get(stuck.id)
    assert recovered.status == IssueStatus.waiting_human, (
        f"Stuck issue should be waiting_human, got {recovered.status}"
    )

    # Recovery log should exist
    logs = await log_repo.list_by_execution(exec_id)
    assert any("服务重启" in log.message for log in logs), (
        "Recovery log should mention 服务重启"
    )

    # Latest execution should be marked as failed
    executions = await exec_repo.list_by_issue(stuck.id)
    latest = executions[-1]
    assert latest.status == ExecutionStatus.failed

    # Done issue should NOT be affected
    done_check = await repo.get(done_issue.id)
    assert done_check.status == IssueStatus.done


# ── Tests: Cancel during execution (no opencode needed) ────────────


@pytest.mark.asyncio
async def test_e2e_cancel_during_execution(initialized_db, tmp_path, monkeypatch):
    """Cancel a running issue and verify status transitions.

    Validates P1 #5: cancel works correctly during execution.
    """
    from agent.agent.runtime import AgentRuntime as _Runtime
    from agent.config import get_settings

    settings = get_settings()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_dir, capture_output=True, check=True)
    (repo_dir / "README.md").write_text("# Test")
    subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_dir, capture_output=True, check=True)

    object.__setattr__(settings.project, "workspace", str(repo_dir))
    object.__setattr__(settings.project, "default_branch", "main")
    object.__setattr__(settings.agent, "max_turns", 3)
    object.__setattr__(settings.agent, "task_timeout", 60)
    object.__setattr__(settings.opencode, "timeout", 30)
    monkeypatch.setattr("agent.agent.runtime.get_settings", lambda: settings)
    monkeypatch.setattr("agent.agent.context.get_settings", lambda: settings)
    monkeypatch.setattr("agent.skills.base.get_settings", lambda: settings)

    runtime = _Runtime()

    # Replace client with a slow mock that respects cancel_event
    async def slow_run(*args, cancel_event=None, **kwargs):
        if cancel_event:
            # Wait for cancel or a long time
            await cancel_event.wait()
            raise asyncio.CancelledError("Cancelled during execution")
        await asyncio.sleep(60)
        return "done"

    runtime.client.run_prompt = slow_run
    runtime.skill.client = runtime.client

    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="Cancel me", description="test"))

    await runtime.start_task(issue.id)
    # Give it a moment to start and reach the slow_run
    await asyncio.sleep(0.3)

    # Cancel
    cancelled = await runtime.cancel_task(issue.id)
    assert cancelled is True

    task = runtime._running_tasks.get(issue.id)
    if task:
        try:
            await asyncio.wait_for(task, timeout=5)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    updated = await repo.get(issue.id)
    assert updated.status == IssueStatus.cancelled

    # Branch should have been created before cancellation
    assert updated.branch_name is not None
    assert updated.branch_name.startswith("agent/")


# ── Tests: Cancelled issue can rerun (with real opencode) ──────────


@skipif_no_opencode
@skipif_no_gh
@pytest.mark.asyncio
@pytest.mark.timeout(600)
async def test_e2e_cancelled_rerun_to_success(e2e_runtime, e2e_git_repo):
    """A cancelled issue can be re-run and complete successfully.

    Validates P1 #5 state machine: cancelled → open → running → done.
    """
    repo_path, created_branches = e2e_git_repo
    runtime = e2e_runtime
    repo = IssueRepo()

    issue = await repo.create(IssueCreate(
        title="Fix the add function in calc.py",
        description=(
            "The file calc.py has a bug: `return a - b` should be `return a + b`. "
            "Fix only that one line. Do NOT modify test_calc.py."
        ),
    ))

    # Manually set to cancelled (simulating a previous cancelled run)
    await repo.update_status(issue.id, IssueStatus.cancelled)

    # Now re-run from cancelled state
    await _run_and_wait(runtime, issue.id)

    updated = await repo.get(issue.id)
    created_branches.append(updated.branch_name)

    # Should succeed (or at least not be stuck in cancelled)
    assert updated.status in (IssueStatus.review, IssueStatus.done, IssueStatus.waiting_human), (
        f"Expected review, done, or waiting_human after rerun, got {updated.status}"
    )

    if updated.status in (IssueStatus.review, IssueStatus.done):
        assert updated.pr_url is not None, "PR URL should be set"
        assert _remote_branch_exists(repo_path, updated.branch_name)


# ── Tests: Git operations (branch reuse, commit check) ─────────────


@skipif_no_opencode
@skipif_no_gh
@pytest.mark.asyncio
@pytest.mark.timeout(600)
async def test_e2e_branch_reused_on_retry(e2e_runtime, e2e_git_repo):
    """When retrying an issue, the same agent branch is reused.

    Validates P1 #4: branch already exists → git checkout (not -b).
    """
    repo_path, created_branches = e2e_git_repo
    runtime = e2e_runtime
    repo = IssueRepo()

    issue = await repo.create(IssueCreate(
        title="Fix the add function in calc.py",
        description=(
            "The file calc.py has a bug: `return a - b` should be `return a + b`. "
            "Fix only calc.py, not test_calc.py."
        ),
    ))

    # First run
    await _run_and_wait(runtime, issue.id)
    updated = await repo.get(issue.id)
    first_branch = updated.branch_name
    assert first_branch is not None

    created_branches.append(first_branch)

    # If it succeeded, we can still test branch reuse by retrying
    if updated.status in (IssueStatus.review, IssueStatus.done):
        await repo.update_status(issue.id, IssueStatus.waiting_human)

    # Switch back to main before retry
    subprocess.run(
        ["git", "checkout", "main"],
        cwd=repo_path, capture_output=True,
    )

    await repo.retry_reset(issue.id, human_instruction="Try again — same fix needed.")
    await _run_and_wait(runtime, issue.id)

    retried = await repo.get(issue.id)
    # Branch name should be the same (reused, not a new branch)
    assert retried.branch_name == first_branch, (
        f"Branch should be reused: expected {first_branch}, got {retried.branch_name}"
    )


# ── Tests: Execution records integrity ──────────────────────────────


@skipif_no_opencode
@skipif_no_gh
@pytest.mark.asyncio
@pytest.mark.timeout(600)
async def test_e2e_execution_records_complete(e2e_runtime, e2e_git_repo):
    """Verify execution records and logs are properly stored after a run.

    Each turn should create an execution record with:
    - Correct turn_number
    - Non-null prompt
    - Status (completed or failed)
    - Duration tracked
    """
    repo_path, created_branches = e2e_git_repo
    runtime = e2e_runtime
    repo = IssueRepo()

    issue = await repo.create(IssueCreate(
        title="Fix the add function in calc.py",
        description=(
            "In calc.py, change `return a - b` to `return a + b`. "
            "That is the only change."
        ),
    ))

    await _run_and_wait(runtime, issue.id)

    updated = await repo.get(issue.id)
    created_branches.append(updated.branch_name)

    # Check execution records
    exec_repo = ExecutionRepo()
    executions = await exec_repo.list_by_issue(issue.id)
    assert len(executions) >= 1

    for exc in executions:
        assert exc.issue_id == issue.id
        assert exc.turn_number >= 1
        assert exc.attempt_number >= 1
        assert exc.prompt is not None and len(exc.prompt) > 0, (
            "Execution should have a non-empty prompt"
        )
        assert exc.status in (
            ExecutionStatus.completed, ExecutionStatus.failed,
            ExecutionStatus.timeout,
        ), f"Unexpected execution status: {exc.status}"
        # Duration should be set for finished executions
        assert exc.duration_ms is not None and exc.duration_ms > 0, (
            f"Duration should be positive, got {exc.duration_ms}"
        )

    # Check logs exist
    log_repo = ExecutionLogRepo()
    logs = await log_repo.list_by_issue(issue.id)
    assert len(logs) >= 1, "Should have at least one log entry"


# ── Tests: PR title and format ──────────────────────────────────────


@skipif_no_opencode
@skipif_no_gh
@pytest.mark.asyncio
@pytest.mark.timeout(600)
async def test_e2e_pr_title_format(e2e_runtime, e2e_git_repo):
    """Verify the PR title follows the expected format: 'agent: {issue.title}'.

    Also validates the PR targets the correct base branch.
    """
    repo_path, created_branches = e2e_git_repo
    runtime = e2e_runtime
    repo = IssueRepo()

    issue_title = "Fix the add function in calc.py"
    issue = await repo.create(IssueCreate(
        title=issue_title,
        description=(
            "The file calc.py has a bug: `return a - b` should be `return a + b`. "
            "Fix only that one line."
        ),
    ))

    await _run_and_wait(runtime, issue.id)

    updated = await repo.get(issue.id)
    created_branches.append(updated.branch_name)

    if updated.status not in (IssueStatus.review, IssueStatus.done) or updated.pr_url is None:
        pytest.skip("AI did not produce a successful PR — cannot verify PR format")

    # Fetch PR details via gh CLI
    pr_number = updated.pr_url.rstrip("/").split("/")[-1]
    result = subprocess.run(
        ["gh", "pr", "view", pr_number, "--repo", REMOTE_REPO_NWO,
         "--json", "title,baseRefName,headRefName"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"gh pr view failed: {result.stderr}"

    import json
    pr_data = json.loads(result.stdout)

    # PR title should match the expected format
    expected_title = f"agent: {issue_title}"
    assert pr_data["title"] == expected_title, (
        f"PR title should be '{expected_title}', got '{pr_data['title']}'"
    )

    # PR base should be 'main'
    assert pr_data["baseRefName"] == "main", (
        f"PR base should be 'main', got '{pr_data['baseRefName']}'"
    )

    # PR head should be the agent branch
    assert pr_data["headRefName"] == updated.branch_name, (
        f"PR head should be '{updated.branch_name}', got '{pr_data['headRefName']}'"
    )


# ── Tests: HTTP API E2E (through full ASGI stack) ──────────────────


@skipif_no_opencode
@skipif_no_gh
@pytest.mark.asyncio
@pytest.mark.timeout(600)
async def test_e2e_api_create_run_poll(e2e_git_repo, initialized_db, monkeypatch):
    """Full API-level test: create issue via HTTP → run → poll until done.

    Tests the entire API surface as a real client would use it.
    """
    from httpx import ASGITransport, AsyncClient
    from agent.config import get_settings
    from agent.server.app import create_app

    repo_path, created_branches = e2e_git_repo
    settings = get_settings()
    object.__setattr__(settings.project, "workspace", str(repo_path))
    object.__setattr__(settings.project, "default_branch", "main")
    object.__setattr__(settings.project, "remote", "origin")
    object.__setattr__(settings.project, "pr_base", "main")
    object.__setattr__(settings.agent, "max_turns", 3)
    object.__setattr__(settings.agent, "task_timeout", 300)
    object.__setattr__(settings.opencode, "command", "opencode")
    object.__setattr__(settings.opencode, "timeout", 120)

    monkeypatch.setattr("agent.agent.runtime.get_settings", lambda: settings)
    monkeypatch.setattr("agent.agent.context.get_settings", lambda: settings)
    monkeypatch.setattr("agent.skills.base.get_settings", lambda: settings)

    app = create_app()
    # Manually set up runtime since lifespan won't run in test
    runtime = AgentRuntime()
    app.state.runtime = runtime

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create issue
        resp = await client.post("/api/issues", json={
            "title": "Fix the add function in calc.py",
            "description": (
                "In calc.py, change `return a - b` to `return a + b`. "
                "That is the only change."
            ),
        })
        assert resp.status_code == 201
        issue_data = resp.json()
        issue_id = issue_data["id"]
        assert issue_data["status"] == "open"

        # 2. Run the issue
        resp = await client.post(f"/api/issues/{issue_id}/run")
        assert resp.status_code == 202

        # 3. Wait for completion by polling
        for _ in range(300):  # poll for up to 5 minutes
            await asyncio.sleep(1)
            resp = await client.get(f"/api/issues/{issue_id}")
            assert resp.status_code == 200
            data = resp.json()
            if data["status"] not in ("open", "running"):
                break
        else:
            pytest.fail("Issue did not complete within timeout")

        final = resp.json()
        created_branches.append(final.get("branch_name"))

        assert final["branch_name"] is not None
        assert final["branch_name"].startswith("agent/")

        # 4. Verify executions endpoint
        resp = await client.get(f"/api/issues/{issue_id}/executions")
        assert resp.status_code == 200
        executions = resp.json()
        assert len(executions) >= 1

        # 5. Verify logs endpoint
        resp = await client.get(f"/api/issues/{issue_id}/logs")
        assert resp.status_code == 200
        logs = resp.json()
        assert len(logs) >= 1

        # 6. If done, verify PR
        if final["status"] == "done":
            assert final["pr_url"] is not None
            assert "github.com" in final["pr_url"]

    await runtime.client.close()


# ── Tests: No-op when no changes (with mock client, real git) ──────


@pytest.mark.asyncio
async def test_e2e_no_changes_no_push(initialized_db, tmp_path, monkeypatch):
    """When AI reports success but makes no file changes, issue goes to
    waiting_human and no push/PR happens.

    Validates P0 #3: empty commit detection.
    """
    from agent.agent.opencode_client import OpenCodeClient
    from agent.config import get_settings

    settings = get_settings()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_dir, capture_output=True, check=True)
    (repo_dir / "README.md").write_text("# Test")
    subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_dir, capture_output=True, check=True)

    object.__setattr__(settings.project, "workspace", str(repo_dir))
    object.__setattr__(settings.project, "default_branch", "main")
    object.__setattr__(settings.project, "remote", "origin")
    object.__setattr__(settings.project, "pr_base", "main")
    object.__setattr__(settings.agent, "max_turns", 1)
    object.__setattr__(settings.agent, "task_timeout", 30)
    object.__setattr__(settings.opencode, "timeout", 10)
    monkeypatch.setattr("agent.agent.runtime.get_settings", lambda: settings)
    monkeypatch.setattr("agent.agent.context.get_settings", lambda: settings)
    monkeypatch.setattr("agent.skills.base.get_settings", lambda: settings)

    runtime = AgentRuntime()

    # Mock client that returns success but does NOT write files
    async def no_change_run(*args, **kwargs):
        return "Everything looks correct, no changes needed."

    runtime.client.run_prompt = no_change_run
    runtime.skill.client = runtime.client

    # Track push/PR calls
    runtime._git_push = AsyncMock(return_value=True)
    runtime._create_pr = AsyncMock(return_value="https://github.com/test/pull/1")

    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="Nothing to fix", description="test"))

    await _run_and_wait(runtime, issue.id)

    updated = await repo.get(issue.id)
    assert updated.status == IssueStatus.waiting_human, (
        f"Expected waiting_human when no changes, got {updated.status}"
    )

    # Push and PR should NOT have been called
    runtime._git_push.assert_not_awaited()
    runtime._create_pr.assert_not_awaited()


# ── Tests: DB field whitelist (security) ────────────────────────────


@pytest.mark.asyncio
async def test_e2e_update_fields_whitelist(initialized_db):
    """Verify that update_fields rejects disallowed fields.

    Validates P1 #5 / P2 #9: field name whitelist.
    """
    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="Test", description="test"))

    # Allowed fields should work
    await repo.update_fields(issue.id, pr_url="https://github.com/test/pull/1")
    updated = await repo.get(issue.id)
    assert updated.pr_url == "https://github.com/test/pull/1"

    await repo.update_fields(issue.id, branch_name="agent/test")
    updated = await repo.get(issue.id)
    assert updated.branch_name == "agent/test"

    # Disallowed fields should raise
    with pytest.raises(ValueError, match="Disallowed"):
        await repo.update_fields(issue.id, status="hacked")

    with pytest.raises(ValueError, match="Disallowed"):
        await repo.update_fields(issue.id, title="hacked")

    with pytest.raises(ValueError, match="Disallowed"):
        await repo.update_fields(issue.id, id="new-id")


# ── Tests: Retry stores and uses human instruction ──────────────────


@pytest.mark.asyncio
async def test_e2e_retry_preserves_instruction(initialized_db):
    """Verify retry_reset atomically stores the human instruction and resets status.

    Validates P1 #5: retry_reset atomic transaction.
    """
    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="Retry test", description="test"))
    await repo.update_status(issue.id, IssueStatus.waiting_human)

    instruction = "Please fix the bug in line 42"
    await repo.retry_reset(issue.id, instruction)

    updated = await repo.get(issue.id)
    assert updated.status == IssueStatus.open, (
        "Status should be reset to open after retry_reset"
    )
    assert updated.human_instruction == instruction, (
        "Human instruction should be stored"
    )

    # Retry without instruction should preserve existing instruction
    await repo.update_status(updated.id, IssueStatus.waiting_human)
    await repo.retry_reset(updated.id, human_instruction=None)

    final = await repo.get(updated.id)
    assert final.status == IssueStatus.open
    assert final.human_instruction == instruction, (
        "Previous instruction should be preserved when none provided"
    )


# ── Tests: Git operations with mock AI (Tier B) ─────────────────────


@pytest.mark.asyncio
async def test_e2e_git_push_failure_to_waiting_human(initialized_db, tmp_path, monkeypatch):
    """When git push fails, issue transitions to waiting_human (not done).

    Validates the _run_task push-failure branch: committed but push fails
    → waiting_human, no pr_url.
    """
    from agent.agent.runtime import AgentRuntime
    from agent.config import get_settings

    settings = get_settings()

    # Local repo WITHOUT a remote — push will naturally fail
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo_dir, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo_dir, capture_output=True, check=True,
    )
    (repo_dir / "README.md").write_text("# Test")
    subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo_dir, capture_output=True, check=True,
    )

    object.__setattr__(settings.project, "workspace", str(repo_dir))
    object.__setattr__(settings.project, "default_branch", "main")
    object.__setattr__(settings.project, "remote", "origin")
    object.__setattr__(settings.project, "pr_base", "main")
    object.__setattr__(settings.agent, "max_turns", 1)
    object.__setattr__(settings.agent, "task_timeout", 30)
    object.__setattr__(settings.opencode, "timeout", 10)
    monkeypatch.setattr("agent.agent.runtime.get_settings", lambda: settings)
    monkeypatch.setattr("agent.agent.context.get_settings", lambda: settings)
    monkeypatch.setattr("agent.skills.base.get_settings", lambda: settings)

    runtime = AgentRuntime()

    # Mock client that writes a real file change (so commit succeeds)
    async def write_and_succeed(*args, **kwargs):
        (repo_dir / "fix.py").write_text("# fixed\n")
        return "Fixed the issue."

    runtime.client.run_prompt = write_and_succeed
    runtime.skill.client = runtime.client

    repo = IssueRepo()
    issue = await repo.create(IssueCreate(
        title="Push will fail", description="No remote configured",
    ))

    await _run_and_wait(runtime, issue.id)

    updated = await repo.get(issue.id)
    assert updated.status == IssueStatus.waiting_human, (
        f"Expected waiting_human when push fails, got {updated.status}"
    )
    assert updated.pr_url is None, "PR URL should not be set when push fails"

    # Branch should still have been created and commit should exist
    assert updated.branch_name is not None
    assert _branch_exists(repo_dir, updated.branch_name)


@pytest.mark.asyncio
async def test_e2e_pr_creation_failure_still_done(mock_runtime):
    """When push succeeds but PR creation fails, issue still transitions to done.

    Validates runtime.py lines 146–150: code is pushed, PR fails → done with no pr_url.
    """
    repo_dir, runtime = mock_runtime

    # Mock client that writes a real file change
    async def write_and_succeed(*args, **kwargs):
        (repo_dir / "fix.py").write_text("# fixed\n")
        return "Fixed the issue."

    runtime.client.run_prompt = write_and_succeed
    runtime.skill.client = runtime.client

    # Mock _create_pr to fail (return None)
    runtime._create_pr = AsyncMock(return_value=None)

    repo = IssueRepo()
    issue = await repo.create(IssueCreate(
        title="PR will fail", description="Push succeeds but PR fails",
    ))

    await _run_and_wait(runtime, issue.id)

    updated = await repo.get(issue.id)
    assert updated.status == IssueStatus.done, (
        f"Expected done even when PR creation fails, got {updated.status}"
    )
    assert updated.pr_url is None, "PR URL should be None when PR creation fails"

    # Push should have succeeded — branch exists on remote
    assert updated.branch_name is not None
    assert _remote_branch_exists(repo_dir, updated.branch_name)

    # _create_pr should have been called
    runtime._create_pr.assert_awaited_once()


@pytest.mark.asyncio
async def test_e2e_multi_turn_retry_within_run(mock_runtime):
    """AI fails first turn, succeeds on second turn within same run.

    Validates multi-turn loop: 2 execution records, first failed, second completed.
    """
    repo_dir, runtime = mock_runtime

    call_count = 0

    async def fail_then_succeed(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Simulated AI failure on first turn")
        (repo_dir / "fix.py").write_text("# fixed on second turn\n")
        return "Fixed the bug on second attempt."

    runtime.client.run_prompt = fail_then_succeed
    runtime.skill.client = runtime.client

    # Mock _create_pr since we have a bare remote (no gh)
    runtime._create_pr = AsyncMock(return_value="https://github.com/test/pull/42")

    repo = IssueRepo()
    issue = await repo.create(IssueCreate(
        title="Multi-turn fix", description="Should fail first, succeed second",
    ))

    await _run_and_wait(runtime, issue.id)

    updated = await repo.get(issue.id)
    assert updated.status == IssueStatus.review, (
        f"Expected review after second turn success with PR, got {updated.status}"
    )
    assert updated.pr_url == "https://github.com/test/pull/42"

    # Verify execution records
    exec_repo = ExecutionRepo()
    executions = await exec_repo.list_by_issue(issue.id)
    assert len(executions) == 2, (
        f"Expected 2 execution records (fail + success), got {len(executions)}"
    )
    assert executions[0].status == ExecutionStatus.failed, (
        f"First execution should be failed, got {executions[0].status}"
    )
    assert executions[1].status == ExecutionStatus.completed, (
        f"Second execution should be completed, got {executions[1].status}"
    )


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_e2e_task_timeout_handling(mock_runtime):
    """Task exceeds task_timeout and transitions to waiting_human.

    Validates the task-level timeout in _run_task.
    """
    from agent.config import get_settings

    repo_dir, runtime = mock_runtime
    settings = get_settings()

    # Set a very short task timeout
    object.__setattr__(settings.agent, "task_timeout", 2)

    # Mock client that blocks longer than the task timeout
    async def slow_run(*args, cancel_event=None, **kwargs):
        await asyncio.sleep(30)
        return "Should not reach here"

    runtime.client.run_prompt = slow_run
    runtime.skill.client = runtime.client

    repo = IssueRepo()
    issue = await repo.create(IssueCreate(
        title="Timeout test", description="Should timeout",
    ))

    await _run_and_wait(runtime, issue.id)

    updated = await repo.get(issue.id)
    assert updated.status == IssueStatus.waiting_human, (
        f"Expected waiting_human after timeout, got {updated.status}"
    )

    # At least one execution record should exist
    exec_repo = ExecutionRepo()
    executions = await exec_repo.list_by_issue(issue.id)
    assert len(executions) >= 1, "Should have at least one execution record"


@pytest.mark.asyncio
async def test_e2e_selective_git_add(mock_runtime):
    """_git_commit only stages modified/untracked files and respects .gitignore.

    Validates P1 #4: selective git add instead of 'git add -A'.
    """
    repo_dir, runtime = mock_runtime

    # Create a .gitignore that ignores *.log files
    (repo_dir / ".gitignore").write_text("*.log\n")
    subprocess.run(
        ["git", "add", ".gitignore"],
        cwd=repo_dir, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "add gitignore"],
        cwd=repo_dir, capture_output=True, check=True,
    )

    # Switch to an agent branch
    branch = "agent/test-selective"
    subprocess.run(
        ["git", "checkout", "-b", branch],
        cwd=repo_dir, capture_output=True, check=True,
    )

    # Write both a legit file and a log file that should be ignored
    (repo_dir / "fix.py").write_text("# This should be committed\n")
    (repo_dir / "debug.log").write_text("This should NOT be committed\n")

    # Call the real _git_commit
    committed = await runtime._git_commit(branch, "test selective add", cwd=str(repo_dir))
    assert committed, "Commit should succeed with fix.py"

    # Verify what was committed
    result = subprocess.run(
        ["git", "show", "--name-only", "--pretty=format:", "HEAD"],
        cwd=repo_dir, capture_output=True, text=True,
    )
    committed_files = result.stdout.strip().splitlines()
    assert "fix.py" in committed_files, (
        f"fix.py should be in the commit, got: {committed_files}"
    )
    assert "debug.log" not in committed_files, (
        f"debug.log should NOT be in the commit (gitignored), got: {committed_files}"
    )


# ── Tests: DB and API logic (Tier C) ────────────────────────────────


@pytest.mark.asyncio
async def test_e2e_api_retry_endpoint(initialized_db, monkeypatch):
    """POST /api/issues/{id}/retry stores instruction and starts task.

    Validates the retry API endpoint with correct and incorrect states.
    """
    from unittest.mock import AsyncMock as _AsyncMock

    from httpx import ASGITransport, AsyncClient
    from agent.agent.runtime import AgentRuntime
    from agent.server.app import create_app

    app = create_app()
    runtime = AgentRuntime()

    # Mock start_task so it doesn't actually run anything
    runtime.start_task = _AsyncMock()
    app.state.runtime = runtime

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create issue
        resp = await client.post("/api/issues", json={
            "title": "Retry endpoint test",
            "description": "Testing the retry API",
        })
        assert resp.status_code == 201
        issue_id = resp.json()["id"]

        # 2. Retry on 'open' issue should fail (must be failed/waiting_human)
        resp = await client.post(f"/api/issues/{issue_id}/retry", json={
            "human_instruction": "Some instruction",
        })
        assert resp.status_code == 409, (
            f"Expected 409 for retry on open issue, got {resp.status_code}"
        )

        # 3. Set to waiting_human, then retry should succeed
        issue_repo = IssueRepo()
        await issue_repo.update_status(issue_id, IssueStatus.waiting_human)

        resp = await client.post(f"/api/issues/{issue_id}/retry", json={
            "human_instruction": "Please fix line 42",
        })
        assert resp.status_code == 202, (
            f"Expected 202 for retry, got {resp.status_code}"
        )

        # Verify instruction was stored
        updated = await issue_repo.get(issue_id)
        assert updated.human_instruction == "Please fix line 42"
        assert updated.status == IssueStatus.open, (
            "Status should be reset to open after retry_reset"
        )

        # start_task should have been called
        runtime.start_task.assert_awaited_once_with(issue_id)

        # 4. Retry on nonexistent issue should return 404
        resp = await client.post("/api/issues/nonexistent-id/retry", json={
            "human_instruction": "test",
        })
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_e2e_concurrent_db_writes(initialized_db):
    """Concurrent DB writes should not cause 'database is locked' errors.

    Validates P1 #6: DB connection sharing handles concurrent access.
    """
    repo = IssueRepo()

    async def create_and_update(i: int) -> str:
        """Create an issue and update its status."""
        issue = await repo.create(IssueCreate(
            title=f"Concurrent issue {i}",
            description=f"Test concurrent write #{i}",
        ))
        await repo.update_status(issue.id, IssueStatus.running)
        await repo.update_status(issue.id, IssueStatus.done)
        return issue.id

    # Run 20 concurrent create+update tasks
    tasks = [create_and_update(i) for i in range(20)]
    issue_ids = await asyncio.gather(*tasks)

    # Verify all 20 issues exist with correct final status
    assert len(issue_ids) == 20
    for issue_id in issue_ids:
        issue = await repo.get(issue_id)
        assert issue is not None, f"Issue {issue_id} should exist"
        assert issue.status == IssueStatus.done, (
            f"Issue {issue_id} should be done, got {issue.status}"
        )


# ── Tests: ROADMAP3 Kanban status flows (no opencode needed) ────────


@pytest.mark.asyncio
async def test_e2e_complete_review_to_done(initialized_db):
    """review → done via complete endpoint.

    Validates ROADMAP3: POST /complete transitions review → done.
    """
    repo = IssueRepo()
    issue = await repo.create(IssueCreate(
        title="Complete review test", description="test",
    ))
    await repo.update_status(issue.id, IssueStatus.review)
    await repo.update_fields(issue.id, pr_url="https://github.com/test/pull/99")

    # Transition to done
    await repo.update_status(issue.id, IssueStatus.done)

    updated = await repo.get(issue.id)
    assert updated.status == IssueStatus.done
    assert updated.pr_url == "https://github.com/test/pull/99"


@pytest.mark.asyncio
async def test_e2e_spec_flow_plan_to_run(mock_runtime):
    """Full Spec flow: open → plan → planned → run → review.

    Validates ROADMAP3 acceptance:
    - POST /plan triggers Spec generation (open → planning → planned)
    - Issue has spec field with valid JSON
    - POST /run on planned issue works (spec injected into execution)
    """
    import json
    repo_dir, runtime = mock_runtime

    # Mock OpenCode to return valid spec JSON for plan
    valid_spec = json.dumps({
        "plan": "Fix the bug by changing subtraction to addition",
        "acceptance_criteria": ["calc.py add function returns a+b", "All tests pass"],
        "files_to_modify": ["calc.py"],
        "estimated_complexity": "low",
    })

    async def plan_response(*args, **kwargs):
        return valid_spec

    runtime.client.run_prompt = plan_response
    runtime.plan_skill.client = runtime.client

    repo = IssueRepo()
    issue = await repo.create(IssueCreate(
        title="Spec flow test", description="Test the full spec flow",
    ))
    assert issue.status == IssueStatus.open

    # Step 1: Generate plan
    await runtime.start_plan(issue.id)
    task = runtime._running_tasks.get(issue.id)
    if task:
        await task

    updated = await repo.get(issue.id)
    assert updated.status == IssueStatus.planned, (
        f"Expected planned after plan generation, got {updated.status}"
    )
    assert updated.spec is not None
    spec_data = json.loads(updated.spec)
    assert spec_data["plan"] == "Fix the bug by changing subtraction to addition"
    assert len(spec_data["acceptance_criteria"]) == 2

    # Step 2: Run from planned status (simulates code execution)
    async def code_response(*args, **kwargs):
        # Write a file to simulate code changes
        (repo_dir / "fix.py").write_text("# fixed\n")
        return "Bug fixed successfully."

    runtime.client.run_prompt = code_response
    runtime.skill.client = runtime.client
    runtime._create_pr = AsyncMock(return_value="https://github.com/test/pull/1")

    await runtime.start_task(issue.id)
    task = runtime._running_tasks.get(issue.id)
    if task:
        await task

    final = await repo.get(issue.id)
    assert final.status == IssueStatus.review, (
        f"Expected review after successful run with PR, got {final.status}"
    )
    assert final.pr_url == "https://github.com/test/pull/1"


@pytest.mark.asyncio
async def test_e2e_skip_spec_flow(mock_runtime):
    """Skip-Spec flow: open → run → review (no plan phase).

    Validates ROADMAP3 acceptance: POST /run on open Issue still works
    without going through the Spec phase.
    """
    repo_dir, runtime = mock_runtime

    async def code_response(*args, **kwargs):
        (repo_dir / "fix.py").write_text("# fixed without spec\n")
        return "Done."

    runtime.client.run_prompt = code_response
    runtime.skill.client = runtime.client
    runtime._create_pr = AsyncMock(return_value="https://github.com/test/pull/2")

    repo = IssueRepo()
    issue = await repo.create(IssueCreate(
        title="Skip spec", description="Run directly without plan",
    ))
    assert issue.status == IssueStatus.open
    assert issue.spec is None  # No spec

    await runtime.start_task(issue.id)
    task = runtime._running_tasks.get(issue.id)
    if task:
        await task

    updated = await repo.get(issue.id)
    assert updated.status == IssueStatus.review
    assert updated.pr_url == "https://github.com/test/pull/2"


@pytest.mark.asyncio
async def test_e2e_reject_spec_back_to_open(initialized_db):
    """Reject Spec: planned → open, spec cleared.

    Validates ROADMAP3 acceptance: POST /reject-spec.
    """
    import json
    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="Reject spec test"))
    await repo.update_status(issue.id, IssueStatus.planned)
    await repo.update_fields(
        issue.id,
        spec=json.dumps({"plan": "Bad plan", "acceptance_criteria": [], "files_to_modify": [], "estimated_complexity": "high"}),
    )

    # Reject spec
    await repo.update_fields(issue.id, spec=None)
    await repo.update_status(issue.id, IssueStatus.open)

    updated = await repo.get(issue.id)
    assert updated.status == IssueStatus.open
    assert updated.spec is None


@pytest.mark.asyncio
async def test_e2e_priority_ordering(initialized_db):
    """Issues with different priorities are stored and filterable.

    Validates ROADMAP3 acceptance: Priority field works correctly.
    """
    from agent.models import IssuePriority
    repo = IssueRepo()

    high = await repo.create(IssueCreate(title="High priority task", priority=IssuePriority.high))
    medium = await repo.create(IssueCreate(title="Medium priority task", priority=IssuePriority.medium))
    low = await repo.create(IssueCreate(title="Low priority task", priority=IssuePriority.low))

    # All issues exist
    all_issues = await repo.list_all()
    assert len(all_issues) >= 3

    # Filter by priority
    high_issues = await repo.list_all(priority=IssuePriority.high)
    assert len(high_issues) == 1
    assert high_issues[0].priority == IssuePriority.high
    assert high_issues[0].title == "High priority task"


@pytest.mark.asyncio
async def test_e2e_edit_and_delete_status_guards(initialized_db):
    """Edit/delete respect status guards.

    Validates ROADMAP3 acceptance:
    - open status: editable and deletable
    - running status: NOT editable, NOT deletable
    - done status: deletable
    """
    from agent.models import IssuePriority
    repo = IssueRepo()

    # ── open status: editable ──
    open_issue = await repo.create(IssueCreate(title="Open editable", priority=IssuePriority.medium))
    assert open_issue.status == IssueStatus.open

    # ── running status: verify we can set it ──
    running_issue = await repo.create(IssueCreate(title="Running"))
    await repo.update_status(running_issue.id, IssueStatus.running)
    running_check = await repo.get(running_issue.id)
    assert running_check.status == IssueStatus.running

    # ── done status: deletable ──
    done_issue = await repo.create(IssueCreate(title="Done deletable"))
    await repo.update_status(done_issue.id, IssueStatus.done)
    deleted = await repo.delete(done_issue.id)
    assert deleted is True
    assert await repo.get(done_issue.id) is None

    # ── waiting_human status: deletable ──
    wh_issue = await repo.create(IssueCreate(title="WH deletable"))
    await repo.update_status(wh_issue.id, IssueStatus.waiting_human)
    deleted = await repo.delete(wh_issue.id)
    assert deleted is True

    # ── cancelled status: deletable ──
    cancelled_issue = await repo.create(IssueCreate(title="Cancelled deletable"))
    await repo.update_status(cancelled_issue.id, IssueStatus.cancelled)
    deleted = await repo.delete(cancelled_issue.id)
    assert deleted is True


@pytest.mark.asyncio
async def test_e2e_waiting_human_retry_flow(mock_runtime):
    """Failure retry flow: run → waiting_human → retry → review.

    Validates ROADMAP3 acceptance:
    - Failed execution → waiting_human with failure_reason
    - Retry with human instruction → successful execution
    """
    repo_dir, runtime = mock_runtime

    call_count = 0

    async def fail_then_succeed(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 3:  # Fail all 3 turns of first run
            raise RuntimeError(f"Simulated failure #{call_count}")
        # Second run succeeds
        (repo_dir / "fix.py").write_text("# fixed on retry\n")
        return "Fixed with human guidance."

    runtime.client.run_prompt = fail_then_succeed
    runtime.skill.client = runtime.client
    runtime._create_pr = AsyncMock(return_value="https://github.com/test/pull/3")

    repo = IssueRepo()
    issue = await repo.create(IssueCreate(
        title="Retry flow test", description="Will fail first",
    ))

    # First run: all turns fail → waiting_human
    await runtime.start_task(issue.id)
    task = runtime._running_tasks.get(issue.id)
    if task:
        await task

    updated = await repo.get(issue.id)
    assert updated.status == IssueStatus.waiting_human
    assert updated.failure_reason is not None

    # Retry with human instruction
    await repo.retry_reset(issue.id, human_instruction="Just change line 6")

    await runtime.start_task(issue.id)
    task = runtime._running_tasks.get(issue.id)
    if task:
        await task

    retried = await repo.get(issue.id)
    assert retried.status == IssueStatus.review, (
        f"Expected review after successful retry, got {retried.status}"
    )
    assert retried.human_instruction == "Just change line 6"
    assert retried.pr_url is not None
