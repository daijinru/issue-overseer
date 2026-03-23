"""Agent Runtime — runTask → runTurn → runAttempt loop."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import asdict
from typing import TYPE_CHECKING

from mango.agent.context import build_turn_context
from mango.agent.opencode_client import OpenCodeClient
from mango.agent.safety import extract_commands_from_result, validate_command
from mango.config import get_settings
from mango.db.repos import ExecutionLogRepo, ExecutionRepo, IssueRepo
from mango.models import ExecutionStatus, Issue, IssueStatus, LogLevel
from mango.skills.base import GenericSkill

if TYPE_CHECKING:
    from mango.server.event_bus import EventBus

logger = logging.getLogger(__name__)


class AgentRuntime:
    def __init__(self, event_bus: EventBus | None = None) -> None:
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
        self._event_bus = event_bus

    # ── Event helpers ───────────────────────────────────────────────

    def _emit(self, issue_id: str, event_type: str, data: dict | None = None) -> None:
        """Publish an event via the EventBus (no-op when bus is absent)."""
        if self._event_bus is not None:
            self._event_bus.publish(issue_id, event_type, data)

    async def recover_from_restart(self) -> None:
        """Recover issues stuck in 'running' after a service restart.

        Sets them to 'waiting_human' and logs the interruption.
        """
        stuck_issues = await self.issue_repo.list_all(status=IssueStatus.running)
        for issue in stuck_issues:
            logger.warning("Recovering stuck issue %s (%s)", issue.id, issue.title)
            await self.issue_repo.update_status(issue.id, IssueStatus.waiting_human)
            # Find the latest execution for this issue and log the interruption
            executions = await self.exec_repo.list_by_issue(issue.id)
            if executions:
                latest_exec = executions[-1]
                # Mark running executions as failed
                if latest_exec.status == ExecutionStatus.running:
                    await self.exec_repo.finish(
                        latest_exec.id,
                        status=ExecutionStatus.failed,
                        error_message="服务重启，执行中断",
                    )
                await self.log_repo.append(
                    latest_exec.id, LogLevel.warn, "服务重启，执行中断"
                )
            logger.info("Issue %s recovered to waiting_human", issue.id)

    async def start_task(self, issue_id: str) -> None:
        issue = await self.issue_repo.get(issue_id)
        if issue is None:
            raise ValueError(f"Issue {issue_id} not found")
        if issue.status not in (IssueStatus.open, IssueStatus.waiting_human, IssueStatus.cancelled):
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
        self._emit(issue_id, "task_start", {"issue_id": issue_id, "branch_name": branch_name})
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
                        self._emit(issue_id, "task_cancelled", {"issue_id": issue_id})
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
            self._emit(issue_id, "task_cancelled", {"issue_id": issue_id})
            return
        if success:
            committed = await self._git_commit(
                branch_name, f"agent: resolve issue {issue.title}", cwd=workspace,
            )
            if not committed:
                logger.warning("Task %s: AI reported success but no file changes", issue_id)
                await self.issue_repo.update_status(issue_id, IssueStatus.waiting_human)
                self._emit(issue_id, "task_end", {"issue_id": issue_id, "success": False})
            else:
                self._emit(issue_id, "git_commit", {"branch_name": branch_name})
                pushed = await self._git_push(branch_name, cwd=workspace)
                if not pushed:
                    logger.warning("Task %s: git push failed", issue_id)
                    await self.issue_repo.update_status(issue_id, IssueStatus.waiting_human)
                    self._emit(issue_id, "task_end", {"issue_id": issue_id, "success": False})
                else:
                    self._emit(issue_id, "git_push", {"branch_name": branch_name})
                    pr_url = await self._create_pr(branch_name, issue, cwd=workspace)
                    if pr_url:
                        await self.issue_repo.update_fields(issue_id, pr_url=pr_url)
                        self._emit(issue_id, "pr_created", {"pr_url": pr_url})
                    else:
                        logger.warning("Task %s: PR creation failed (code is pushed)", issue_id)
                    await self.issue_repo.update_status(issue_id, IssueStatus.done)
                    self._emit(issue_id, "task_end", {"issue_id": issue_id, "success": True, "pr_url": pr_url})
        else:
            await self.issue_repo.update_status(issue_id, IssueStatus.waiting_human)
            self._emit(issue_id, "task_end", {"issue_id": issue_id, "success": False})

    async def _run_turn(self, *, issue, turn_number, max_turns,
                        cancel_event, last_result, last_error, execution_history) -> dict:
        self._emit(issue.id, "turn_start", {"turn_number": turn_number, "max_turns": max_turns})
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
        result = await self._run_attempt(
            execution_id=execution_id, ctx=ctx,
            cancel_event=cancel_event, cwd=workspace,
        )
        self._emit(issue.id, "turn_end", {"turn_number": turn_number, "success": result.get("success", False)})
        return result

    async def _run_attempt(self, *, execution_id, ctx, cancel_event, cwd: str) -> dict:
        issue_id = ctx.issue.id
        self._emit(issue_id, "attempt_start", {"execution_id": execution_id})
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
            self._emit(issue_id, "attempt_end", {"execution_id": execution_id, "status": "completed", "duration_ms": duration_ms})
            return {"success": True, "result": result_text, "error": None}
        except TimeoutError:
            duration_ms = int((time.monotonic() - start) * 1000)
            error_msg = f"Attempt timed out after {attempt_timeout}s"
            await self.exec_repo.finish(execution_id, status=ExecutionStatus.timeout,
                                        error_message=error_msg, duration_ms=duration_ms)
            await self.log_repo.append(execution_id, LogLevel.error, error_msg)
            self._emit(issue_id, "attempt_end", {"execution_id": execution_id, "status": "timeout", "duration_ms": duration_ms})
            return {"success": False, "result": None, "error": error_msg}
        except asyncio.CancelledError:
            duration_ms = int((time.monotonic() - start) * 1000)
            await self.exec_repo.finish(execution_id, status=ExecutionStatus.cancelled,
                                        error_message="Cancelled by user", duration_ms=duration_ms)
            self._emit(issue_id, "attempt_end", {"execution_id": execution_id, "status": "cancelled", "duration_ms": duration_ms})
            raise
        except Exception as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            error_msg = f"{type(e).__name__}: {e}"
            await self.exec_repo.finish(execution_id, status=ExecutionStatus.failed,
                                        error_message=error_msg, duration_ms=duration_ms)
            await self.log_repo.append(execution_id, LogLevel.error, error_msg)
            self._emit(issue_id, "attempt_end", {"execution_id": execution_id, "status": "failed", "duration_ms": duration_ms})
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
        # Check if branch already exists
        check = await asyncio.create_subprocess_exec(
            "git", "rev-parse", "--verify", branch_name, cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await check.communicate()
        if check.returncode == 0:
            # Branch exists — just checkout
            proc = await asyncio.create_subprocess_exec(
                "git", "checkout", branch_name, cwd=cwd,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.warning("git checkout failed: %s", stderr.decode())
        else:
            # Branch does not exist — create and checkout
            proc = await asyncio.create_subprocess_exec(
                "git", "checkout", "-b", branch_name, cwd=cwd,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.warning("git checkout -b failed: %s", stderr.decode())

    async def _git_commit(self, branch_name: str, message: str, *, cwd: str) -> bool:
        """Stage changed files and commit. Returns True if a commit was made."""
        # 1. Get modified tracked files
        proc = await asyncio.create_subprocess_exec(
            "git", "diff", "--name-only", cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        modified = [f for f in stdout.decode().strip().splitlines() if f]

        # 2. Get new untracked files (respecting .gitignore)
        proc = await asyncio.create_subprocess_exec(
            "git", "ls-files", "--others", "--exclude-standard", cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        untracked = [f for f in stdout.decode().strip().splitlines() if f]

        files_to_add = modified + untracked
        if not files_to_add:
            logger.warning("No file changes to commit")
            return False

        # 3. Stage only the changed files
        proc = await asyncio.create_subprocess_exec(
            "git", "add", "--", *files_to_add, cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        # 4. Verify something is staged
        proc = await asyncio.create_subprocess_exec(
            "git", "diff", "--cached", "--quiet", cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        if proc.returncode == 0:
            # returncode 0 means no staged changes
            logger.warning("Nothing staged after git add")
            return False

        # 5. Commit (no --allow-empty)
        proc = await asyncio.create_subprocess_exec(
            "git", "commit", "-m", message, cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning("git commit failed: %s", stderr.decode())
            return False
        return True

    async def _git_push(self, branch_name: str, *, cwd: str) -> bool:
        """Push branch to remote. Returns True on success."""
        remote = self.settings.project.remote
        proc = await asyncio.create_subprocess_exec(
            "git", "push", "-u", remote, branch_name, cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning("git push failed: %s", stderr.decode())
            return False
        return True

    async def _get_changed_files(self, branch_name: str, *, cwd: str) -> list[str]:
        """Return list of changed file paths between pr_base and branch."""
        pr_base = self.settings.project.pr_base
        proc = await asyncio.create_subprocess_exec(
            "git", "diff", "--name-only", f"{pr_base}...{branch_name}", cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return []
        return [f for f in stdout.decode().strip().splitlines() if f]

    async def _create_pr(
        self, branch_name: str, issue: Issue, *, cwd: str
    ) -> str | None:
        """Create a PR via gh CLI. Returns the PR URL on success, None on failure."""
        pr_base = self.settings.project.pr_base
        title = f"agent: {issue.title}"
        # Build body: issue description + changed files list
        body = issue.description or issue.title
        changed_files = await self._get_changed_files(branch_name, cwd=cwd)
        if changed_files:
            file_list = "\n".join(f"- {f}" for f in changed_files)
            body = f"{body}\n\n---\nChanged files:\n{file_list}"
        proc = await asyncio.create_subprocess_exec(
            "gh", "pr", "create",
            "--base", pr_base,
            "--head", branch_name,
            "--title", title,
            "--body", body,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning("gh pr create failed: %s", stderr.decode())
            return None
        pr_url = stdout.decode().strip()
        return pr_url or None

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
