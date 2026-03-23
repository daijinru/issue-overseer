"""Tests for the EventBus in-memory pub/sub."""

from __future__ import annotations

import asyncio

import pytest

from mango.server.event_bus import EventBus


@pytest.mark.asyncio
async def test_subscribe_and_publish():
    """A subscriber should receive events published to its issue."""
    bus = EventBus()
    queue = bus.subscribe("issue-1")

    bus.publish("issue-1", "task_start", {"branch": "agent/abc"})

    event = queue.get_nowait()
    assert event["type"] == "task_start"
    assert event["data"]["branch"] == "agent/abc"
    assert "timestamp" in event


@pytest.mark.asyncio
async def test_multiple_subscribers():
    """All subscribers for the same issue should receive each event."""
    bus = EventBus()
    q1 = bus.subscribe("issue-1")
    q2 = bus.subscribe("issue-1")

    bus.publish("issue-1", "turn_start", {"turn_number": 1})

    for q in (q1, q2):
        event = q.get_nowait()
        assert event["type"] == "turn_start"
        assert event["data"]["turn_number"] == 1


@pytest.mark.asyncio
async def test_unsubscribe():
    """After unsubscribe the queue should no longer receive events."""
    bus = EventBus()
    queue = bus.subscribe("issue-1")
    bus.unsubscribe("issue-1", queue)

    bus.publish("issue-1", "task_end", {})

    assert queue.empty()


@pytest.mark.asyncio
async def test_publish_no_subscribers():
    """Publishing to an issue with no subscribers should not raise."""
    bus = EventBus()
    # Should not raise
    bus.publish("no-such-issue", "task_start", {})


@pytest.mark.asyncio
async def test_queue_full_drops_event():
    """When a subscriber's queue is full the event is silently dropped."""
    bus = EventBus(maxsize=2)
    queue = bus.subscribe("issue-1")

    # Fill the queue
    bus.publish("issue-1", "event_1", {})
    bus.publish("issue-1", "event_2", {})

    # This should be dropped silently (no exception)
    bus.publish("issue-1", "event_3", {})

    assert queue.qsize() == 2
    e1 = queue.get_nowait()
    e2 = queue.get_nowait()
    assert e1["type"] == "event_1"
    assert e2["type"] == "event_2"


@pytest.mark.asyncio
async def test_subscriber_count():
    """subscriber_count reflects active subscribers."""
    bus = EventBus()
    assert bus.subscriber_count("issue-1") == 0

    q1 = bus.subscribe("issue-1")
    assert bus.subscriber_count("issue-1") == 1

    q2 = bus.subscribe("issue-1")
    assert bus.subscriber_count("issue-1") == 2

    bus.unsubscribe("issue-1", q1)
    assert bus.subscriber_count("issue-1") == 1

    bus.unsubscribe("issue-1", q2)
    assert bus.subscriber_count("issue-1") == 0


@pytest.mark.asyncio
async def test_publish_different_issues():
    """Events should be isolated between different issues."""
    bus = EventBus()
    q1 = bus.subscribe("issue-1")
    q2 = bus.subscribe("issue-2")

    bus.publish("issue-1", "task_start", {"for": "1"})
    bus.publish("issue-2", "task_start", {"for": "2"})

    e1 = q1.get_nowait()
    e2 = q2.get_nowait()
    assert e1["data"]["for"] == "1"
    assert e2["data"]["for"] == "2"
    # Each queue should only have one event
    assert q1.empty()
    assert q2.empty()


@pytest.mark.asyncio
async def test_unsubscribe_idempotent():
    """Calling unsubscribe twice should not raise."""
    bus = EventBus()
    queue = bus.subscribe("issue-1")
    bus.unsubscribe("issue-1", queue)
    # Second call should be a no-op
    bus.unsubscribe("issue-1", queue)
