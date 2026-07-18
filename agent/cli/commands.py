"""Command handlers for the simplified Issue CLI."""

from __future__ import annotations

import argparse

from agent.cli.client import MangoClient
from agent.cli.output import (
    bold, green, print_issue_detail, print_issues_table, print_json,
    print_success,
)


def _make_client(args: argparse.Namespace) -> MangoClient:
    return MangoClient(args.server_url)


def cmd_serve(args: argparse.Namespace) -> None:
    from agent.main import main as start_server
    if args.port:
        import os
        from agent.config import get_settings
        os.environ["SERVER__PORT"] = str(args.port)
        get_settings.cache_clear()
    start_server()


def cmd_health(args: argparse.Namespace) -> None:
    client = _make_client(args)
    try:
        data = client.health()
        print_success(f"status={data.get('status', '?')}  version={data.get('version', '?')}")
    finally:
        client.close()


def cmd_issue_create(args: argparse.Namespace) -> None:
    client = _make_client(args)
    try:
        issue = client.create_issue(args.content, args.project)
        if args.json_output:
            print_json(issue)
        else:
            print(f"{green('Created')} Issue {bold(issue['id'][:8])} — {issue['content']}")
    finally:
        client.close()


def cmd_issue_list(args: argparse.Namespace) -> None:
    client = _make_client(args)
    try:
        issues = client.list_issues(status=args.status)
        print_json(issues) if args.json_output else print_issues_table(issues)
    finally:
        client.close()


def cmd_issue_show(args: argparse.Namespace) -> None:
    client = _make_client(args)
    try:
        issue = client.get_issue(args.id)
        print_json(issue) if args.json_output else print_issue_detail(issue)
    finally:
        client.close()


def cmd_issue_delete(args: argparse.Namespace) -> None:
    client = _make_client(args)
    try:
        client.delete_issue(args.id)
        print_success(f"Issue {args.id[:8]} 已删除")
    finally:
        client.close()


def cmd_issue_run(args: argparse.Namespace) -> None:
    client = _make_client(args)
    try:
        result = client.run_issue(args.id)
        print(result.get("message", "任务已启动"))
    finally:
        client.close()


def cmd_issue_cancel(args: argparse.Namespace) -> None:
    client = _make_client(args)
    try:
        print_success(client.cancel_issue(args.id).get("message", "取消信号已发送"))
    finally:
        client.close()
