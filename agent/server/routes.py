"""API routes for Mango."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent.db.connection import get_db_connection
from agent.db.repos import ExecutionLogRepo, ExecutionRepo, ExecutionStepRepo, IssueRepo
from agent.models import (
    Execution, ExecutionLog, ExecutionStep, Issue, IssueCreate, IssueRetry, IssueStatus,
    IssueUpdate, IssuePriority,
)
from agent.server.sse import sse_stream

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
async def list_issues(status: IssueStatus | None = None, priority: IssuePriority | None = None):
    repo = IssueRepo()
    return await repo.list_all(status=status, priority=priority)


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
    if issue.status not in (IssueStatus.open, IssueStatus.planned, IssueStatus.waiting_human, IssueStatus.cancelled):
        raise HTTPException(status_code=409, detail=f"Issue is {issue.status.value}, must be 'open', 'planned', 'waiting_human' or 'cancelled' to run")
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
    if issue.status not in (IssueStatus.waiting_human,):
        raise HTTPException(status_code=409, detail=f"Issue is {issue.status.value}, must be 'waiting_human' to retry")
    await repo.retry_reset(issue_id, body.human_instruction, workspace=body.workspace)
    await runtime.start_task(issue_id)
    return {"message": "Retry started", "issue_id": issue_id}


@router.post("/issues/{issue_id}/complete")
async def complete_issue(issue_id: str):
    """Mark a review issue as done."""
    repo = IssueRepo()
    issue = await repo.get(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if issue.status != IssueStatus.review:
        raise HTTPException(
            status_code=409,
            detail=f"Issue is {issue.status.value}, must be 'review' to complete",
        )
    await repo.update_status(issue_id, IssueStatus.done)
    updated = await repo.get(issue_id)
    return updated


@router.post("/issues/{issue_id}/plan", status_code=202)
async def plan_issue(issue_id: str, request: Request):
    """Trigger Spec generation (open → planning → planned)."""
    runtime = _get_runtime(request)
    repo = IssueRepo()
    issue = await repo.get(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if issue.status != IssueStatus.open:
        raise HTTPException(
            status_code=409,
            detail=f"Issue is {issue.status.value}, must be 'open' to plan",
        )
    if runtime.is_running(issue_id):
        raise HTTPException(status_code=409, detail="Issue is already running")
    await runtime.start_plan(issue_id)
    return {"message": "Plan generation started", "issue_id": issue_id}


class SpecUpdate(BaseModel):
    spec: str


@router.put("/issues/{issue_id}/spec", response_model=Issue)
async def update_spec(issue_id: str, body: SpecUpdate):
    """Edit Spec content (only in planned status)."""
    repo = IssueRepo()
    issue = await repo.get(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if issue.status != IssueStatus.planned:
        raise HTTPException(
            status_code=409,
            detail=f"Issue is {issue.status.value}, must be 'planned' to edit spec",
        )
    await repo.update_fields(issue_id, spec=body.spec)
    updated = await repo.get(issue_id)
    return updated


@router.post("/issues/{issue_id}/reject-spec", response_model=Issue)
async def reject_spec(issue_id: str):
    """Reject Spec and return Issue to open (planned → open)."""
    repo = IssueRepo()
    issue = await repo.get(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if issue.status != IssueStatus.planned:
        raise HTTPException(
            status_code=409,
            detail=f"Issue is {issue.status.value}, must be 'planned' to reject spec",
        )
    await repo.update_fields(issue_id, spec=None)
    await repo.update_status(issue_id, IssueStatus.open)
    updated = await repo.get(issue_id)
    return updated


@router.patch("/issues/{issue_id}", response_model=Issue)
async def edit_issue(issue_id: str, body: IssueUpdate):
    """Edit an issue's title, description, or priority (only in open/planned status)."""
    repo = IssueRepo()
    issue = await repo.get(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if issue.status not in (IssueStatus.open, IssueStatus.planned):
        raise HTTPException(
            status_code=409,
            detail=f"Issue is {issue.status.value}, must be 'open' or 'planned' to edit",
        )
    fields: dict[str, object] = {}
    if body.title is not None:
        fields["title"] = body.title
    if body.description is not None:
        fields["description"] = body.description
    if body.priority is not None:
        fields["priority"] = body.priority.value
    if not fields:
        raise HTTPException(status_code=422, detail="No fields to update")
    # Use direct SQL for title/description since they are not in _ALLOWED_ISSUE_FIELDS
    async with get_db_connection() as db:
        set_clauses = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [issue_id]
        await db.execute(
            f"UPDATE issues SET {set_clauses}, updated_at = datetime('now') WHERE id = ?",
            values,
        )
        await db.commit()
    updated = await repo.get(issue_id)
    return updated


@router.delete("/issues/{issue_id}", status_code=204)
async def delete_issue(issue_id: str):
    """Delete an issue (only in open/done/waiting_human/cancelled status)."""
    repo = IssueRepo()
    issue = await repo.get(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if issue.status not in (IssueStatus.open, IssueStatus.done, IssueStatus.waiting_human, IssueStatus.cancelled):
        raise HTTPException(
            status_code=409,
            detail=f"Issue is {issue.status.value}, must be 'open', 'done', 'waiting_human' or 'cancelled' to delete",
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
