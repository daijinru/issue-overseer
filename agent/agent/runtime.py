"""Runtime lifecycle coordinator for simplified Issues."""

from __future__ import annotations

import asyncio
import logging

from agent.agent.cc_connect_client import CCConnectBridgeError, CCConnectClient, ProjectInfo
from agent.config import get_settings
from agent.db.repos import IssueRepo
from agent.models import IssueOutcome, IssueStatus

logger = logging.getLogger(__name__)


class AgentRuntime:
    """Own Issue lifecycle state and delegate each task to cc-connect."""

    def __init__(self, event_bus=None) -> None:
        self.settings = get_settings()
        self.issue_repo = IssueRepo()
        self.client = CCConnectClient(
            url=self.settings.cc_connect.url,
            token=self.settings.cc_connect.token,
            platform=self.settings.cc_connect.platform,
            timeout=self.settings.cc_connect.timeout,
        )
        self._cancel_tokens: dict[str, asyncio.Event] = {}
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._event_bus = event_bus

    def _emit(self, issue_id: str, event_type: str, data: dict | None = None) -> None:
        if self._event_bus is not None:
            self._event_bus.publish(issue_id, event_type, data)

    async def recover_from_restart(self) -> None:
        """Finish any interrupted running Issues with an error outcome."""
        for issue in await self.issue_repo.list_all(status=IssueStatus.running):
            reason = "服务重启，执行中断"
            logger.warning("Recovering interrupted Issue %s", issue.id)
            await self.issue_repo.finish(issue.id, IssueOutcome.error, None, reason)

    async def list_projects(self) -> list[ProjectInfo]:
        """Return the projects currently advertised by cc-connect."""
        return await self.client.list_projects()

    async def start_task(self, issue_id: str) -> None:
        """Atomically claim a pending Issue and schedule its execution."""
        if not await self.issue_repo.start(issue_id):
            issue = await self.issue_repo.get(issue_id)
            if issue is None:
                raise ValueError(f"Issue {issue_id} not found")
            raise ValueError(f"Issue {issue_id} is in status {issue.status}, cannot run")

        cancel_event = asyncio.Event()
        self._cancel_tokens[issue_id] = cancel_event
        task = asyncio.create_task(self._run_task(issue_id, cancel_event))
        self._running_tasks[issue_id] = task
        task.add_done_callback(lambda _: self._cleanup(issue_id))

    async def cancel_task(self, issue_id: str) -> bool:
        cancel_event = self._cancel_tokens.get(issue_id)
        if cancel_event is None:
            return False
        cancel_event.set()
        return True

    def is_running(self, issue_id: str) -> bool:
        return issue_id in self._running_tasks

    async def wait_for_task(self, issue_id: str) -> None:
        """Wait for an in-process task; used by callers that need its result."""
        task = self._running_tasks.get(issue_id)
        if task is not None:
            await task

    def _cleanup(self, issue_id: str) -> None:
        self._cancel_tokens.pop(issue_id, None)
        self._running_tasks.pop(issue_id, None)

    async def _run_task(self, issue_id: str, cancel_event: asyncio.Event) -> None:
        """Run one Issue against its selected cc-connect project."""
        if cancel_event.is_set():
            await self.issue_repo.finish(issue_id, IssueOutcome.error, None, "任务已取消")
            self._emit(issue_id, "task_end", {"success": False, "error": "任务已取消"})
            return

        issue = await self.issue_repo.get(issue_id)
        if issue is None:
            return
        self._emit(issue_id, "task_start", {"issue_id": issue_id})
        try:
            result = await self.client.run_task(issue.project, issue.content, issue.id)
        except CCConnectBridgeError as exc:
            await self.issue_repo.finish(issue_id, IssueOutcome.error, None, str(exc))
            self._emit(issue_id, "task_end", {"success": False, "error": str(exc)})
        else:
            await self.issue_repo.finish(issue_id, IssueOutcome.success, result, None)
            self._emit(issue_id, "task_end", {"success": True})
