"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mango.db.connection import close_shared_connection, init_db
from mango.server.event_bus import EventBus
from mango.server.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: initialize DB and Agent Runtime on startup."""
    await init_db()
    event_bus = EventBus()
    app.state.event_bus = event_bus
    from mango.agent.runtime import AgentRuntime
    runtime = AgentRuntime(event_bus=event_bus)
    await runtime.recover_from_restart()
    app.state.runtime = runtime
    yield
    if hasattr(app.state, "runtime"):
        await app.state.runtime.client.close()
    await close_shared_connection()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Mango",
        description="AI-driven code generation platform — Issue in, code out.",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS — allow all origins for MVP / frontend dev convenience
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    return app
