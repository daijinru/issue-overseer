"""API routes for Mango."""

from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter

from mango.db.connection import get_db_connection

router = APIRouter(prefix="/api")


# ── Health check ─────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: str
    version: str


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check — verifies the server is running and DB is reachable."""
    async with get_db_connection() as db:
        await db.execute("SELECT 1")

    return HealthResponse(status="ok", version="0.1.0")
