"""Tests for database initialization and basic repo operations."""

from __future__ import annotations

import pytest

from mango.db.connection import init_db, get_db_connection
from mango.db.repos import IssueRepo
from mango.models import IssueCreate


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
