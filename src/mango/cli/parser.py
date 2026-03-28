"""Argparse command tree for the Mango CLI."""

from __future__ import annotations

import argparse
import os
import sys

from mango import __version__
from mango.cli.commands import (
    cmd_health,
    cmd_issue_cancel,
    cmd_issue_complete,
    cmd_issue_create,
    cmd_issue_delete,
    cmd_issue_edit,
    cmd_issue_list,
    cmd_issue_logs,
    cmd_issue_plan,
    cmd_issue_retry,
    cmd_issue_run,
    cmd_issue_show,
    cmd_issue_spec,
    cmd_issue_steps,
    cmd_serve,
)


def _resolve_server_url(args: argparse.Namespace) -> str:
    """Resolve the Mango server URL from flags → env → config → default."""
    # 1. --server flag (set on the top-level parser)
    if getattr(args, "server", None):
        return args.server

    # 2. Environment variable
    env_url = os.environ.get("MANGO_SERVER_URL")
    if env_url:
        return env_url

    # 3. Read from overseer.toml
    try:
        from mango.config import get_settings
        settings = get_settings()
        port = settings.server.port
        return f"http://localhost:{port}"
    except Exception:
        pass

    # 4. Default
    return "http://localhost:18800"


def build_parser() -> argparse.ArgumentParser:
    """Build the complete CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="mango",
        description="Mango CLI — Issue in, code out.",
    )
    parser.add_argument(
        "--version", action="version", version=f"mango {__version__}"
    )
    parser.add_argument(
        "--server",
        metavar="URL",
        help="Mango server URL (default: from MANGO_SERVER_URL or overseer.toml)",
    )

    subparsers = parser.add_subparsers(dest="command")

    # ── serve ───────────────────────────────────────────────────────
    p_serve = subparsers.add_parser("serve", help="启动 Mango 服务器")
    p_serve.add_argument("--port", type=int, help="监听端口")
    p_serve.set_defaults(func=cmd_serve)

    # ── health ──────────────────────────────────────────────────────
    p_health = subparsers.add_parser("health", help="服务器健康检查")
    p_health.set_defaults(func=cmd_health)

    # ── issue (group) ───────────────────────────────────────────────
    p_issue = subparsers.add_parser("issue", help="Issue 管理")
    issue_sub = p_issue.add_subparsers(dest="issue_command")

    # issue create
    p_create = issue_sub.add_parser("create", help="创建 Issue")
    p_create.add_argument("title", help="Issue 标题")
    p_create.add_argument("-d", "--desc", default="", help="描述")
    p_create.add_argument("-w", "--workspace", help="工作目录路径")
    p_create.add_argument(
        "-p", "--priority", choices=["high", "medium", "low"], help="优先级"
    )
    p_create.add_argument("--json", dest="json_output", action="store_true", help="JSON 输出")
    p_create.set_defaults(func=cmd_issue_create)

    # issue list
    p_list = issue_sub.add_parser("list", help="列出 Issue")
    p_list.add_argument("-s", "--status", help="按状态筛选")
    p_list.add_argument("-p", "--priority", choices=["high", "medium", "low"], help="按优先级筛选")
    p_list.add_argument("--json", dest="json_output", action="store_true", help="JSON 输出")
    p_list.set_defaults(func=cmd_issue_list)

    # issue show
    p_show = issue_sub.add_parser("show", help="查看 Issue 详情")
    p_show.add_argument("id", help="Issue ID")
    p_show.add_argument("--json", dest="json_output", action="store_true", help="JSON 输出")
    p_show.set_defaults(func=cmd_issue_show)

    # issue edit
    p_edit = issue_sub.add_parser("edit", help="编辑 Issue")
    p_edit.add_argument("id", help="Issue ID")
    p_edit.add_argument("--title", help="新标题")
    p_edit.add_argument("-d", "--desc", help="新描述")
    p_edit.add_argument(
        "-p", "--priority", choices=["high", "medium", "low"], help="新优先级"
    )
    p_edit.add_argument("--json", dest="json_output", action="store_true", help="JSON 输出")
    p_edit.set_defaults(func=cmd_issue_edit)

    # issue delete
    p_del = issue_sub.add_parser("delete", help="删除 Issue")
    p_del.add_argument("id", help="Issue ID")
    p_del.add_argument("-y", "--yes", action="store_true", help="跳过确认")
    p_del.set_defaults(func=cmd_issue_delete)

    # issue run
    p_run = issue_sub.add_parser("run", help="触发执行")
    p_run.add_argument("id", help="Issue ID")
    p_run.add_argument("--no-stream", action="store_true", help="不流式输出")
    p_run.set_defaults(func=cmd_issue_run)

    # issue cancel
    p_cancel = issue_sub.add_parser("cancel", help="取消执行")
    p_cancel.add_argument("id", help="Issue ID")
    p_cancel.set_defaults(func=cmd_issue_cancel)

    # issue retry
    p_retry = issue_sub.add_parser("retry", help="重试 (waiting_human)")
    p_retry.add_argument("id", help="Issue ID")
    p_retry.add_argument("-m", "--message", help="附加指令")
    p_retry.add_argument("-w", "--workspace", help="工作目录路径")
    p_retry.add_argument("--no-stream", action="store_true", help="不流式输出")
    p_retry.set_defaults(func=cmd_issue_retry)

    # issue plan
    p_plan = issue_sub.add_parser("plan", help="生成 Spec")
    p_plan.add_argument("id", help="Issue ID")
    p_plan.add_argument("--no-stream", action="store_true", help="不流式输出")
    p_plan.set_defaults(func=cmd_issue_plan)

    # issue spec
    p_spec = issue_sub.add_parser("spec", help="查看/编辑 Spec")
    p_spec.add_argument("id", help="Issue ID")
    p_spec.add_argument("--edit", help="Spec 内容 (字符串)")
    p_spec.add_argument("--edit-file", help="从文件读取 Spec")
    p_spec.add_argument("--reject", action="store_true", help="驳回 Spec")
    p_spec.add_argument("--json", dest="json_output", action="store_true", help="JSON 输出")
    p_spec.set_defaults(func=cmd_issue_spec)

    # issue complete
    p_complete = issue_sub.add_parser("complete", help="标记 review → done")
    p_complete.add_argument("id", help="Issue ID")
    p_complete.set_defaults(func=cmd_issue_complete)

    # issue logs
    p_logs = issue_sub.add_parser("logs", help="查看执行日志")
    p_logs.add_argument("id", help="Issue ID")
    p_logs.add_argument("--json", dest="json_output", action="store_true", help="JSON 输出")
    p_logs.set_defaults(func=cmd_issue_logs)

    # issue steps
    p_steps = issue_sub.add_parser("steps", help="查看执行步骤")
    p_steps.add_argument("id", help="Issue ID")
    p_steps.add_argument("--json", dest="json_output", action="store_true", help="JSON 输出")
    p_steps.set_defaults(func=cmd_issue_steps)

    # ── Top-level shortcuts ─────────────────────────────────────────

    # mango run <id> → mango issue run <id>
    p_run_short = subparsers.add_parser("run", help="快捷方式: issue run")
    p_run_short.add_argument("id", help="Issue ID")
    p_run_short.add_argument("--no-stream", action="store_true", help="不流式输出")
    p_run_short.set_defaults(func=cmd_issue_run)

    # mango list → mango issue list
    p_list_short = subparsers.add_parser("list", help="快捷方式: issue list")
    p_list_short.add_argument("-s", "--status", help="按状态筛选")
    p_list_short.add_argument("-p", "--priority", choices=["high", "medium", "low"], help="按优先级筛选")
    p_list_short.add_argument("--json", dest="json_output", action="store_true", help="JSON 输出")
    p_list_short.set_defaults(func=cmd_issue_list)

    # mango create <title> → mango issue create <title>
    p_create_short = subparsers.add_parser("create", help="快捷方式: issue create")
    p_create_short.add_argument("title", help="Issue 标题")
    p_create_short.add_argument("-d", "--desc", default="", help="描述")
    p_create_short.add_argument("-w", "--workspace", help="工作目录路径")
    p_create_short.add_argument(
        "-p", "--priority", choices=["high", "medium", "low"], help="优先级"
    )
    p_create_short.add_argument("--json", dest="json_output", action="store_true", help="JSON 输出")
    p_create_short.set_defaults(func=cmd_issue_create)

    return parser


def main() -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()

    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(0)

    # Resolve server URL and attach to args
    args.server_url = _resolve_server_url(args)

    args.func(args)
