"""API routes for Mango Gateway."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from mango_gateway.models import (
    GatewayMessageSend,
    GatewayReply,
    Message,
    Session,
    SessionCreate,
)

router = APIRouter(prefix="/api")


def _get_gateway(request: Request):
    """Get the GatewayService from app state."""
    gateway = getattr(request.app.state, "gateway", None)
    if gateway is None:
        raise HTTPException(
            status_code=503, detail="Gateway service not initialized"
        )
    return gateway


# ── Health check ─────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: str
    version: str
    runtime_ok: bool


@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request) -> HealthResponse:
    """Health check with Runtime connectivity probe."""
    gateway = _get_gateway(request)
    runtime_ok = await gateway.runtime.health_check()
    return HealthResponse(
        status="ok",
        version="0.1.0",
        runtime_ok=runtime_ok,
    )


# ── Session endpoints ────────────────────────────────────────────────


@router.post("/gateway/sessions", response_model=Session, status_code=201)
async def create_session(data: SessionCreate, request: Request):
    """Create a new gateway session."""
    gateway = _get_gateway(request)
    return await gateway.create_session(data)


@router.get("/gateway/sessions/{session_id}", response_model=Session)
async def get_session(session_id: str, request: Request):
    """Get session details."""
    gateway = _get_gateway(request)
    session = await gateway.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.post("/gateway/sessions/{session_id}/close", response_model=Session)
async def close_session(session_id: str, request: Request):
    """Close a session."""
    gateway = _get_gateway(request)
    try:
        return await gateway.close_session(session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get(
    "/gateway/sessions/{session_id}/messages", response_model=list[Message]
)
async def get_session_messages(session_id: str, request: Request):
    """Get all messages in a session."""
    gateway = _get_gateway(request)
    session = await gateway.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return await gateway.get_session_messages(session_id)


@router.get("/gateway/sessions/{session_id}/stream")
async def stream_session_events(session_id: str, request: Request):
    """SSE proxy — forward Runtime's Issue SSE events to Gateway clients.

    Connects to the Runtime's GET /api/issues/{id}/stream and relays
    events to the caller.
    """
    gateway = _get_gateway(request)
    session = await gateway.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.current_issue_id is None:
        raise HTTPException(
            status_code=404, detail="No active issue for this session"
        )

    async def proxy_generator():
        try:
            async for event in gateway.runtime.stream_issue_events(
                session.current_issue_id
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                # Stop on terminal events
                event_type = event.get("type")
                if event_type in ("task_end", "task_cancelled"):
                    break
        except Exception:
            yield f"data: {json.dumps({'type': 'error', 'message': 'SSE stream error'})}\n\n"

    return StreamingResponse(
        proxy_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Message endpoint (core) ─────────────────────────────────────────


@router.post("/gateway/messages", response_model=GatewayReply)
async def send_message(data: GatewayMessageSend, request: Request):
    """Core endpoint: send a message, route to Agent Runtime.

    - ``wait=false`` (default): Returns immediately with session_id and issue_id.
      Use the SSE stream endpoint to monitor progress.
    - ``wait=true``: Blocks until the task completes (or times out).
      Returns the execution result, PR URL, etc.
    """
    gateway = _get_gateway(request)
    try:
        return await gateway.send_message(data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
