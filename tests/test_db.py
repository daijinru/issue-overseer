"""Tests for database initialization and basic repo operations."""

from __future__ import annotations

import uuid

import pytest

from mango.db.connection import init_db, get_db_connection
from mango.db.repos import ExecutionLogRepo, ExecutionRepo, IssueRepo
from mango.models import ExecutionStatus, IssueCreate, LogLevel


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
