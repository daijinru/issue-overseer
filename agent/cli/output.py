"""Terminal output helpers — ANSI colors, table formatting, status styling."""

from __future__ import annotations

import json
import os
import sys
from typing import Any


# ── ANSI color support ──────────────────────────────────────────────


def _supports_color() -> bool:
    """Check whether the terminal supports ANSI color codes."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


_COLOR = _supports_color()


def _ansi(code: str, text: str) -> str:
    if not _COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def bold(text: str) -> str:
    return _ansi("1", text)


def dim(text: str) -> str:
    return _ansi("2", text)


def red(text: str) -> str:
    return _ansi("31", text)


def green(text: str) -> str:
    return _ansi("32", text)


def yellow(text: str) -> str:
    return _ansi("33", text)


def blue(text: str) -> str:
    return _ansi("34", text)


def cyan(text: str) -> str:
    return _ansi("36", text)


def gray(text: str) -> str:
    return _ansi("90", text)


# ── Status styling ──────────────────────────────────────────────────

_STATUS_COLORS: dict[str, Any] = {
    "open": cyan,
    "planning": blue,
    "planned": blue,
    "running": blue,
    "review": green,
    "done": green,
    "waiting_human": yellow,
    "cancelled": gray,
    "failed": red,
}

_PRIORITY_COLORS: dict[str, Any] = {
    "high": red,
    "medium": yellow,
    "low": gray,
}


def styled_status(status: str) -> str:
    """Return a colored status string."""
    fn = _STATUS_COLORS.get(status, str)
    return fn(status)


def styled_priority(priority: str) -> str:
    """Return a colored priority string."""
    fn = _PRIORITY_COLORS.get(priority, str)
    return fn(priority)


# ── Table rendering ─────────────────────────────────────────────────


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    """Print a simple aligned table to stdout."""
    if not rows:
        print(dim("(no results)"))
        return

    # Calculate column widths
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            # Strip ANSI for width calculation
            plain = _strip_ansi(cell)
            widths[i] = max(widths[i], len(plain))

    # Header
    header_line = "  ".join(bold(h.ljust(w)) for h, w in zip(headers, widths))
    print(header_line)
    print(dim("─" * (sum(widths) + 2 * (len(widths) - 1))))

    # Rows
    for row in rows:
        parts = []
        for i, cell in enumerate(row):
            plain = _strip_ansi(cell)
            padding = widths[i] - len(plain)
            parts.append(cell + " " * padding)
        print("  ".join(parts))


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences for width calculation."""
    import re
    return re.sub(r"\033\[[0-9;]*m", "", text)


# ── JSON output ─────────────────────────────────────────────────────


def print_json(data: Any) -> None:
    """Print data as formatted JSON."""
    print(json.dumps(data, indent=2, ensure_ascii=False))


# ── Issue display ───────────────────────────────────────────────────


def print_issue_detail(issue: dict) -> None:
    """Print a single issue in detail view."""
    print(f"{bold('ID:')}          {issue['id']}")
    print(f"{bold('Title:')}       {issue['title']}")
    print(f"{bold('Status:')}      {styled_status(issue['status'])}")
    print(f"{bold('Priority:')}    {styled_priority(issue.get('priority', 'medium'))}")
    if issue.get("description"):
        print(f"{bold('Description:')} {issue['description']}")
    if issue.get("workspace"):
        print(f"{bold('Workspace:')}   {issue['workspace']}")
    if issue.get("branch_name"):
        print(f"{bold('Branch:')}      {issue['branch_name']}")
    if issue.get("pr_url"):
        print(f"{bold('PR:')}          {issue['pr_url']}")
    if issue.get("failure_reason"):
        print(f"{bold('Failure:')}     {red(issue['failure_reason'])}")
    if issue.get("human_instruction"):
        print(f"{bold('Instruction:')} {issue['human_instruction']}")
    if issue.get("created_at"):
        print(f"{bold('Created:')}     {issue['created_at']}")
    if issue.get("updated_at"):
        print(f"{bold('Updated:')}     {issue['updated_at']}")
    if issue.get("spec"):
        print(f"\n{bold('── Spec ──')}")
        print(issue["spec"])


def print_issue_row(issue: dict) -> list[str]:
    """Return a table row for an issue."""
    return [
        issue["id"][:8],
        styled_status(issue["status"]),
        styled_priority(issue.get("priority", "medium")),
        issue["title"][:50],
    ]


def print_issues_table(issues: list[dict]) -> None:
    """Print a list of issues as a table."""
    headers = ["ID", "STATUS", "PRIORITY", "TITLE"]
    rows = [print_issue_row(i) for i in issues]
    print_table(headers, rows)


# ── Log / step display ──────────────────────────────────────────────

_LOG_LEVEL_COLORS: dict[str, Any] = {
    "info": blue,
    "warn": yellow,
    "error": red,
}


def print_logs(logs: list[dict]) -> None:
    """Print execution logs."""
    if not logs:
        print(dim("(no logs)"))
        return
    for log in logs:
        level = log.get("level", "info")
        color_fn = _LOG_LEVEL_COLORS.get(level, str)
        tag = color_fn(f"[{level.upper()}]")
        ts = gray(log.get("created_at", "")[:19]) if log.get("created_at") else ""
        print(f"{ts}  {tag}  {log.get('message', '')}")


_STEP_ICONS: dict[str, str] = {
    "tool_use": "🔧",
    "text": "💬",
    "step": "▸",
}


def print_steps(steps: list[dict]) -> None:
    """Print execution steps."""
    if not steps:
        print(dim("(no steps)"))
        return
    for step in steps:
        icon = _STEP_ICONS.get(step.get("step_type", ""), "▸")
        tool = step.get("tool") or ""
        target = step.get("target") or ""
        summary = step.get("summary") or ""
        parts = [p for p in [tool, target, summary] if p]
        print(f"  {icon} {' '.join(parts)}")


# ── Error display ───────────────────────────────────────────────────


def print_error(message: str) -> None:
    """Print an error message to stderr."""
    print(red(f"Error: {message}"), file=sys.stderr)


def print_success(message: str) -> None:
    """Print a success message."""
    print(green(message))
