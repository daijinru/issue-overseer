"""API routes for Mango."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from mango.db.connection import get_db_connection
from mango.db.repos import ExecutionLogRepo, ExecutionRepo, IssueRepo
from mango.models import (
    Execution, ExecutionLog, Issue, IssueCreate, IssueRetry, IssueStatus,
)

router = APIRouter(prefix="/api")


def _get_runtime(request: Request):
    return request.app.state.runtime


class HealthResponse(BaseModel):
    status: str
    version: str


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    async with get_db_connection() as db:
        await db.execute("SELECT 1")
    return HealthResponse(status="ok", version="0.1.0")


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
    repo = IssueRepo()
    issue = await repo.get(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if issue.status not in (IssueStatus.open, IssueStatus.waiting_human, IssueStatus.cancelled):
        raise HTTPException(status_code=409, detail=f"Issue is {issue.status.value}, must be 'open', 'waiting_human' or 'cancelled' to run")
    if runtime.is_running(issue_id):
        raise HTTPException(status_code=409, detail="Issue is already running")
    await runtime.start_task(issue_id)
    return {"message": "Task started", "issue_id": issue_id}


@router.post("/issues/{issue_id}/cancel")
async def cancel_issue(issue_id: str, request: Request):
    runtime = _get_runtime(request)
    cancelled = await runtime.cancel_task(issue_id)
    if not cancelled:
        raise HTTPException(status_code=409, detail="Issue is not running")
    return {"message": "Cancel signal sent", "issue_id": issue_id}


@router.post("/issues/{issue_id}/retry", status_code=202)
async def retry_issue(issue_id: str, body: IssueRetry, request: Request):
    runtime = _get_runtime(request)
    repo = IssueRepo()
    issue = await repo.get(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if issue.status not in (IssueStatus.failed, IssueStatus.waiting_human):
        raise HTTPException(status_code=409, detail=f"Issue is {issue.status.value}, must be 'failed' or 'waiting_human' to retry")
    await repo.retry_reset(issue_id, body.human_instruction)
    await runtime.start_task(issue_id)
    return {"message": "Retry started", "issue_id": issue_id}


@router.get("/issues/{issue_id}/logs", response_model=list[ExecutionLog])
async def get_issue_logs(issue_id: str):
    repo = IssueRepo()
    issue = await repo.get(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    log_repo = ExecutionLogRepo()
    return await log_repo.list_by_issue(issue_id)


@router.get("/issues/{issue_id}/executions", response_model=list[Execution])
async def get_issue_executions(issue_id: str):
    repo = IssueRepo()
    issue = await repo.get(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    exec_repo = ExecutionRepo()
    return await exec_repo.list_by_issue(issue_id)
