"""API routes for Mango."""

from __future__ import annotations

import platform
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent.db.connection import get_db_connection
from agent.db.repos import ExecutionLogRepo, ExecutionRepo, ExecutionStepRepo, IssueRepo
from agent.models import (
    Execution, ExecutionLog, ExecutionStep, Issue, IssueCreate, IssueStatus,
)
from agent.server.sse import sse_stream

router = APIRouter(prefix="/api")


def _get_runtime(request: Request):
    return request.app.state.runtime


class HealthResponse(BaseModel):
    status: str
    version: str


class WorkspaceSelection(BaseModel):
    workspace: str | None


def select_workspace() -> str | None:
    """Open the local operating system's directory picker."""
    if platform.system() != "Darwin":
        raise RuntimeError("当前系统暂不支持原生目录选择")

    try:
        result = subprocess.run(
            [
                "osascript",
                "-e",
                "POSIX path of (choose folder with prompt \"选择 Issue 工作目录\")",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("选择目录超时，请重试") from exc
    except OSError as exc:
        raise RuntimeError("本机无法打开目录选择窗口") from exc

    if result.returncode != 0:
        if "User canceled" in result.stderr or "-128" in result.stderr:
            return None
        raise RuntimeError("目录选择窗口未能完成")
    selection = result.stdout.strip()
    return str(Path(selection)) if selection else None


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    async with get_db_connection() as db:
        await db.execute("SELECT 1")
    return HealthResponse(status="ok", version="0.1.0")


@router.post("/workspaces/select", response_model=WorkspaceSelection)
async def choose_workspace() -> WorkspaceSelection:
    try:
        return WorkspaceSelection(workspace=select_workspace())
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/issues", response_model=Issue, status_code=201)
async def create_issue(data: IssueCreate):
    repo = IssueRepo()
    return await repo.create(data)


@router.get("/issues", response_model=list[Issue])
async def list_issues(status: IssueStatus | None = None):
    repo = IssueRepo()
    return await repo.list_all(status=status)


@router.get("/issues/{issue_id}", response_model=Issue)
async def get_issue(issue_id: str):
    repo = IssueRepo()
    issue = await repo.get(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    return issue


@router.post("/issues/{issue_id}/run", status_code=202)
async def run_issue(issue_id: str, request: Request):
    runtime = _get_runtime(request)
    issue = await IssueRepo().get(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if issue.status is not IssueStatus.pending:
        raise HTTPException(status_code=409, detail="Issue must be pending to run")
    if runtime.is_running(issue_id):
        raise HTTPException(status_code=409, detail="Issue is already running")
    try:
        await runtime.start_task(issue_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="Issue is no longer pending") from exc
    return {"message": "Task started", "issue_id": issue_id}


@router.post("/issues/{issue_id}/cancel")
async def cancel_issue(issue_id: str, request: Request):
    runtime = _get_runtime(request)
    cancelled = await runtime.cancel_task(issue_id)
    if not cancelled:
        raise HTTPException(status_code=409, detail="Issue is not running")
    return {"message": "Cancel signal sent", "issue_id": issue_id}


@router.delete("/issues/{issue_id}", status_code=204)
async def delete_issue(issue_id: str):
    """Delete a non-running Issue."""
    repo = IssueRepo()
    issue = await repo.get(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if issue.status is IssueStatus.running:
        raise HTTPException(
            status_code=409,
            detail="A running Issue cannot be deleted",
        )
    await repo.delete(issue_id)


@router.get("/issues/{issue_id}/logs", response_model=list[ExecutionLog])
async def get_issue_logs(issue_id: str):
    repo = IssueRepo()
    issue = await repo.get(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    log_repo = ExecutionLogRepo()
    return await log_repo.list_by_issue(issue_id)


@router.get("/issues/{issue_id}/steps", response_model=list[ExecutionStep])
async def get_issue_steps(issue_id: str):
    repo = IssueRepo()
    issue = await repo.get(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    step_repo = ExecutionStepRepo()
    return await step_repo.list_by_issue(issue_id)


@router.get("/issues/{issue_id}/executions", response_model=list[Execution])
async def get_issue_executions(issue_id: str):
    repo = IssueRepo()
    issue = await repo.get(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    exec_repo = ExecutionRepo()
    return await exec_repo.list_by_issue(issue_id)


@router.get("/issues/{issue_id}/stream")
async def stream_issue_events(issue_id: str, request: Request):
    """SSE endpoint — real-time event stream for an issue's execution."""
    repo = IssueRepo()
    issue = await repo.get(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    event_bus = request.app.state.event_bus
    return StreamingResponse(
        sse_stream(event_bus, issue_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
