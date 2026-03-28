"""Database repository classes for sessions and messages."""

from __future__ import annotations

import json
import uuid

from mango_gateway.db.connection import get_db_connection
from mango_gateway.models import (
    Message,
    MessageRole,
    Session,
    SessionCreate,
    SessionStatus,
)


class SessionRepo:
    """Repository for the ``sessions`` table."""

    async def create(self, data: SessionCreate, runtime_url: str = "") -> Session:
        session_id = str(uuid.uuid4())
        metadata_json = json.dumps(data.metadata) if data.metadata else None
        async with get_db_connection() as db:
            await db.execute(
                """INSERT INTO sessions (id, source, source_id, runtime_url, metadata)
                   VALUES (?, ?, ?, ?, ?)""",
                (session_id, data.source, data.source_id, runtime_url, metadata_json),
            )
            await db.commit()
            cursor = await db.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            )
            row = await cursor.fetchone()
            return Session(**dict(row))  # type: ignore[arg-type]

    async def get(self, session_id: str) -> Session | None:
        async with get_db_connection() as db:
            cursor = await db.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return Session(**dict(row))  # type: ignore[arg-type]

    async def get_by_source(self, source: str, source_id: str) -> Session | None:
        """Find an active session by source + source_id."""
        async with get_db_connection() as db:
            cursor = await db.execute(
                """SELECT * FROM sessions
                   WHERE source = ? AND source_id = ? AND status = ?
                   ORDER BY created_at DESC LIMIT 1""",
                (source, source_id, SessionStatus.active.value),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return Session(**dict(row))  # type: ignore[arg-type]

    async def update_fields(self, session_id: str, **kwargs: object) -> None:
        """Update arbitrary fields on a session."""
        if not kwargs:
            return
        async with get_db_connection() as db:
            set_clauses = ", ".join(f"{k} = ?" for k in kwargs)
            values = list(kwargs.values()) + [session_id]
            await db.execute(
                f"UPDATE sessions SET {set_clauses}, updated_at = datetime('now') WHERE id = ?",
                values,
            )
            await db.commit()

    async def close(self, session_id: str) -> None:
        """Close a session."""
        async with get_db_connection() as db:
            await db.execute(
                """UPDATE sessions
                   SET status = ?, closed_at = datetime('now'), updated_at = datetime('now')
                   WHERE id = ?""",
                (SessionStatus.closed.value, session_id),
            )
            await db.commit()

    async def list_expired(self, max_age_hours: int) -> list[Session]:
        """List sessions that have been active longer than max_age_hours."""
        async with get_db_connection() as db:
            cursor = await db.execute(
                """SELECT * FROM sessions
                   WHERE status = ? AND created_at < datetime('now', ? || ' hours')""",
                (SessionStatus.active.value, f"-{max_age_hours}"),
            )
            rows = await cursor.fetchall()
            return [Session(**dict(r)) for r in rows]  # type: ignore[arg-type]

    async def delete(self, session_id: str) -> None:
        """Delete a session and its messages (CASCADE)."""
        async with get_db_connection() as db:
            await db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            await db.commit()


class MessageRepo:
    """Repository for the ``messages`` table."""

    async def create(
        self,
        session_id: str,
        role: MessageRole,
        content: str,
        issue_id: str | None = None,
        metadata: str | None = None,
    ) -> Message:
        async with get_db_connection() as db:
            cursor = await db.execute(
                """INSERT INTO messages (session_id, role, content, issue_id, metadata)
                   VALUES (?, ?, ?, ?, ?)""",
                (session_id, role.value, content, issue_id, metadata),
            )
            await db.commit()
            msg_id = cursor.lastrowid
            cursor = await db.execute(
                "SELECT * FROM messages WHERE id = ?", (msg_id,)
            )
            row = await cursor.fetchone()
            return Message(**dict(row))  # type: ignore[arg-type]

    async def list_by_session(
        self, session_id: str, limit: int = 100
    ) -> list[Message]:
        async with get_db_connection() as db:
            cursor = await db.execute(
                """SELECT * FROM messages
                   WHERE session_id = ?
                   ORDER BY created_at ASC
                   LIMIT ?""",
                (session_id, limit),
            )
            rows = await cursor.fetchall()
            return [Message(**dict(r)) for r in rows]  # type: ignore[arg-type]

    async def list_by_issue(self, issue_id: str) -> list[Message]:
        async with get_db_connection() as db:
            cursor = await db.execute(
                """SELECT * FROM messages
                   WHERE issue_id = ?
                   ORDER BY created_at ASC""",
                (issue_id,),
            )
            rows = await cursor.fetchall()
            return [Message(**dict(r)) for r in rows]  # type: ignore[arg-type]
