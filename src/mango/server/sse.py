"""Server-Sent Events stream generator for issue execution updates."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator

from mango.server.event_bus import EventBus

logger = logging.getLogger(__name__)

# Heartbeat interval in seconds — keeps connection alive through proxies.
_HEARTBEAT_INTERVAL = 30


async def sse_stream(
    event_bus: EventBus, issue_id: str
) -> AsyncGenerator[str, None]:
    """Yield SSE-formatted strings for events on *issue_id*.

    The generator:
    - Subscribes to *issue_id* on the *event_bus*.
    - Sends each event as ``event: <type>\\ndata: <json>\\n\\n``.
    - Sends a heartbeat comment (``: heartbeat``) every 30 s of silence.
    - Terminates when a ``task_end`` or ``task_cancelled`` event is received.
    - Always unsubscribes in ``finally`` to prevent leaks.
    """
    queue = event_bus.subscribe(issue_id)
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_INTERVAL)
            except asyncio.TimeoutError:
                # No event within the heartbeat window — send a keep-alive
                yield ": heartbeat\n\n"
                continue

            event_type: str = event.get("type", "message")
            event_data: dict = event.get("data", {})
            yield f"event: {event_type}\ndata: {json.dumps(event_data)}\n\n"

            # Terminal events — close the stream after delivery
            if event_type in ("task_end", "task_cancelled"):
                return
    except asyncio.CancelledError:
        # Client disconnected (or server shutting down)
        pass
    finally:
        event_bus.unsubscribe(issue_id, queue)
        logger.debug("SSE stream closed for issue %s", issue_id)
