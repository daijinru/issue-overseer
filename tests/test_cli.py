"""Tests for the Mango CLI — parser, commands, and output formatting."""

from __future__ import annotations

import json
import sys
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from mango.cli.parser import build_parser, _resolve_server_url
from mango.cli.output import (
    _strip_ansi,
    print_table,
    print_issues_table,
    print_issue_detail,
    print_logs,
    print_steps,
    styled_status,
    styled_priority,
)


# ── Parser tests ────────────────────────────────────────────────────


class TestParser:
    """Test argparse command tree construction."""

    def setup_method(self):
        self.parser = build_parser()

    def test_version(self, capsys):
        with pytest.raises(SystemExit, match="0"):
            self.parser.parse_args(["--version"])
        out = capsys.readouterr().out
        assert "0.1.0" in out

    def test_no_command_has_no_func(self):
        args = self.parser.parse_args([])
        assert not hasattr(args, "func")

    def test_health(self):
        args = self.parser.parse_args(["health"])
        assert args.command == "health"
        assert hasattr(args, "func")

    def test_serve(self):
        args = self.parser.parse_args(["serve"])
        assert args.command == "serve"

    def test_serve_with_port(self):
        args = self.parser.parse_args(["serve", "--port", "9999"])
        assert args.port == 9999

    def test_issue_create(self):
        args = self.parser.parse_args(["issue", "create", "Fix bug"])
        assert args.title == "Fix bug"

    def test_issue_create_with_options(self):
        args = self.parser.parse_args([
            "issue", "create", "Fix bug",
            "-d", "some desc",
            "-w", "/path/to/repo",
            "-p", "high",
        ])
        assert args.title == "Fix bug"
        assert args.desc == "some desc"
        assert args.workspace == "/path/to/repo"
        assert args.priority == "high"

    def test_issue_list(self):
        args = self.parser.parse_args(["issue", "list"])
        assert args.issue_command == "list"

    def test_issue_list_with_filters(self):
        args = self.parser.parse_args(["issue", "list", "-s", "running", "-p", "high"])
        assert args.status == "running"
        assert args.priority == "high"

    def test_issue_show(self):
        args = self.parser.parse_args(["issue", "show", "abc123"])
        assert args.id == "abc123"

    def test_issue_edit(self):
        args = self.parser.parse_args(["issue", "edit", "abc123", "--title", "New title"])
        assert args.id == "abc123"
        assert args.title == "New title"

    def test_issue_delete(self):
        args = self.parser.parse_args(["issue", "delete", "abc123", "-y"])
        assert args.id == "abc123"
        assert args.yes is True

    def test_issue_run(self):
        args = self.parser.parse_args(["issue", "run", "abc123"])
        assert args.id == "abc123"
        assert args.no_stream is False

    def test_issue_run_no_stream(self):
        args = self.parser.parse_args(["issue", "run", "abc123", "--no-stream"])
        assert args.no_stream is True

    def test_issue_cancel(self):
        args = self.parser.parse_args(["issue", "cancel", "abc123"])
        assert args.id == "abc123"

    def test_issue_retry(self):
        args = self.parser.parse_args([
            "issue", "retry", "abc123", "-m", "try again"
        ])
        assert args.id == "abc123"
        assert args.message == "try again"

    def test_issue_plan(self):
        args = self.parser.parse_args(["issue", "plan", "abc123"])
        assert args.id == "abc123"

    def test_issue_spec(self):
        args = self.parser.parse_args(["issue", "spec", "abc123"])
        assert args.id == "abc123"

    def test_issue_spec_reject(self):
        args = self.parser.parse_args(["issue", "spec", "abc123", "--reject"])
        assert args.reject is True

    def test_issue_spec_edit(self):
        args = self.parser.parse_args(["issue", "spec", "abc123", "--edit", "new spec"])
        assert args.edit == "new spec"

    def test_issue_complete(self):
        args = self.parser.parse_args(["issue", "complete", "abc123"])
        assert args.id == "abc123"

    def test_issue_logs(self):
        args = self.parser.parse_args(["issue", "logs", "abc123"])
        assert args.id == "abc123"

    def test_issue_steps(self):
        args = self.parser.parse_args(["issue", "steps", "abc123"])
        assert args.id == "abc123"

    # ── Top-level shortcuts ─────────────────────────────────────────

    def test_shortcut_run(self):
        args = self.parser.parse_args(["run", "abc123"])
        assert args.id == "abc123"

    def test_shortcut_list(self):
        args = self.parser.parse_args(["list"])
        assert hasattr(args, "func")

    def test_shortcut_create(self):
        args = self.parser.parse_args(["create", "Fix bug"])
        assert args.title == "Fix bug"

    # ── --server flag ───────────────────────────────────────────────

    def test_server_flag(self):
        args = self.parser.parse_args(["--server", "http://host:1234", "health"])
        assert args.server == "http://host:1234"

    # ── JSON output flag ────────────────────────────────────────────

    def test_json_flag_on_list(self):
        args = self.parser.parse_args(["issue", "list", "--json"])
        assert args.json_output is True


# ── Server URL resolution tests ─────────────────────────────────────


class TestResolveServerURL:
    def test_flag_takes_precedence(self):
        ns = MagicMock()
        ns.server = "http://custom:8888"
        assert _resolve_server_url(ns) == "http://custom:8888"

    def test_env_fallback(self, monkeypatch):
        monkeypatch.setenv("MANGO_SERVER_URL", "http://env:9999")
        ns = MagicMock()
        ns.server = None
        assert _resolve_server_url(ns) == "http://env:9999"

    def test_default_fallback(self, monkeypatch):
        monkeypatch.delenv("MANGO_SERVER_URL", raising=False)
        ns = MagicMock()
        ns.server = None
        # Patch get_settings at source to fail so we hit the default
        with patch("mango.config.get_settings", side_effect=Exception("no config")):
            url = _resolve_server_url(ns)
        assert url == "http://localhost:18800"


# ── Output formatting tests ─────────────────────────────────────────


class TestOutput:
    def test_strip_ansi(self):
        # colored text
        assert _strip_ansi("\033[31mhello\033[0m") == "hello"
        # plain text
        assert _strip_ansi("hello") == "hello"

    def test_styled_status_known(self):
        result = styled_status("running")
        assert "running" in _strip_ansi(result)

    def test_styled_status_unknown(self):
        result = styled_status("unknown_status")
        assert result == "unknown_status"

    def test_styled_priority(self):
        result = styled_priority("high")
        assert "high" in _strip_ansi(result)

    def test_print_table_empty(self, capsys):
        print_table(["A", "B"], [])
        out = capsys.readouterr().out
        assert "no results" in _strip_ansi(out)

    def test_print_table_with_rows(self, capsys):
        print_table(["ID", "NAME"], [["1", "alice"], ["2", "bob"]])
        out = capsys.readouterr().out
        assert "alice" in out
        assert "bob" in out

    def test_print_issues_table(self, capsys):
        issues = [
            {
                "id": "abc12345-1234-1234-1234-123456789012",
                "title": "Fix login bug",
                "status": "running",
                "priority": "high",
            }
        ]
        print_issues_table(issues)
        out = capsys.readouterr().out
        assert "abc12345" in _strip_ansi(out)
        assert "Fix login" in out

    def test_print_issue_detail(self, capsys):
        issue = {
            "id": "abc12345",
            "title": "Test issue",
            "status": "open",
            "priority": "medium",
            "description": "A test",
            "workspace": "/tmp/repo",
            "branch_name": None,
            "pr_url": None,
            "failure_reason": None,
            "human_instruction": None,
            "created_at": "2025-01-01T00:00:00",
            "updated_at": "2025-01-01T00:00:00",
            "spec": None,
        }
        print_issue_detail(issue)
        out = capsys.readouterr().out
        assert "abc12345" in out
        assert "Test issue" in out

    def test_print_logs_empty(self, capsys):
        print_logs([])
        out = capsys.readouterr().out
        assert "no logs" in _strip_ansi(out)

    def test_print_logs(self, capsys):
        logs = [{"level": "info", "message": "hello", "created_at": "2025-01-01T00:00:00"}]
        print_logs(logs)
        out = capsys.readouterr().out
        assert "hello" in out
        assert "INFO" in _strip_ansi(out)

    def test_print_steps_empty(self, capsys):
        print_steps([])
        out = capsys.readouterr().out
        assert "no steps" in _strip_ansi(out)

    def test_print_steps(self, capsys):
        steps = [{"step_type": "tool_use", "tool": "read_file", "target": "main.py", "summary": "read"}]
        print_steps(steps)
        out = capsys.readouterr().out
        assert "main.py" in out
