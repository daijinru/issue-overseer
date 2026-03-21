"""End-to-end integration test — real opencode, real git, real DB.

Validates the ROADMAP Phase 1 acceptance criteria:
  创建 Issue → AI 执行 → (可能失败) → retry with instruction → 完成 → 代码提交到分支

Requires: a working ``opencode`` binary on PATH with a configured provider.
Run with: uv run pytest tests/test_e2e.py -v -s -m e2e

Test fixture source files live in tests/fixtures/e2e_repo/:
  - calc.py       — buggy calculator (return a - b)
  - test_calc.py  — tests that fail against the bug
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from mango.agent.runtime import AgentRuntime
from mango.db.repos import ExecutionLogRepo, ExecutionRepo, IssueRepo
from mango.models import IssueCreate, IssueStatus

pytestmark = pytest.mark.e2e

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "e2e_repo"


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


skipif_no_opencode = pytest.mark.skipif(
    not _opencode_available(),
    reason="opencode CLI not available",
)


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture()
def e2e_git_repo(tmp_path):
    """Copy fixture files into a fresh git repo for testing."""
    repo = tmp_path / "e2e_repo"
    shutil.copytree(FIXTURES_DIR, repo)

    # Init git
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo, capture_output=True, check=True,
    )

    # Initial commit
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial: buggy calc"],
        cwd=repo, capture_output=True, check=True,
    )

    # Verify the test actually fails
    result = subprocess.run(
        ["python", "-m", "pytest", "test_calc.py", "-q"],
        cwd=repo, capture_output=True,
    )
    assert result.returncode != 0, "Test should fail with the buggy code"

    return repo


@pytest.fixture()
async def e2e_runtime(initialized_db, e2e_git_repo, monkeypatch):
    """AgentRuntime wired to the real opencode CLI and a test git repo."""
    from mango.config import get_settings

    settings = get_settings()

    object.__setattr__(settings.project, "repo_path", str(e2e_git_repo))
    object.__setattr__(settings.project, "default_branch", "main")
    object.__setattr__(settings.agent, "max_turns", 3)
    object.__setattr__(settings.agent, "task_timeout", 300)
    object.__setattr__(settings.opencode, "command", "opencode")
    object.__setattr__(settings.opencode, "timeout", 120)

    monkeypatch.setattr("mango.agent.runtime.get_settings", lambda: settings)
    monkeypatch.setattr("mango.agent.context.get_settings", lambda: settings)
    monkeypatch.setattr("mango.skills.base.get_settings", lambda: settings)

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
    """Check if a git branch exists."""
    result = subprocess.run(
        ["git", "branch", "--list", branch_name],
        cwd=repo_path, capture_output=True, text=True,
    )
    return branch_name in result.stdout


# ── Tests ───────────────────────────────────────────────────────────


@skipif_no_opencode
@pytest.mark.asyncio
async def test_e2e_fix_bug_full_lifecycle(e2e_runtime, e2e_git_repo):
    """Full Phase 1 acceptance test:
    Create Issue → AI executes → verify state → (retry if needed) → done.

    This test uses a real opencode process to fix a simple bug:
    calc.py has `return a - b` instead of `return a + b`.

    The test validates:
    1. Issue status transitions (open → running → done/waiting_human)
    2. Git branch is created
    3. Execution records exist in DB
    4. If first attempt fails, retry with instruction works
    5. Code is actually fixed and committed
    """
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
    await runtime.start_task(issue.id)

    task = runtime._running_tasks.get(issue.id)
    assert task is not None, "Task should be running"
    await task

    updated = await repo.get(issue.id)

    # Branch should be created regardless of success/failure
    assert updated.branch_name is not None
    assert updated.branch_name.startswith("agent/")
    assert _branch_exists(e2e_git_repo, updated.branch_name)

    # Execution records should exist
    exec_repo = ExecutionRepo()
    executions = await exec_repo.list_by_issue(issue.id)
    assert len(executions) >= 1, "At least one execution record"

    log_repo = ExecutionLogRepo()
    logs = await log_repo.list_by_issue(issue.id)
    assert len(logs) >= 1, "At least one log entry"

    # ── Step 3: Check if AI fixed it, otherwise retry ──
    if updated.status == IssueStatus.done:
        # AI succeeded on first try — check the fix
        subprocess.run(
            ["git", "checkout", updated.branch_name],
            cwd=e2e_git_repo, capture_output=True, check=True,
        )
        if _tests_pass(e2e_git_repo):
            # Perfect — first attempt fixed the bug
            assert _get_branch_commits(e2e_git_repo, updated.branch_name)
            return

        # AI claimed success but didn't actually fix — that's OK for this test,
        # the point is the Runtime lifecycle worked. Fall through to retry.

    # ── Step 4: Retry with human instruction ──
    # Reset to waiting_human if not already
    if updated.status == IssueStatus.done:
        await repo.update_status(issue.id, IssueStatus.waiting_human)

    # Switch back to main so the agent branch can be recreated
    subprocess.run(
        ["git", "checkout", "main"],
        cwd=e2e_git_repo, capture_output=True,
    )
    # Delete the old branch so checkout -b doesn't conflict
    subprocess.run(
        ["git", "branch", "-D", updated.branch_name],
        cwd=e2e_git_repo, capture_output=True,
    )

    await repo.update_fields(
        issue.id,
        human_instruction=(
            "The fix is very simple: in calc.py line 6, change `return a - b` "
            "to `return a + b`. That is the ONLY change needed. "
            "Do NOT modify test_calc.py."
        ),
    )
    await repo.update_status(issue.id, IssueStatus.open)
    await runtime.start_task(issue.id)

    task = runtime._running_tasks.get(issue.id)
    assert task is not None
    await task

    retried = await repo.get(issue.id)

    # After retry, should be done
    assert retried.status == IssueStatus.done, (
        f"Expected done after retry, got {retried.status}"
    )

    # Verify the fix
    subprocess.run(
        ["git", "checkout", retried.branch_name],
        cwd=e2e_git_repo, capture_output=True, check=True,
    )
    assert _tests_pass(e2e_git_repo), (
        "Tests should pass after retry with explicit instruction"
    )

    # Commit should exist on branch
    assert _get_branch_commits(e2e_git_repo, retried.branch_name), (
        "At least one commit should exist on the agent branch"
    )

    # More execution records after retry
    all_executions = await exec_repo.list_by_issue(issue.id)
    assert len(all_executions) >= 2, (
        "Should have execution records from both attempts"
    )
