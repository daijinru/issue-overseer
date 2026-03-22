"""Agent Runtime — runTask → runTurn → runAttempt loop."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import asdict

from mango.agent.context import build_turn_context
from mango.agent.opencode_client import OpenCodeClient
from mango.agent.safety import extract_commands_from_result, validate_command
from mango.config import get_settings
from mango.db.repos import ExecutionLogRepo, ExecutionRepo, IssueRepo
from mango.models import ExecutionStatus, Issue, IssueStatus, LogLevel
from mango.skills.base import GenericSkill

logger = logging.getLogger(__name__)


class AgentRuntime:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.issue_repo = IssueRepo()
        self.exec_repo = ExecutionRepo()
        self.log_repo = ExecutionLogRepo()
        self.client = OpenCodeClient(
            command=self.settings.opencode.command,
            timeout=self.settings.opencode.timeout,
        )
        self.skill = GenericSkill(self.client)
        self._cancel_tokens: dict[str, asyncio.Event] = {}
        self._running_tasks: dict[str, asyncio.Task] = {}

    async def start_task(self, issue_id: str) -> None:
        issue = await self.issue_repo.get(issue_id)
        if issue is None:
            raise ValueError(f"Issue {issue_id} not found")
        if issue.status not in (IssueStatus.open, IssueStatus.waiting_human):
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

    def _resolve_workspace(self, issue: Issue) -> str:
        """Return the working directory for an issue, falling back to global config."""
        return issue.workspace or self.settings.project.workspace

    async def _run_task(self, issue_id: str, cancel_event: asyncio.Event) -> None:
        issue = await self.issue_repo.get(issue_id)
        assert issue is not None
        await self.issue_repo.update_status(issue_id, IssueStatus.running)
        branch_name = f"agent/{issue_id[:8]}"
        workspace = self._resolve_workspace(issue)
        await self._git_create_branch(branch_name, cwd=workspace)
        await self.issue_repo.update_fields(issue_id, branch_name=branch_name)
        max_turns = self.settings.agent.max_turns
        task_timeout = self.settings.agent.task_timeout
        last_result: str | None = None
        last_error: str | None = None
        execution_history: list[dict] = []
        success = False
        try:
            async with asyncio.timeout(task_timeout):
                for turn in range(1, max_turns + 1):
                    if cancel_event.is_set():
                        await self.issue_repo.update_status(issue_id, IssueStatus.cancelled)
                        return
                    turn_result = await self._run_turn(
                        issue=issue, turn_number=turn, max_turns=max_turns,
                        cancel_event=cancel_event,
                        last_result=last_result, last_error=last_error,
                        execution_history=execution_history,
                    )
                    execution_history.append({
                        "turn": turn,
                        "status": "completed" if turn_result.get("success") else "failed",
                        "summary": (turn_result.get("result") or turn_result.get("error") or "")[:200],
                    })
                    if turn_result.get("success"):
                        success = True
                        break
                    last_result = turn_result.get("result")
                    last_error = turn_result.get("error")
        except TimeoutError:
            logger.warning("Task %s timed out after %ds", issue_id, task_timeout)
        except asyncio.CancelledError:
            await self.issue_repo.update_status(issue_id, IssueStatus.cancelled)
            return
        if success:
            await self._git_commit(branch_name, f"agent: resolve issue {issue.title}", cwd=workspace)
            await self.issue_repo.update_status(issue_id, IssueStatus.done)
        else:
            await self.issue_repo.update_status(issue_id, IssueStatus.waiting_human)

    async def _run_turn(self, *, issue, turn_number, max_turns,
                        cancel_event, last_result, last_error, execution_history) -> dict:
        fresh_issue = await self.issue_repo.get(issue.id)
        workspace = self._resolve_workspace(fresh_issue or issue)
        git_diff = await self._get_git_diff(cwd=workspace)
        ctx = build_turn_context(
            issue=fresh_issue or issue, turn_number=turn_number, max_turns=max_turns,
            last_result=last_result, last_error=last_error, git_diff=git_diff,
            execution_history=execution_history,
            human_instruction=(fresh_issue or issue).human_instruction,
        )
        execution_id = str(uuid.uuid4())
        await self.exec_repo.create(
            execution_id=execution_id, issue_id=issue.id,
            turn_number=turn_number, attempt_number=1,
            prompt=self.skill._build_prompt(ctx),
            context_snapshot=_context_to_dict(ctx), git_diff_snapshot=git_diff,
        )
        return await self._run_attempt(
            execution_id=execution_id, ctx=ctx,
            cancel_event=cancel_event, cwd=workspace,
        )

    async def _run_attempt(self, *, execution_id, ctx, cancel_event, cwd: str) -> dict:
        start = time.monotonic()
        attempt_timeout = self.settings.opencode.timeout
        try:
            async with asyncio.timeout(attempt_timeout):
                result_text = await self.skill.execute(
                    ctx, cwd, cancel_event=cancel_event
                )
            duration_ms = int((time.monotonic() - start) * 1000)
            await self._audit_commands(execution_id, result_text)
            await self.exec_repo.finish(execution_id, status=ExecutionStatus.completed,
                                        result=result_text, duration_ms=duration_ms)
            await self.log_repo.append(execution_id, LogLevel.info, f"Turn completed in {duration_ms}ms")
            return {"success": True, "result": result_text, "error": None}
        except TimeoutError:
            duration_ms = int((time.monotonic() - start) * 1000)
            error_msg = f"Attempt timed out after {attempt_timeout}s"
            await self.exec_repo.finish(execution_id, status=ExecutionStatus.timeout,
                                        error_message=error_msg, duration_ms=duration_ms)
            await self.log_repo.append(execution_id, LogLevel.error, error_msg)
            return {"success": False, "result": None, "error": error_msg}
        except asyncio.CancelledError:
            duration_ms = int((time.monotonic() - start) * 1000)
            await self.exec_repo.finish(execution_id, status=ExecutionStatus.cancelled,
                                        error_message="Cancelled by user", duration_ms=duration_ms)
            raise
        except Exception as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            error_msg = f"{type(e).__name__}: {e}"
            await self.exec_repo.finish(execution_id, status=ExecutionStatus.failed,
                                        error_message=error_msg, duration_ms=duration_ms)
            await self.log_repo.append(execution_id, LogLevel.error, error_msg)
            return {"success": False, "result": None, "error": error_msg}

    async def _audit_commands(self, execution_id: str, result_text: str) -> None:
        commands = extract_commands_from_result(result_text)
        security_cfg = self.settings.security
        for cmd in commands:
            is_allowed = validate_command(cmd, security_cfg)
            level = LogLevel.info if is_allowed else LogLevel.warn
            prefix = "CMD" if is_allowed else "⚠ BLOCKED CMD"
            await self.log_repo.append(execution_id, level, f"{prefix}: {cmd}")

    async def _git_create_branch(self, branch_name: str, *, cwd: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            "git", "checkout", "-b", branch_name, cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning("git checkout -b failed: %s", stderr.decode())

    async def _git_commit(self, branch_name: str, message: str, *, cwd: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            "git", "add", "-A", cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        proc = await asyncio.create_subprocess_exec(
            "git", "commit", "-m", message, "--allow-empty", cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning("git commit failed: %s", stderr.decode())

    async def _get_git_diff(self, *, cwd: str) -> str | None:
        default_branch = self.settings.project.default_branch
        proc = await asyncio.create_subprocess_exec(
            "git", "diff", default_branch, "--", cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        diff = stdout.decode()
        return diff if diff.strip() else None


def _context_to_dict(ctx) -> dict:
    d = asdict(ctx)
    d["issue"] = ctx.issue.model_dump()
    return d
