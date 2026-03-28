"""FastAPI application factory for Mango Gateway."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mango_gateway.config import get_settings
from mango_gateway.db.connection import close_shared_connection, init_db
from mango_gateway.server.routes import router
from mango_gateway.service.gateway import GatewayService
from mango_gateway.service.runtime_client import RuntimeClient

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: initialize DB, RuntimeClient, GatewayService."""
    settings = get_settings()

    # Initialize Gateway database
    await init_db()

    # Create RuntimeClient (HTTP client to Agent Runtime)
    runtime_client = RuntimeClient(
        base_url=settings.runtime.url,
        timeout=settings.runtime.timeout,
    )
    app.state.runtime_client = runtime_client

    # Create GatewayService
    gateway = GatewayService(
        runtime_client=runtime_client,
        settings=settings,
    )
    app.state.gateway = gateway

    # Check Runtime connectivity at startup
    runtime_ok = await runtime_client.health_check()
    if runtime_ok:
        logger.info("Runtime at %s is reachable", settings.runtime.url)
    else:
        logger.warning(
            "Runtime at %s is NOT reachable — Gateway will start anyway",
            settings.runtime.url,
        )

    # Start session cleanup background task
    cleanup_task = asyncio.create_task(gateway.run_cleanup_loop())
    app.state.cleanup_task = cleanup_task

    yield

    # Shutdown: cancel cleanup, close clients and DB
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    await runtime_client.close()
    await close_shared_connection()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Mango Gateway",
        description="Gateway Service — session management, message routing, external integration.",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS — allow all origins for dev convenience (tighten in production)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    return app
