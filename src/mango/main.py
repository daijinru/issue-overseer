"""Uvicorn startup for the Mango server."""

from __future__ import annotations

import uvicorn

from mango.config import get_settings


def main() -> None:
    """Start the Mango server via uvicorn."""
    settings = get_settings()
    uvicorn.run(
        "mango.server.app:create_app",
        factory=True,
        host="0.0.0.0",
        port=settings.server.port,
    )
