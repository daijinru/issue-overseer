"""Tests for database initialization and basic repo operations."""

from __future__ import annotations

import json
import uuid

import pytest

from mango.db.connection import init_db, get_db_connection
from mango.db.repos import ExecutionLogRepo, ExecutionRepo, ExecutionStepRepo, IssueRepo
from mango.models import ExecutionStatus, IssueCreate, IssuePriority, IssueStatus, LogLevel


@pytest.mark.asyncio
async def test_tables_created(initialized_db):
    """After init_db(), all 3 application tables should exist."""
    async with get_db_connection() as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        rows = await cursor.fetchall()
        table_names = {row[0] for row in rows}

    assert "issues" in table_names
    assert "executions" in table_names
    assert "execution_logs" in table_names


@pytest.mark.asyncio
async def test_migrations_table_exists(initialized_db):
    """The _migrations meta-table should be created."""
    async with get_db_connection() as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='_migrations'"
        )
        row = await cursor.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_issue_create_and_get(initialized_db):
    """Round-trip: create an Issue via repo, then read it back."""
    repo = IssueRepo()
    created = await repo.create(
        IssueCreate(title="Fix login test", description="test_login.py fails")
    )

    assert created.id is not None
    assert created.title == "Fix login test"
    assert created.description == "test_login.py fails"
    assert created.status.value == "open"

    fetched = await repo.get(created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.title == "Fix login test"


@pytest.mark.asyncio
async def test_issue_get_nonexistent(initialized_db):
    """Getting a non-existent Issue should return None."""
    repo = IssueRepo()
    result = await repo.get("nonexistent-id")
    assert result is None


@pytest.mark.asyncio
async def test_issue_update_fields(initialized_db):
    """update_fields should update specific fields."""
    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="Update me", description="desc"))
    await repo.update_fields(issue.id, branch_name="agent/test", human_instruction="try again")
    updated = await repo.get(issue.id)
    assert updated.branch_name == "agent/test"
    assert updated.human_instruction == "try again"


@pytest.mark.asyncio
async def test_execution_create_and_list(initialized_db):
    """Create an Execution and list by issue."""
    issue_repo = IssueRepo()
    issue = await issue_repo.create(IssueCreate(title="Exec test"))
    exec_repo = ExecutionRepo()
    execution_id = str(uuid.uuid4())
    execution = await exec_repo.create(
        execution_id=execution_id, issue_id=issue.id,
        turn_number=1, attempt_number=1, prompt="test prompt",
    )
    assert execution.id == execution_id
    assert execution.issue_id == issue.id

    executions = await exec_repo.list_by_issue(issue.id)
    assert len(executions) == 1
    assert executions[0].id == execution_id


@pytest.mark.asyncio
async def test_execution_finish_updates_status(initialized_db):
    """finish() should update execution status and result."""
    issue_repo = IssueRepo()
    issue = await issue_repo.create(IssueCreate(title="Finish test"))
    exec_repo = ExecutionRepo()
    execution_id = str(uuid.uuid4())
    await exec_repo.create(
        execution_id=execution_id, issue_id=issue.id,
        turn_number=1, attempt_number=1,
    )
    await exec_repo.finish(
        execution_id, status=ExecutionStatus.completed,
        result="Success!", duration_ms=1234,
    )
    executions = await exec_repo.list_by_issue(issue.id)
    assert executions[0].status == ExecutionStatus.completed
    assert executions[0].result == "Success!"
    assert executions[0].duration_ms == 1234


@pytest.mark.asyncio
async def test_execution_log_append_and_list(initialized_db):
    """append() and list_by_execution() should work."""
    issue_repo = IssueRepo()
    issue = await issue_repo.create(IssueCreate(title="Log test"))
    exec_repo = ExecutionRepo()
    execution_id = str(uuid.uuid4())
    await exec_repo.create(
        execution_id=execution_id, issue_id=issue.id,
        turn_number=1, attempt_number=1,
    )
    log_repo = ExecutionLogRepo()
    await log_repo.append(execution_id, LogLevel.info, "test message")
    await log_repo.append(execution_id, LogLevel.error, "error message")

    logs = await log_repo.list_by_execution(execution_id)
    assert len(logs) == 2
    assert logs[0].message == "test message"
    assert logs[1].level == LogLevel.error


@pytest.mark.asyncio
async def test_update_fields_rejects_invalid_field(initialized_db):
    """update_fields should reject field names not in the whitelist."""
    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="Whitelist test", description="desc"))
    with pytest.raises(ValueError, match="Disallowed field"):
        await repo.update_fields(issue.id, status="hacked")


@pytest.mark.asyncio
async def test_update_fields_pr_url(initialized_db):
    """update_fields should accept pr_url (in the whitelist)."""
    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="PR URL test", description="desc"))
    await repo.update_fields(issue.id, pr_url="https://github.com/test/repo/pull/1")
    updated = await repo.get(issue.id)
    assert updated.pr_url == "https://github.com/test/repo/pull/1"


# ── Migration 006 + new fields tests ──


@pytest.mark.asyncio
async def test_execution_steps_table_exists(initialized_db):
    """After init_db(), execution_steps table should exist."""
    async with get_db_connection() as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='execution_steps'"
        )
        row = await cursor.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_issue_has_priority_field(initialized_db):
    """Issues should have a priority field with default 'medium'."""
    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="Priority default"))
    assert issue.priority == IssuePriority.medium


@pytest.mark.asyncio
async def test_issue_create_with_priority(initialized_db):
    """Issues can be created with a specific priority."""
    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="High priority", priority=IssuePriority.high))
    assert issue.priority == IssuePriority.high

    fetched = await repo.get(issue.id)
    assert fetched.priority == IssuePriority.high


@pytest.mark.asyncio
async def test_issue_has_spec_field(initialized_db):
    """Issues should have a spec field, initially None."""
    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="Spec test"))
    assert issue.spec is None


@pytest.mark.asyncio
async def test_issue_update_spec(initialized_db):
    """spec field can be updated via update_fields."""
    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="Spec update"))
    spec_data = json.dumps({
        "plan": "Test plan",
        "acceptance_criteria": ["Criterion 1"],
        "files_to_modify": ["file.py"],
        "estimated_complexity": "low",
    })
    await repo.update_fields(issue.id, spec=spec_data)
    updated = await repo.get(issue.id)
    assert updated.spec == spec_data
    parsed = json.loads(updated.spec)
    assert parsed["plan"] == "Test plan"


@pytest.mark.asyncio
async def test_issue_update_priority(initialized_db):
    """priority field can be updated via update_fields."""
    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="Priority update"))
    assert issue.priority == IssuePriority.medium

    await repo.update_fields(issue.id, priority="high")
    updated = await repo.get(issue.id)
    assert updated.priority == IssuePriority.high


@pytest.mark.asyncio
async def test_issue_status_new_values(initialized_db):
    """New status values (planning, planned, review) should be storable."""
    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="Status test"))

    for status in (IssueStatus.planning, IssueStatus.planned, IssueStatus.review):
        await repo.update_status(issue.id, status)
        updated = await repo.get(issue.id)
        assert updated.status == status


@pytest.mark.asyncio
async def test_issue_no_failed_status(initialized_db):
    """'failed' is no longer a valid IssueStatus (removed in favor of waiting_human)."""
    # Verify 'failed' is not in the IssueStatus enum
    status_values = [s.value for s in IssueStatus]
    assert "failed" not in status_values
    assert "waiting_human" in status_values


@pytest.mark.asyncio
async def test_issue_list_filter_by_priority(initialized_db):
    """list_all should support priority filtering."""
    repo = IssueRepo()
    await repo.create(IssueCreate(title="High", priority=IssuePriority.high))
    await repo.create(IssueCreate(title="Low", priority=IssuePriority.low))
    await repo.create(IssueCreate(title="Medium"))

    high_issues = await repo.list_all(priority=IssuePriority.high)
    assert len(high_issues) == 1
    assert high_issues[0].title == "High"


@pytest.mark.asyncio
async def test_issue_list_filter_by_status_and_priority(initialized_db):
    """list_all should support combined status + priority filtering."""
    repo = IssueRepo()
    issue1 = await repo.create(IssueCreate(title="Open High", priority=IssuePriority.high))
    issue2 = await repo.create(IssueCreate(title="Open Low", priority=IssuePriority.low))
    issue3 = await repo.create(IssueCreate(title="Done High", priority=IssuePriority.high))
    await repo.update_status(issue3.id, IssueStatus.done)

    results = await repo.list_all(status=IssueStatus.open, priority=IssuePriority.high)
    assert len(results) == 1
    assert results[0].title == "Open High"


@pytest.mark.asyncio
async def test_issue_delete_cascades(initialized_db):
    """Deleting an issue should also delete associated executions/logs/steps."""
    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="Cascade delete"))

    # Create execution
    exec_repo = ExecutionRepo()
    exec_id = str(uuid.uuid4())
    await exec_repo.create(
        execution_id=exec_id, issue_id=issue.id,
        turn_number=1, attempt_number=1,
    )

    # Create log
    log_repo = ExecutionLogRepo()
    await log_repo.append(exec_id, LogLevel.info, "test log")

    # Create step
    step_repo = ExecutionStepRepo()
    await step_repo.create(exec_id, "tool_use", tool="bash", summary="ls")

    # Delete issue
    deleted = await repo.delete(issue.id)
    assert deleted is True

    # Verify cascaded deletions
    assert await repo.get(issue.id) is None
    assert await exec_repo.list_by_issue(issue.id) == []
    assert await log_repo.list_by_issue(issue.id) == []
    assert await step_repo.list_by_issue(issue.id) == []


@pytest.mark.asyncio
async def test_issue_retry_reset(initialized_db):
    """retry_reset should clear failure_reason and reset status to open."""
    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="Retry reset"))
    await repo.update_status(issue.id, IssueStatus.waiting_human)
    await repo.update_fields(issue.id, failure_reason="Something broke")

    await repo.retry_reset(issue.id, human_instruction="Try again")

    updated = await repo.get(issue.id)
    assert updated.status == IssueStatus.open
    assert updated.human_instruction == "Try again"
    assert updated.failure_reason is None


@pytest.mark.asyncio
async def test_issue_failure_reason_field(initialized_db):
    """failure_reason field should be stored and retrievable."""
    repo = IssueRepo()
    issue = await repo.create(IssueCreate(title="Failure test"))
    await repo.update_fields(issue.id, failure_reason="AI execution failed: timeout")
    updated = await repo.get(issue.id)
    assert updated.failure_reason == "AI execution failed: timeout"


@pytest.mark.asyncio
async def test_execution_step_create_and_list(initialized_db):
    """ExecutionStepRepo CRUD operations."""
    issue_repo = IssueRepo()
    issue = await issue_repo.create(IssueCreate(title="Step test"))
    exec_repo = ExecutionRepo()
    exec_id = str(uuid.uuid4())
    await exec_repo.create(
        execution_id=exec_id, issue_id=issue.id,
        turn_number=1, attempt_number=1,
    )

    step_repo = ExecutionStepRepo()
    await step_repo.create(exec_id, "tool_use", tool="bash", target="ls -la", summary="List files")
    await step_repo.create(exec_id, "text", summary="Analyzing code...")

    steps = await step_repo.list_by_execution(exec_id)
    assert len(steps) == 2
    assert steps[0].tool == "bash"
    assert steps[1].step_type.value == "text"

    # Also test list_by_issue
    issue_steps = await step_repo.list_by_issue(issue.id)
    assert len(issue_steps) == 2
