"""CLI rendering for the simplified runtime SSE events."""

from __future__ import annotations

from agent.cli.stream import _render_event


def test_task_end_renders_success_from_the_bridge_success_flag():
    rendered = _render_event("task_end", {"success": True})

    assert rendered is not None
    assert "任务完成" in rendered


def test_task_end_renders_the_bridge_error_message():
    rendered = _render_event("task_end", {"success": False, "error": "offline"})

    assert rendered is not None
    assert "offline" in rendered


def test_task_end_does_not_infer_success_from_a_legacy_status():
    rendered = _render_event("task_end", {"status": "done"})

    assert rendered is not None
    assert "任务完成" not in rendered
