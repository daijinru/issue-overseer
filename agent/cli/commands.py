"""CLI command handlers — one function per subcommand."""

from __future__ import annotations

import argparse
import sys

from agent.cli.client import MangoClient
from agent.cli.output import (
    bold,
    dim,
    green,
    print_error,
    print_issue_detail,
    print_issues_table,
    print_json,
    print_logs,
    print_steps,
    print_success,
    yellow,
)
from agent.cli.stream import consume_sse_stream


def _make_client(args: argparse.Namespace) -> MangoClient:
    """Create a MangoClient from the resolved server URL."""
    return MangoClient(args.server_url)


# ── serve ───────────────────────────────────────────────────────────


def cmd_serve(args: argparse.Namespace) -> None:
    """Start the Mango server."""
    from agent.main import main as start_server

    if args.port:
        # Override port via environment so get_settings() picks it up
        import os
        os.environ["SERVER__PORT"] = str(args.port)
        # Clear the cached settings so the new port takes effect
        from agent.config import get_settings
        get_settings.cache_clear()

    start_server()


# ── health ──────────────────────────────────────────────────────────


def cmd_health(args: argparse.Namespace) -> None:
    """Check server health."""
    client = _make_client(args)
    try:
        data = client.health()
        print_success(f"status={data.get('status', '?')}  version={data.get('version', '?')}")
    finally:
        client.close()


# ── issue create ────────────────────────────────────────────────────


def cmd_issue_create(args: argparse.Namespace) -> None:
    """Create a new issue."""
    client = _make_client(args)
    try:
        issue = client.create_issue(
            title=args.title,
            description=getattr(args, "desc", "") or "",
            workspace=getattr(args, "workspace", None),
            priority=getattr(args, "priority", None),
        )
        if getattr(args, "json_output", False):
            print_json(issue)
        else:
            print(f"{green('Created')} Issue {bold(issue['id'][:8])} — {issue['title']}")
    finally:
        client.close()


# ── issue list ──────────────────────────────────────────────────────


def cmd_issue_list(args: argparse.Namespace) -> None:
    """List issues."""
    client = _make_client(args)
    try:
        issues = client.list_issues(
            status=getattr(args, "status", None),
            priority=getattr(args, "priority", None),
        )
        if getattr(args, "json_output", False):
            print_json(issues)
        else:
            print_issues_table(issues)
    finally:
        client.close()


# ── issue show ──────────────────────────────────────────────────────


def cmd_issue_show(args: argparse.Namespace) -> None:
    """Show issue detail."""
    client = _make_client(args)
    try:
        issue = client.get_issue(args.id)
        if getattr(args, "json_output", False):
            print_json(issue)
        else:
            print_issue_detail(issue)
    finally:
        client.close()


# ── issue edit ──────────────────────────────────────────────────────


def cmd_issue_edit(args: argparse.Namespace) -> None:
    """Edit an issue's title, description, or priority."""
    title = getattr(args, "title", None)
    desc = getattr(args, "desc", None)
    priority = getattr(args, "priority", None)

    if not any([title, desc, priority]):
        print_error("至少指定一个要修改的字段: --title, -d/--desc, -p/--priority")
        sys.exit(1)

    client = _make_client(args)
    try:
        issue = client.edit_issue(
            args.id,
            title=title,
            description=desc,
            priority=priority,
        )
        if getattr(args, "json_output", False):
            print_json(issue)
        else:
            print_success(f"Issue {args.id[:8]} 已更新")
            print_issue_detail(issue)
    finally:
        client.close()


# ── issue delete ────────────────────────────────────────────────────


def cmd_issue_delete(args: argparse.Namespace) -> None:
    """Delete an issue."""
    if not getattr(args, "yes", False):
        confirm = input(f"确认删除 Issue {args.id[:8]}? [y/N] ").strip().lower()
        if confirm not in ("y", "yes"):
            print("已取消")
            return

    client = _make_client(args)
    try:
        client.delete_issue(args.id)
        print_success(f"Issue {args.id[:8]} 已删除")
    finally:
        client.close()


# ── issue run ───────────────────────────────────────────────────────


def cmd_issue_run(args: argparse.Namespace) -> None:
    """Trigger issue execution."""
    client = _make_client(args)
    try:
        result = client.run_issue(args.id)
        print(f"🚀 {result.get('message', '任务已启动')} (Issue {args.id[:8]})")

        if not getattr(args, "no_stream", False):
            _stream_issue(client, args.id)
    finally:
        client.close()


# ── issue cancel ────────────────────────────────────────────────────


def cmd_issue_cancel(args: argparse.Namespace) -> None:
    """Cancel a running issue."""
    client = _make_client(args)
    try:
        result = client.cancel_issue(args.id)
        print_success(result.get("message", "取消信号已发送"))
    finally:
        client.close()


# ── issue retry ─────────────────────────────────────────────────────


def cmd_issue_retry(args: argparse.Namespace) -> None:
    """Retry a waiting_human issue with optional instruction."""
    client = _make_client(args)
    try:
        result = client.retry_issue(
            args.id,
            instruction=getattr(args, "message", None),
            workspace=getattr(args, "workspace", None),
        )
        print(f"🔄 {result.get('message', '重试已启动')} (Issue {args.id[:8]})")

        if not getattr(args, "no_stream", False):
            _stream_issue(client, args.id)
    finally:
        client.close()


# ── issue plan ──────────────────────────────────────────────────────


def cmd_issue_plan(args: argparse.Namespace) -> None:
    """Generate Spec for an issue."""
    client = _make_client(args)
    try:
        result = client.plan_issue(args.id)
        print(f"📋 {result.get('message', 'Spec 生成已启动')} (Issue {args.id[:8]})")

        if not getattr(args, "no_stream", False):
            _stream_issue(client, args.id)
    finally:
        client.close()


# ── issue spec ──────────────────────────────────────────────────────


def cmd_issue_spec(args: argparse.Namespace) -> None:
    """View or modify an issue's spec."""
    client = _make_client(args)
    try:
        # Reject spec
        if getattr(args, "reject", False):
            issue = client.reject_spec(args.id)
            print_success(f"Spec 已驳回，Issue {args.id[:8]} 回到 open 状态")
            return

        # Edit spec from file
        edit_file = getattr(args, "edit_file", None)
        if edit_file:
            try:
                with open(edit_file) as f:
                    spec_content = f.read()
            except FileNotFoundError:
                print_error(f"文件不存在: {edit_file}")
                sys.exit(1)
            issue = client.update_spec(args.id, spec_content)
            print_success(f"Spec 已更新 (Issue {args.id[:8]})")
            return

        # Edit spec from argument
        edit_content = getattr(args, "edit", None)
        if edit_content:
            issue = client.update_spec(args.id, edit_content)
            print_success(f"Spec 已更新 (Issue {args.id[:8]})")
            return

        # Default: show spec
        issue = client.get_spec(args.id)
        spec = issue.get("spec")
        if spec:
            print(f"{bold('── Spec ──')} (Issue {args.id[:8]})\n")
            print(spec)
        else:
            print(dim(f"Issue {args.id[:8]} 暂无 Spec"))
    finally:
        client.close()


# ── issue complete ──────────────────────────────────────────────────


def cmd_issue_complete(args: argparse.Namespace) -> None:
    """Mark a review issue as done."""
    client = _make_client(args)
    try:
        issue = client.complete_issue(args.id)
        print_success(f"Issue {args.id[:8]} → done ✓")
    finally:
        client.close()


# ── issue logs ──────────────────────────────────────────────────────


def cmd_issue_logs(args: argparse.Namespace) -> None:
    """Show execution logs."""
    client = _make_client(args)
    try:
        logs = client.get_logs(args.id)
        if getattr(args, "json_output", False):
            print_json(logs)
        else:
            print_logs(logs)
    finally:
        client.close()


# ── issue steps ─────────────────────────────────────────────────────


def cmd_issue_steps(args: argparse.Namespace) -> None:
    """Show execution steps."""
    client = _make_client(args)
    try:
        steps = client.get_steps(args.id)
        if getattr(args, "json_output", False):
            print_json(steps)
        else:
            print_steps(steps)
    finally:
        client.close()


# ── SSE streaming helper ────────────────────────────────────────────


def _stream_issue(client: MangoClient, issue_id: str) -> None:
    """Connect to SSE stream and render events until done."""
    with client.stream_events(issue_id) as response:
        consume_sse_stream(response, issue_id)
