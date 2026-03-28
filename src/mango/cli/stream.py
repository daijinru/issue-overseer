"""SSE stream consumer — parse server-sent events and render to terminal."""

from __future__ import annotations

import json
import sys

import httpx

from mango.cli.output import (
    blue,
    bold,
    dim,
    gray,
    green,
    print_error,
    red,
    yellow,
)


# ── SSE event → terminal mapping ────────────────────────────────────

_TOOL_ICONS: dict[str, str] = {
    "read_file": "📖",
    "write_file": "✏️",
    "edit_file": "✏️",
    "execute_command": "🔧",
    "search": "🔍",
    "list_files": "📂",
}


def _render_event(event_type: str, data: dict) -> str | None:
    """Convert an SSE event to a terminal line. Returns None to skip."""
    if event_type == "task_start":
        branch = data.get("branch", "")
        branch_info = f"  分支: {cyan_text(branch)}" if branch else ""
        return f"\n🚀 {bold('任务开始')}{branch_info}"

    if event_type == "turn_start":
        turn = data.get("turn_number", "?")
        max_turns = data.get("max_turns", "?")
        return f"\n{dim('──')} 第 {turn}/{max_turns} 轮 {dim('──')}"

    if event_type == "opencode_step":
        step_type = data.get("step_type", "")
        if step_type == "tool_use":
            tool = data.get("tool", "")
            target = data.get("target", "")
            summary = data.get("summary", "")
            icon = _TOOL_ICONS.get(tool, "🔧")
            parts = [p for p in [target, summary] if p]
            return f"  {icon} {' '.join(parts)}" if parts else f"  {icon} {tool}"
        if step_type == "text":
            summary = data.get("summary", "")
            return f"  💬 {dim(summary[:120])}" if summary else None
        return None

    if event_type == "turn_end":
        turn = data.get("turn_number", "?")
        max_turns = data.get("max_turns", "?")
        return f"{dim('──')} 第 {turn}/{max_turns} 轮 完成 ✓ {dim('──')}"

    if event_type == "git_commit":
        return f"📦 {dim('Git commit')}"

    if event_type == "git_push":
        return f"📤 {dim('Git push')}"

    if event_type == "pr_created":
        url = data.get("pr_url", "")
        return f"🔗 {bold('PR:')} {url}"

    if event_type == "task_end":
        status = data.get("status", "")
        if status in ("done", "review", "completed"):
            return f"\n✅ {green('任务完成')}"
        reason = data.get("failure_reason", "") or data.get("reason", "")
        return f"\n❌ {red('失败')}: {reason}" if reason else f"\n❌ {red('失败')}"

    if event_type == "task_cancelled":
        return f"\n⚠️  {yellow('已取消')}"

    if event_type == "execution_log":
        level = data.get("level", "info").upper()
        message = data.get("message", "")
        color = {"INFO": blue, "WARN": yellow, "ERROR": red}.get(level, str)
        return f"  {color(f'[{level}]')} {message}"

    if event_type == "plan_start":
        return f"\n📋 {bold('开始生成 Spec...')}"

    if event_type == "plan_end":
        status = data.get("status", "")
        if status == "planned":
            return f"📋 {green('Spec 生成完成')}"
        return f"📋 {red('Spec 生成失败')}"

    # heartbeat and unknown events are silently ignored
    return None


def cyan_text(text: str) -> str:
    """Cyan text helper (avoids circular import)."""
    return f"\033[36m{text}\033[0m"


# ── SSE stream parser ───────────────────────────────────────────────


def consume_sse_stream(response: httpx.Response, issue_id: str) -> None:
    """Parse SSE lines from an httpx streaming response and render them.

    Handles Ctrl+C gracefully — prints a hint instead of auto-cancelling.
    """
    try:
        event_type = ""
        data_buf = ""

        for line in response.iter_lines():
            if line.startswith("event:"):
                event_type = line[6:].strip()
                continue
            if line.startswith("data:"):
                data_buf = line[5:].strip()
                continue
            if line == "" and event_type:
                # End of event block
                _dispatch(event_type, data_buf)
                event_type = ""
                data_buf = ""
    except KeyboardInterrupt:
        print(
            f"\n{yellow('中断流式输出，任务仍在运行。')}"
            f"\n用 {bold(f'mango issue cancel {issue_id}')} 取消任务。"
        )
    except httpx.ReadError:
        # Server closed connection (task ended, etc.)
        pass


def _dispatch(event_type: str, raw_data: str) -> None:
    """Parse data and render a single SSE event."""
    if event_type == "heartbeat":
        return

    data: dict = {}
    if raw_data:
        try:
            data = json.loads(raw_data)
        except json.JSONDecodeError:
            data = {"message": raw_data}

    output = _render_event(event_type, data)
    if output is not None:
        print(output, flush=True)
