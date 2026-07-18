"""Terminal output helpers for simplified Issues."""

from __future__ import annotations

import json
import sys
from typing import Any


def bold(text: str) -> str:
    return text


def dim(text: str) -> str:
    return text


def red(text: str) -> str:
    return text


def green(text: str) -> str:
    return text


def yellow(text: str) -> str:
    return text


def blue(text: str) -> str:
    return text


def gray(text: str) -> str:
    return text


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def print_issue_detail(issue: dict) -> None:
    print(f"ID:      {issue['id']}")
    print(f"Project: {issue['project']}")
    print(f"Status:  {issue['status']}")
    print(f"Content: {issue['content']}")
    if issue.get("outcome"):
        print(f"Outcome: {issue['outcome']}")
    if issue.get("result"):
        print(f"Result:  {issue['result']}")
    if issue.get("error_message"):
        print(f"Error:   {issue['error_message']}")


def print_issues_table(issues: list[dict]) -> None:
    for issue in issues:
        print(f"{issue['id'][:8]}  {issue['status']:8}  {issue['project']:16}  {issue['content']}")
def print_error(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)


def print_success(message: str) -> None:
    print(message)
