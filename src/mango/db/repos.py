"""Database repository classes for issues, executions, and logs."""

from __future__ import annotations

import uuid

from mango.db.connection import get_db_connection
from mango.models import (
    ExecutionLog,
    Issue,
    IssueCreate,
    IssueStatus,
    LogLevel,
)


class IssueRepo:
    """Repository for the ``issues`` table."""

    async def create(self, data: IssueCreate) -> Issue:
        issue_id = str(uuid.uuid4())
        async with get_db_connection() as db:
            await db.execute(
                "INSERT INTO issues (id, title, description) VALUES (?, ?, ?)",
                (issue_id, data.title, data.description),
            )
            await db.commit()
            cursor = await db.execute(
                "SELECT * FROM issues WHERE id = ?", (issue_id,)
            )
            row = await cursor.fetchone()
            return Issue(**dict(row))  # type: ignore[arg-type]

    async def get(self, issue_id: str) -> Issue | None:
        async with get_db_connection() as db:
            cursor = await db.execute(
                "SELECT * FROM issues WHERE id = ?", (issue_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return Issue(**dict(row))  # type: ignore[arg-type]

    async def list_all(
        self, status: IssueStatus | None = None
    ) -> list[Issue]:
        async with get_db_connection() as db:
            if status is not None:
                cursor = await db.execute(
                    "SELECT * FROM issues WHERE status = ? ORDER BY created_at DESC",
                    (status.value,),
                )
            else:
                cursor = await db.execute(
                    "SELECT * FROM issues ORDER BY created_at DESC"
                )
            rows = await cursor.fetchall()
            return [Issue(**dict(r)) for r in rows]  # type: ignore[arg-type]

    async def update_status(
        self, issue_id: str, status: IssueStatus
    ) -> None:
        async with get_db_connection() as db:
            await db.execute(
                "UPDATE issues SET status = ?, updated_at = datetime('now') WHERE id = ?",
                (status.value, issue_id),
            )
            await db.commit()


class ExecutionRepo:
    """Repository for the ``executions`` table. (Phase 1)"""

    async def create(self, **kwargs: object) -> None:
        raise NotImplementedError("Phase 1")

    async def update(self, **kwargs: object) -> None:
        raise NotImplementedError("Phase 1")

    async def list_by_issue(self, issue_id: str) -> list:
        raise NotImplementedError("Phase 1")


class ExecutionLogRepo:
    """Repository for the ``execution_logs`` table. (Phase 1)"""

    async def append(
        self, execution_id: str, level: LogLevel, message: str
    ) -> None:
        raise NotImplementedError("Phase 1")

    async def list_by_execution(
        self, execution_id: str
    ) -> list[ExecutionLog]:
        raise NotImplementedError("Phase 1")
