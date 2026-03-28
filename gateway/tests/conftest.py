"""Shared test fixtures for Mango Gateway tests."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

# Override the DB path before importing any gateway modules
_test_db_dir = tempfile.mkdtemp()
os.environ.setdefault("DATABASE__PATH", str(Path(_test_db_dir) / "test_gateway.db"))

from mango_gateway.config import Settings
from mango_gateway.db.connection import init_db, close_shared_connection
from mango_gateway.service.gateway import GatewayService
from mango_gateway.service.runtime_client import RuntimeClient


@pytest.fixture
def settings() -> Settings:
    """Return test settings with a temporary DB path."""
    return Settings(
        database={"path": str(Path(_test_db_dir) / "test_gateway.db")},
        runtime={"url": "http://localhost:18800", "timeout": 5},
        session={"timeout_hours": 24, "cleanup_interval_minutes": 60},
        gateway={"max_wait_timeout": 30},
    )


@pytest.fixture
async def db():
    """Initialize and yield the test database, then clean up."""
    await init_db()
    yield
    await close_shared_connection()


@pytest.fixture
def mock_runtime() -> AsyncMock:
    """Return a mocked RuntimeClient."""
    client = AsyncMock(spec=RuntimeClient)
    client.health_check.return_value = True
    client.create_issue.return_value = {
        "id": "test-issue-001",
        "title": "Test issue",
        "description": "Test description",
        "status": "open",
        "priority": "medium",
    }
    client.run_issue.return_value = {
        "message": "Task started",
        "issue_id": "test-issue-001",
    }
    client.get_issue.return_value = {
        "id": "test-issue-001",
        "title": "Test issue",
        "description": "Test description",
        "status": "running",
        "priority": "medium",
        "pr_url": None,
        "failure_reason": None,
    }
    client.retry_issue.return_value = {
        "message": "Retry started",
        "issue_id": "test-issue-001",
    }
    client.get_issue_executions.return_value = []
    return client


@pytest.fixture
def gateway_service(mock_runtime: AsyncMock, settings: Settings, db) -> GatewayService:
    """Return a GatewayService with a mocked RuntimeClient."""
    return GatewayService(runtime_client=mock_runtime, settings=settings)
