"""GatewayService — session management, message routing, result waiting."""

from __future__ import annotations

import asyncio
import logging

from mango_gateway.config import Settings
from mango_gateway.db.repos import MessageRepo, SessionRepo
from mango_gateway.models import (
    GatewayMessageSend,
    GatewayReply,
    MessageRole,
    Session,
    SessionCreate,
    SessionStatus,
    Message,
)
from mango_gateway.service.runtime_client import RuntimeClient

logger = logging.getLogger(__name__)


class GatewayService:
    """Gateway service: session management + message routing + result waiting.

    The Gateway is a bridge, not a brain. All execution logic remains in
    AgentRuntime — Gateway only translates between messages and Issues.
    """

    def __init__(self, runtime_client: RuntimeClient, settings: Settings) -> None:
        self.runtime = runtime_client
        self.settings = settings
        self.session_repo = SessionRepo()
        self.message_repo = MessageRepo()

    # ── Session management ───────────────────────────────────────────

    async def create_session(self, data: SessionCreate) -> Session:
        """Create a new session."""
        return await self.session_repo.create(data, self.settings.runtime.url)

    async def get_session(self, session_id: str) -> Session | None:
        """Get a session by ID."""
        return await self.session_repo.get(session_id)

    async def close_session(self, session_id: str) -> Session:
        """Close a session."""
        session = await self.session_repo.get(session_id)
        if session is None:
            raise ValueError(f"Session {session_id} not found")
        if session.status != SessionStatus.active:
            raise ValueError(f"Session {session_id} is already {session.status.value}")
        await self.session_repo.close(session_id)
        updated = await self.session_repo.get(session_id)
        assert updated is not None
        return updated

    # ── Core message handling ────────────────────────────────────────

    async def send_message(self, data: GatewayMessageSend) -> GatewayReply:
        """Receive an external message, route it to Agent Runtime.

        Flow:
        1. Resolve or create Session
        2. Persist user message
        3. Route based on current Issue status:
           a. No current_issue → create new Issue + run
           b. current_issue in waiting_human → retry with instruction
           c. current_issue in done/review/cancelled → unbind, create new
           d. current_issue in running/planning → reject (409)
        4. If wait=true → consume Runtime SSE until terminal event
        5. Persist assistant reply and return
        """
        # 1. Resolve session
        session = await self._resolve_session(data)

        # 2. Persist user message
        await self.message_repo.create(
            session_id=session.id,
            role=MessageRole.user,
            content=data.content,
        )

        # 3. Route message → get issue_id
        issue_id = await self._route_message(session, data)

        # 4. Update session's current_issue_id
        await self.session_repo.update_fields(
            session.id, current_issue_id=issue_id
        )

        # 5. Wait for result if requested
        result_data: dict | None = None
        if data.wait:
            timeout = min(data.timeout, self.settings.gateway.max_wait_timeout)
            result_data = await self._wait_for_result(issue_id, timeout)

        # 6. Build reply
        issue = await self.runtime.get_issue(issue_id)
        reply_content = self._format_reply(issue, result_data)

        # Fetch execution result if available and wait was used
        result_text: str | None = None
        if result_data and data.wait:
            try:
                executions = await self.runtime.get_issue_executions(issue_id)
                if executions:
                    # Last execution's result
                    result_text = executions[-1].get("result")
            except Exception:
                logger.debug("Failed to fetch execution result for %s", issue_id)

        assistant_msg = await self.message_repo.create(
            session_id=session.id,
            role=MessageRole.assistant,
            content=reply_content,
            issue_id=issue_id,
        )

        return GatewayReply(
            session_id=session.id,
            message_id=assistant_msg.id,
            issue_id=issue_id,
            issue_status=issue.get("status", "unknown"),
            result=result_text,
            pr_url=issue.get("pr_url"),
            failure_reason=issue.get("failure_reason"),
        )

    async def get_session_messages(self, session_id: str) -> list[Message]:
        """Get all messages in a session."""
        return await self.message_repo.list_by_session(session_id)

    # ── Internal helpers ─────────────────────────────────────────────

    async def _resolve_session(self, data: GatewayMessageSend) -> Session:
        """Get an existing session or create a new one."""
        if data.session_id:
            session = await self.session_repo.get(data.session_id)
            if session is None:
                raise ValueError(f"Session {data.session_id} not found")
            if session.status != SessionStatus.active:
                raise ValueError(
                    f"Session {data.session_id} is {session.status.value}, "
                    "not active"
                )
            return session

        # Try to find existing session by source + source_id
        if data.source_id:
            existing = await self.session_repo.get_by_source(
                data.source, data.source_id
            )
            if existing:
                return existing

        # Auto-create session
        return await self.session_repo.create(
            SessionCreate(source=data.source, source_id=data.source_id),
            self.settings.runtime.url,
        )

    async def _route_message(
        self, session: Session, data: GatewayMessageSend
    ) -> str:
        """Decide how to handle the message based on current Issue status.

        Returns the issue_id that the message was routed to.
        """
        if session.current_issue_id:
            # Query Runtime for current Issue status
            try:
                issue = await self.runtime.get_issue(session.current_issue_id)
                status = issue.get("status")
            except Exception:
                # Issue not found or Runtime unreachable → treat as no Issue
                logger.warning(
                    "Failed to get issue %s from Runtime, creating new",
                    session.current_issue_id,
                )
                status = None

            if status == "waiting_human":
                # Use message content as retry instruction
                await self.runtime.retry_issue(
                    session.current_issue_id, data.content
                )
                return session.current_issue_id

            elif status in ("running", "planning"):
                raise RuntimeError(
                    "当前任务正在执行中，请等待完成后再发送新消息"
                )

            # status in (done, review, cancelled, open, planned, None)
            # → unbind old issue, create new one below

        # Create new Issue on Runtime
        issue = await self.runtime.create_issue(
            title=data.content[:100],
            description=data.content,
            workspace=data.workspace,
            priority=data.priority,
        )
        issue_id = issue["id"]

        # Trigger execution
        await self.runtime.run_issue(issue_id)
        return issue_id

    async def _wait_for_result(self, issue_id: str, timeout: int) -> dict:
        """Consume the Runtime's SSE stream, waiting for a terminal event.

        Subscribes to GET /api/issues/{id}/stream on the Runtime and blocks
        until task_end or task_cancelled is received.
        """
        try:
            async with asyncio.timeout(timeout):
                async for event in self.runtime.stream_issue_events(issue_id):
                    event_type = event.get("type")
                    if event_type in ("task_end", "task_cancelled"):
                        return event
        except TimeoutError:
            logger.warning("Wait for result timed out after %ds for %s", timeout, issue_id)
            return {"success": False, "failure_reason": "Gateway 等待超时"}
        except Exception:
            logger.exception("Error waiting for result on issue %s", issue_id)
            return {"success": False, "failure_reason": "SSE 流消费异常"}

        return {"success": False, "failure_reason": "SSE 流意外关闭"}

    def _format_reply(self, issue: dict, result_data: dict | None) -> str:
        """Format execution result into a human-readable reply."""
        status = issue.get("status", "unknown")

        if result_data and result_data.get("success"):
            pr_url = issue.get("pr_url")
            if pr_url:
                return f"任务完成，PR 已创建：{pr_url}"
            return "任务完成。"
        elif result_data:
            reason = result_data.get("failure_reason", "未知原因")
            return f"任务执行失败：{reason}\n你可以发送补充说明来重试。"
        else:
            return f"任务已提交，当前状态：{status}"

    # ── Cleanup ──────────────────────────────────────────────────────

    async def cleanup_expired_sessions(self) -> int:
        """Mark expired sessions as expired."""
        expired = await self.session_repo.list_expired(
            self.settings.session.timeout_hours
        )
        count = 0
        for session in expired:
            await self.session_repo.update_fields(
                session.id, status=SessionStatus.expired.value
            )
            count += 1
        return count

    async def run_cleanup_loop(self) -> None:
        """Background loop that periodically cleans up expired sessions."""
        interval = self.settings.session.cleanup_interval_minutes * 60
        while True:
            await asyncio.sleep(interval)
            try:
                count = await self.cleanup_expired_sessions()
                if count > 0:
                    logger.info("Cleaned up %d expired sessions", count)
            except Exception:
                logger.exception("Session cleanup failed")
