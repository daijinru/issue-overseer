"""In-memory event bus for per-issue pub/sub (SSE backing store)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class EventBus:
    """Per-issue pub/sub built on asyncio.Queue.

    Each subscriber gets its own queue.  ``publish()`` fans out to every
    queue that is currently subscribed to the given *issue_id*.
    """

    def __init__(self, maxsize: int = 1000) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[dict]]] = {}
        self._maxsize = maxsize

    # ── public API ──────────────────────────────────────────────────

    def subscribe(self, issue_id: str) -> asyncio.Queue[dict]:
        """Create and register a new queue for *issue_id*."""
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=self._maxsize)
        self._subscribers.setdefault(issue_id, []).append(queue)
        logger.debug("SSE subscriber added for issue %s (total: %d)",
                      issue_id, len(self._subscribers[issue_id]))
        return queue

    def unsubscribe(self, issue_id: str, queue: asyncio.Queue[dict]) -> None:
        """Remove *queue* from *issue_id* subscribers."""
        queues = self._subscribers.get(issue_id, [])
        try:
            queues.remove(queue)
        except ValueError:
            pass  # already removed
        if not queues:
            self._subscribers.pop(issue_id, None)
        logger.debug("SSE subscriber removed for issue %s", issue_id)

    def publish(self, issue_id: str, event_type: str, data: dict | None = None) -> None:
        """Broadcast an event to all subscribers of *issue_id*.

        If a subscriber's queue is full the event is silently dropped
        for that subscriber (back-pressure safety).
        """
        event = {
            "type": event_type,
            "data": data or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        queues = self._subscribers.get(issue_id, [])
        for q in queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "SSE queue full for issue %s, dropping event %s",
                    issue_id, event_type,
                )

    def subscriber_count(self, issue_id: str) -> int:
        """Return the number of active subscribers for *issue_id*."""
        return len(self._subscribers.get(issue_id, []))
