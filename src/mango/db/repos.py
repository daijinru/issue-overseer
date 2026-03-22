"""Database repository classes for issues, executions, and logs."""

from __future__ import annotations

import json
import uuid

from mango.db.connection import get_db_connection
from mango.models import (
    Execution,
    ExecutionLog,
    ExecutionStatus,
    Issue,
    IssueCreate,
    IssueStatus,
    LogLevel,
)


_ALLOWED_ISSUE_FIELDS = frozenset({
    "branch_name", "human_instruction", "pr_url", "workspace", "spec",
})


class IssueRepo:
    """Repository for the ``issues`` table."""

    async def create(self, data: IssueCreate) -> Issue:
        issue_id = str(uuid.uuid4())
        async with get_db_connection() as db:
            await db.execute(
                "INSERT INTO issues (id, title, description, workspace) VALUES (?, ?, ?, ?)",
                (issue_id, data.title, data.description, data.workspace),
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

    async def update_fields(self, issue_id: str, **fields: object) -> None:
        if not fields:
            return
        invalid = set(fields) - _ALLOWED_ISSUE_FIELDS
        if invalid:
            raise ValueError(f"Disallowed field(s): {invalid}")
        set_clauses = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [issue_id]
        async with get_db_connection() as db:
            await db.execute(
                f"UPDATE issues SET {set_clauses}, updated_at = datetime('now') WHERE id = ?",
                values,
            )
            await db.commit()


class ExecutionRepo:
    """Repository for the ``executions`` table."""

    async def create(self, *, execution_id: str, issue_id: str, turn_number: int,
                     attempt_number: int, prompt: str | None = None,
                     context_snapshot: dict | None = None,
                     git_diff_snapshot: str | None = None) -> Execution:
        ctx_json = json.dumps(context_snapshot) if context_snapshot else None
        async with get_db_connection() as db:
            await db.execute(
                """INSERT INTO executions
                   (id, issue_id, turn_number, attempt_number, prompt, context_snapshot, git_diff_snapshot)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (execution_id, issue_id, turn_number, attempt_number, prompt, ctx_json, git_diff_snapshot),
            )
            await db.commit()
            cursor = await db.execute("SELECT * FROM executions WHERE id = ?", (execution_id,))
            row = await cursor.fetchone()
            return Execution(**dict(row))

    async def finish(self, execution_id: str, *, status: ExecutionStatus,
                     result: str | None = None, error_message: str | None = None,
                     duration_ms: int | None = None) -> None:
        async with get_db_connection() as db:
            await db.execute(
                """UPDATE executions SET status = ?, result = ?, error_message = ?,
                       duration_ms = ?, finished_at = datetime('now') WHERE id = ?""",
                (status.value, result, error_message, duration_ms, execution_id),
            )
            await db.commit()

    async def list_by_issue(self, issue_id: str) -> list[Execution]:
        async with get_db_connection() as db:
            cursor = await db.execute(
                "SELECT * FROM executions WHERE issue_id = ? ORDER BY started_at",
                (issue_id,),
            )
            rows = await cursor.fetchall()
            return [Execution(**dict(r)) for r in rows]


class ExecutionLogRepo:
    """Repository for the ``execution_logs`` table."""

    async def append(self, execution_id: str, level: LogLevel, message: str) -> None:
        async with get_db_connection() as db:
            await db.execute(
                "INSERT INTO execution_logs (execution_id, level, message) VALUES (?, ?, ?)",
                (execution_id, level.value, message),
            )
            await db.commit()

    async def list_by_execution(self, execution_id: str) -> list[ExecutionLog]:
        async with get_db_connection() as db:
            cursor = await db.execute(
                "SELECT * FROM execution_logs WHERE execution_id = ? ORDER BY created_at",
                (execution_id,),
            )
            rows = await cursor.fetchall()
            return [ExecutionLog(**dict(r)) for r in rows]

    async def list_by_issue(self, issue_id: str) -> list[ExecutionLog]:
        async with get_db_connection() as db:
            cursor = await db.execute(
                """SELECT el.* FROM execution_logs el
                   JOIN executions e ON el.execution_id = e.id
                   WHERE e.issue_id = ?
                   ORDER BY el.created_at""",
                (issue_id,),
            )
            rows = await cursor.fetchall()
            return [ExecutionLog(**dict(r)) for r in rows]
