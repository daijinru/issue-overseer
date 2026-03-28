"""Uvicorn startup for the Mango Gateway server."""

from __future__ import annotations

import uvicorn

from mango_gateway.config import get_settings


def main() -> None:
    """Start the Mango Gateway server via uvicorn."""
    settings = get_settings()
    uvicorn.run(
        "mango_gateway.server.app:create_app",
        factory=True,
        host=settings.server.host,
        port=settings.server.port,
    )
