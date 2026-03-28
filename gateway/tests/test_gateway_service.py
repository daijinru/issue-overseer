"""Tests for GatewayService core logic."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mango_gateway.models import (
    GatewayMessageSend,
    MessageRole,
    SessionCreate,
    SessionStatus,
)
from mango_gateway.service.gateway import GatewayService


class TestSessionManagement:
    async def test_create_session(self, gateway_service: GatewayService):
        session = await gateway_service.create_session(
            SessionCreate(source="cli", source_id="user-123")
        )
        assert session.source == "cli"
        assert session.source_id == "user-123"
        assert session.status == SessionStatus.active
        assert session.id is not None

    async def test_get_session(self, gateway_service: GatewayService):
        created = await gateway_service.create_session(SessionCreate())
        fetched = await gateway_service.get_session(created.id)
        assert fetched is not None
        assert fetched.id == created.id

    async def test_get_nonexistent_session(self, gateway_service: GatewayService):
        result = await gateway_service.get_session("nonexistent")
        assert result is None

    async def test_close_session(self, gateway_service: GatewayService):
        session = await gateway_service.create_session(SessionCreate())
        closed = await gateway_service.close_session(session.id)
        assert closed.status == SessionStatus.closed
        assert closed.closed_at is not None

    async def test_close_nonexistent_session(self, gateway_service: GatewayService):
        with pytest.raises(ValueError, match="not found"):
            await gateway_service.close_session("nonexistent")

    async def test_close_already_closed_session(self, gateway_service: GatewayService):
        session = await gateway_service.create_session(SessionCreate())
        await gateway_service.close_session(session.id)
        with pytest.raises(ValueError, match="already"):
            await gateway_service.close_session(session.id)


class TestSendMessage:
    async def test_new_session_new_issue(self, gateway_service: GatewayService):
        """First message: auto-creates session + issue, triggers run."""
        reply = await gateway_service.send_message(
            GatewayMessageSend(
                content="帮我写一个 hello world",
                workspace="/tmp/test-repo",
            )
        )

        assert reply.session_id is not None
        assert reply.issue_id == "test-issue-001"
        assert reply.issue_status == "running"

        # Verify Runtime calls
        gateway_service.runtime.create_issue.assert_called_once()
        gateway_service.runtime.run_issue.assert_called_once_with("test-issue-001")

    async def test_existing_session_new_issue(self, gateway_service: GatewayService):
        """Use existing session_id."""
        session = await gateway_service.create_session(SessionCreate(source="api"))
        reply = await gateway_service.send_message(
            GatewayMessageSend(
                content="帮我写一个函数",
                session_id=session.id,
            )
        )

        assert reply.session_id == session.id
        assert reply.issue_id == "test-issue-001"

    async def test_retry_on_waiting_human(self, gateway_service: GatewayService):
        """When current issue is waiting_human, message becomes retry instruction."""
        # Setup: create session with current issue in waiting_human
        session = await gateway_service.create_session(SessionCreate())
        await gateway_service.session_repo.update_fields(
            session.id, current_issue_id="existing-issue-001"
        )

        # Mock: issue is in waiting_human
        gateway_service.runtime.get_issue.return_value = {
            "id": "existing-issue-001",
            "status": "waiting_human",
            "pr_url": None,
            "failure_reason": "Test failed",
        }

        reply = await gateway_service.send_message(
            GatewayMessageSend(
                content="请检查 import 路径",
                session_id=session.id,
            )
        )

        assert reply.issue_id == "existing-issue-001"
        gateway_service.runtime.retry_issue.assert_called_once_with(
            "existing-issue-001", "请检查 import 路径"
        )

    async def test_reject_when_running(self, gateway_service: GatewayService):
        """When current issue is running, reject with 409."""
        session = await gateway_service.create_session(SessionCreate())
        await gateway_service.session_repo.update_fields(
            session.id, current_issue_id="running-issue"
        )

        gateway_service.runtime.get_issue.return_value = {
            "id": "running-issue",
            "status": "running",
        }

        with pytest.raises(RuntimeError, match="正在执行中"):
            await gateway_service.send_message(
                GatewayMessageSend(
                    content="新任务",
                    session_id=session.id,
                )
            )

    async def test_new_issue_after_done(self, gateway_service: GatewayService):
        """When current issue is done, create a new issue."""
        session = await gateway_service.create_session(SessionCreate())
        await gateway_service.session_repo.update_fields(
            session.id, current_issue_id="done-issue"
        )

        gateway_service.runtime.get_issue.side_effect = [
            # First call: check current issue
            {"id": "done-issue", "status": "done", "pr_url": None, "failure_reason": None},
            # Second call: create_issue returns
            # Third call: get_issue for the new issue
            {"id": "test-issue-001", "status": "running", "pr_url": None, "failure_reason": None},
        ]

        reply = await gateway_service.send_message(
            GatewayMessageSend(
                content="新任务",
                session_id=session.id,
            )
        )

        assert reply.issue_id == "test-issue-001"
        gateway_service.runtime.create_issue.assert_called_once()

    async def test_invalid_session_id(self, gateway_service: GatewayService):
        with pytest.raises(ValueError, match="not found"):
            await gateway_service.send_message(
                GatewayMessageSend(
                    content="test",
                    session_id="nonexistent",
                )
            )


class TestMessageHistory:
    async def test_messages_persisted(self, gateway_service: GatewayService):
        """Messages should be persisted in the database."""
        reply = await gateway_service.send_message(
            GatewayMessageSend(content="帮我写代码")
        )

        messages = await gateway_service.get_session_messages(reply.session_id)
        assert len(messages) == 2  # user + assistant
        assert messages[0].role == MessageRole.user
        assert messages[0].content == "帮我写代码"
        assert messages[1].role == MessageRole.assistant


class TestFormatReply:
    def test_success_with_pr(self, gateway_service: GatewayService):
        issue = {"status": "review", "pr_url": "https://github.com/pr/1"}
        result = {"success": True}
        reply = gateway_service._format_reply(issue, result)
        assert "PR 已创建" in reply
        assert "https://github.com/pr/1" in reply

    def test_success_without_pr(self, gateway_service: GatewayService):
        issue = {"status": "done", "pr_url": None}
        result = {"success": True}
        reply = gateway_service._format_reply(issue, result)
        assert "任务完成" in reply

    def test_failure(self, gateway_service: GatewayService):
        issue = {"status": "waiting_human"}
        result = {"success": False, "failure_reason": "Test failed"}
        reply = gateway_service._format_reply(issue, result)
        assert "失败" in reply
        assert "Test failed" in reply

    def test_no_result(self, gateway_service: GatewayService):
        issue = {"status": "running"}
        reply = gateway_service._format_reply(issue, None)
        assert "已提交" in reply


class TestCleanup:
    async def test_cleanup_no_expired(self, gateway_service: GatewayService):
        count = await gateway_service.cleanup_expired_sessions()
        assert count == 0
