"""Runtime lifecycle coordinator for simplified Issues."""

from __future__ import annotations

import asyncio
import logging

from agent.agent.cc_connect_client import CCConnectClient
from agent.config import get_settings
from agent.db.repos import ExecutionLogRepo, ExecutionRepo, ExecutionStepRepo, IssueRepo
from agent.models import ExecutionStatus, IssueOutcome, IssueStatus, LogLevel

logger = logging.getLogger(__name__)


class AgentRuntime:
    """Own Issue lifecycle state while Bridge execution is integrated separately."""

    def __init__(self, event_bus=None) -> None:
        self.settings = get_settings()
        self.issue_repo = IssueRepo()
        self.exec_repo = ExecutionRepo()
        self.log_repo = ExecutionLogRepo()
        self.step_repo = ExecutionStepRepo()
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

    async def _log(
        self, issue_id: str, execution_id: str, level: LogLevel, message: str,
    ) -> None:
        await self.log_repo.append(execution_id, level, message)
        self._emit(issue_id, "execution_log", {
            "execution_id": execution_id,
            "level": level.value,
            "message": message,
        })

    async def recover_from_restart(self) -> None:
        """Finish any interrupted running Issues with an error outcome."""
        for issue in await self.issue_repo.list_all(status=IssueStatus.running):
            reason = "服务重启，执行中断"
            logger.warning("Recovering interrupted Issue %s", issue.id)
            await self.issue_repo.finish(issue.id, IssueOutcome.error, None, reason)
            executions = await self.exec_repo.list_by_issue(issue.id)
            if executions:
                latest = executions[-1]
                if latest.status is ExecutionStatus.running:
                    await self.exec_repo.finish(
                        latest.id,
                        status=ExecutionStatus.failed,
                        error_message=reason,
                    )
                await self._log(issue.id, latest.id, LogLevel.warn, reason)

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

    def _cleanup(self, issue_id: str) -> None:
        self._cancel_tokens.pop(issue_id, None)
        self._running_tasks.pop(issue_id, None)

    async def _run_task(self, issue_id: str, cancel_event: asyncio.Event) -> None:
        """Record a terminal result until Task 3 supplies Bridge execution."""
        if cancel_event.is_set():
            message = "任务已取消"
        else:
            message = "Issue execution will be dispatched through cc-connect Bridge."

        await self.issue_repo.finish(issue_id, IssueOutcome.error, None, message)
        self._emit(issue_id, "task_end", {
            "issue_id": issue_id,
            "success": False,
            "error_message": message,
        })
