"""Argument parser for the simplified Issue CLI."""

from __future__ import annotations

import argparse
import os
import sys

from agent import __version__
from agent.cli.commands import (
    cmd_health, cmd_issue_cancel, cmd_issue_create, cmd_issue_delete,
    cmd_issue_list, cmd_issue_run, cmd_issue_show, cmd_serve,
)


def _resolve_server_url(args: argparse.Namespace) -> str:
    if getattr(args, "server", None):
        return args.server
    return os.environ.get("MANGO_SERVER_URL", "http://localhost:18800")


def _add_issue_commands(subparsers) -> None:
    create = subparsers.add_parser("create", help="创建 Issue")
    create.add_argument("content", help="任务内容")
    create.add_argument("project", help="cc-connect project")
    create.add_argument("--json", dest="json_output", action="store_true")
    create.set_defaults(func=cmd_issue_create)

    listing = subparsers.add_parser("list", help="列出 Issue")
    listing.add_argument("-s", "--status", choices=["pending", "running", "finished"])
    listing.add_argument("--json", dest="json_output", action="store_true")
    listing.set_defaults(func=cmd_issue_list)

    show = subparsers.add_parser("show", help="查看 Issue")
    show.add_argument("id")
    show.add_argument("--json", dest="json_output", action="store_true")
    show.set_defaults(func=cmd_issue_show)

    delete = subparsers.add_parser("delete", help="删除 Issue")
    delete.add_argument("id")
    delete.set_defaults(func=cmd_issue_delete)

    run = subparsers.add_parser("run", help="触发执行")
    run.add_argument("id")
    run.set_defaults(func=cmd_issue_run)

    cancel = subparsers.add_parser("cancel", help="取消执行")
    cancel.add_argument("id")
    cancel.set_defaults(func=cmd_issue_cancel)

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mango", description="Mango CLI")
    parser.add_argument("--version", action="version", version=f"mango {__version__}")
    parser.add_argument("--server", metavar="URL")
    commands = parser.add_subparsers(dest="command")
    serve = commands.add_parser("serve")
    serve.add_argument("--port", type=int)
    serve.set_defaults(func=cmd_serve)
    health = commands.add_parser("health")
    health.set_defaults(func=cmd_health)
    issue = commands.add_parser("issue")
    _add_issue_commands(issue.add_subparsers(dest="issue_command"))
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not hasattr(args, "func"):
        build_parser().print_help()
        sys.exit(0)
    args.server_url = _resolve_server_url(args)
    args.func(args)
