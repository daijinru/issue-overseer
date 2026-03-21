"""Tests for OpenCodeClient — subprocess mode."""

from __future__ import annotations

import asyncio
import json

import pytest

from mango.agent.opencode_client import OpenCodeClient


def _make_json_output(text: str) -> str:
    """Build a fake ``opencode run --format json`` output line."""
    event = {"parts": [{"type": "text", "text": text}]}
    return json.dumps(event) + "\n"


@pytest.mark.asyncio
async def test_run_prompt_success(monkeypatch):
    """Normal subprocess execution returns parsed text."""
    expected_output = _make_json_output("Task completed successfully.")

    async def fake_create_subprocess_exec(*args, **kwargs):
        proc = FakeProcess(stdout=expected_output.encode(), stderr=b"", returncode=0)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    client = OpenCodeClient(command="opencode", timeout=10)
    result = await client.run_prompt("do something", cwd="/tmp")
    assert result == "Task completed successfully."


@pytest.mark.asyncio
async def test_run_prompt_cancel_before_run():
    """If cancel_event is already set, raises CancelledError immediately."""
    client = OpenCodeClient(command="opencode", timeout=10)
    cancel = asyncio.Event()
    cancel.set()

    with pytest.raises(asyncio.CancelledError):
        await client.run_prompt("hello", cwd="/tmp", cancel_event=cancel)


@pytest.mark.asyncio
async def test_run_prompt_cancel_during_execution(monkeypatch):
    """If cancel_event fires mid-execution, the process is killed."""
    killed = {"value": False}

    async def fake_create_subprocess_exec(*args, **kwargs):
        proc = SlowFakeProcess(killed_flag=killed)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    client = OpenCodeClient(command="opencode", timeout=10)
    cancel = asyncio.Event()

    async def fire_cancel():
        await asyncio.sleep(0.05)
        cancel.set()

    asyncio.create_task(fire_cancel())

    with pytest.raises(asyncio.CancelledError):
        await client.run_prompt("hello", cwd="/tmp", cancel_event=cancel)

    assert killed["value"], "Process should have been killed"


@pytest.mark.asyncio
async def test_run_prompt_nonzero_exit(monkeypatch):
    """Non-zero exit code raises RuntimeError."""

    async def fake_create_subprocess_exec(*args, **kwargs):
        return FakeProcess(stdout=b"", stderr=b"something broke", returncode=1)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    client = OpenCodeClient(command="opencode", timeout=10)
    with pytest.raises(RuntimeError, match="something broke"):
        await client.run_prompt("fail", cwd="/tmp")


@pytest.mark.asyncio
async def test_run_prompt_fast_with_cancel_event(monkeypatch):
    """Fast subprocess finishes before cancel — result returned normally."""
    expected_output = _make_json_output("fast result")

    async def fake_create_subprocess_exec(*args, **kwargs):
        return FakeProcess(stdout=expected_output.encode(), stderr=b"", returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    client = OpenCodeClient(command="opencode", timeout=10)
    cancel = asyncio.Event()  # never set
    result = await client.run_prompt("hello", cwd="/tmp", cancel_event=cancel)
    assert result == "fast result"


@pytest.mark.asyncio
async def test_parse_output_multiline_events():
    """Parser extracts text from last event with parts."""
    lines = [
        json.dumps({"type": "start"}),
        json.dumps({"parts": [{"type": "text", "text": "intermediate"}]}),
        json.dumps({"parts": [{"type": "text", "text": "final answer"}]}),
    ]
    raw = "\n".join(lines) + "\n"
    result = OpenCodeClient._parse_output(raw)
    assert result == "final answer"


@pytest.mark.asyncio
async def test_parse_output_fallback_raw():
    """If no JSON events can be parsed, return raw output."""
    raw = "plain text output with no json"
    result = OpenCodeClient._parse_output(raw)
    assert result == raw.strip()


# ── Helpers ─────────────────────────────────────────────────────────


class FakeProcess:
    """Simulates an asyncio subprocess that finishes immediately."""

    def __init__(self, stdout: bytes, stderr: bytes, returncode: int):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode

    async def communicate(self):
        return self._stdout, self._stderr

    def kill(self):
        pass

    async def wait(self):
        pass


class SlowFakeProcess:
    """Simulates a long-running subprocess that can be killed."""

    def __init__(self, killed_flag: dict):
        self._killed = killed_flag
        self.returncode = -9

    async def communicate(self):
        # Simulate a long-running process
        await asyncio.sleep(60)
        return b"", b""

    def kill(self):
        self._killed["value"] = True

    async def wait(self):
        pass
