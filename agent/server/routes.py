"""API routes for Mango."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent.agent.cc_connect_client import CCConnectBridgeError
from agent.db.connection import get_db_connection
from agent.db.repos import IssueRepo
from agent.models import Issue, IssueCreate, IssueStatus
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


@router.get("/cc-connect/projects")
async def list_cc_connect_projects(request: Request):
    try:
        projects = await _get_runtime(request).list_projects()
    except CCConnectBridgeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"projects": [{"name": project.name} for project in projects]}


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
        raise HTTPException(status_code=409, detail="Issue is not cancellable")
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
