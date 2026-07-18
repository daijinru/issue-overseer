"""Tests for the simplified Issue CLI."""

from __future__ import annotations

import pytest

from agent.cli.output import print_issue_detail, print_issues_table
from agent.cli.parser import build_parser


def test_create_accepts_content_and_project():
    args = build_parser().parse_args(["issue", "create", "fix login", "api"])

    assert args.content == "fix login"
    assert args.project == "api"


def test_retired_cli_actions_are_not_registered():
    parser = build_parser()

    for action in ("edit", "retry", "plan", "spec", "complete", "logs", "steps"):
        with pytest.raises(SystemExit):
            parser.parse_args(["issue", action, "issue-1"])


def test_issue_output_displays_project_and_content(capsys):
    issue = {"id": "abc123", "project": "api", "content": "fix login", "status": "pending"}

    print_issue_detail(issue)
    print_issues_table([issue])

    output = capsys.readouterr().out
    assert "Project:" in output
    assert "fix login" in output
