"""Database repository for simplified Issues."""

from __future__ import annotations

import uuid

from agent.db.connection import get_db_connection
from agent.models import Issue, IssueCreate, IssueOutcome, IssueStatus


class IssueRepo:
    """Repository for the ``issues`` table."""

    async def create(self, data: IssueCreate) -> Issue:
        issue_id = str(uuid.uuid4())
        async with get_db_connection() as db:
            await db.execute(
                """INSERT INTO issues (id, title, content, project, status)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    issue_id,
                    data.content,
                    data.content,
                    data.project,
                    IssueStatus.pending.value,
                ),
            )
            await db.commit()
            cursor = await db.execute(
                "SELECT * FROM issues WHERE id = ?", (issue_id,)
            )
            row = await cursor.fetchone()
            return Issue(**dict(row))  # type: ignore[arg-type]

    async def start(self, issue_id: str) -> bool:
        """Transition an issue from pending to running exactly once."""
        async with get_db_connection() as db:
            cursor = await db.execute(
                """UPDATE issues
                   SET status = ?, updated_at = datetime('now')
                   WHERE id = ? AND status = ?""",
                (IssueStatus.running.value, issue_id, IssueStatus.pending.value),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def finish(
        self,
        issue_id: str,
        outcome: IssueOutcome,
        result: str | None,
        error_message: str | None,
    ) -> None:
        """Record one terminal issue outcome."""
        async with get_db_connection() as db:
            await db.execute(
                """UPDATE issues
                   SET status = ?, outcome = ?, result = ?, failure_reason = ?,
                       finished_at = datetime('now'), updated_at = datetime('now')
                   WHERE id = ?""",
                (
                    IssueStatus.finished.value,
                    outcome.value,
                    result,
                    error_message,
                    issue_id,
                ),
            )
            await db.commit()

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
        self, status: IssueStatus | None = None,
    ) -> list[Issue]:
        async with get_db_connection() as db:
            conditions: list[str] = []
            params: list[str] = []
            if status is not None:
                conditions.append("status = ?")
                params.append(status.value)
            where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
            cursor = await db.execute(
                f"SELECT * FROM issues{where} ORDER BY created_at DESC",
                params,
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

    async def delete(self, issue_id: str) -> bool:
        """Delete an Issue and its historical legacy rows. Returns True if deleted."""
        async with get_db_connection() as db:
            # Delete execution logs via join
            await db.execute(
                """DELETE FROM execution_logs WHERE execution_id IN
                   (SELECT id FROM executions WHERE issue_id = ?)""",
                (issue_id,),
            )
            # Delete execution steps via join
            await db.execute(
                """DELETE FROM execution_steps WHERE execution_id IN
                   (SELECT id FROM executions WHERE issue_id = ?)""",
                (issue_id,),
            )
            # Delete executions
            await db.execute(
                "DELETE FROM executions WHERE issue_id = ?",
                (issue_id,),
            )
            # Delete the issue itself
            cursor = await db.execute(
                "DELETE FROM issues WHERE id = ?",
                (issue_id,),
            )
            await db.commit()
            return cursor.rowcount > 0
