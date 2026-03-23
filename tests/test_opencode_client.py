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
    """Simulates an asyncio subprocess that finishes immediately.

    Now provides streaming-compatible stdout/stderr interfaces since
    the client uses ``proc.stdout.readline()`` instead of ``proc.communicate()``.
    """

    def __init__(self, stdout: bytes, stderr: bytes, returncode: int):
        self.stdout = FakeStdout(
            [line + b"\n" for line in stdout.split(b"\n") if line]
        )
        self.stderr = FakeStderr(stderr)
        self.returncode = returncode

    def kill(self):
        pass

    async def wait(self):
        pass


class SlowFakeProcess:
    """Simulates a long-running subprocess that can be killed."""

    def __init__(self, killed_flag: dict):
        self._killed = killed_flag
        self.stdout = SlowFakeStdout()
        self.stderr = FakeStderr()
        self.returncode = -9

    def kill(self):
        self._killed["value"] = True

    async def wait(self):
        pass


class FakeStdout:
    """Simulates async readline from proc.stdout for streaming tests."""

    def __init__(self, lines: list[bytes]):
        self._lines = list(lines)
        self._index = 0

    async def readline(self) -> bytes:
        if self._index >= len(self._lines):
            return b""  # EOF
        line = self._lines[self._index]
        self._index += 1
        return line

    async def read(self) -> bytes:
        return b"".join(self._lines[self._index:])


class FakeStderr:
    """Simulates async read from proc.stderr."""

    def __init__(self, data: bytes = b""):
        self._data = data

    async def read(self) -> bytes:
        return self._data


class StreamingFakeProcess:
    """Simulates an asyncio subprocess with streaming stdout for line-by-line reading."""

    def __init__(self, stdout_lines: list[bytes], stderr: bytes = b"", returncode: int = 0):
        self.stdout = FakeStdout(stdout_lines)
        self.stderr = FakeStderr(stderr)
        self.returncode = returncode
        self._waited = False

    def kill(self):
        pass

    async def wait(self):
        self._waited = True


class SlowStreamingFakeProcess:
    """Simulates a streaming subprocess that produces lines slowly (for cancel tests)."""

    def __init__(self, killed_flag: dict):
        self._killed = killed_flag
        self.stdout = SlowFakeStdout()
        self.stderr = FakeStderr()
        self.returncode = -9

    def kill(self):
        self._killed["value"] = True

    async def wait(self):
        pass


class SlowFakeStdout:
    """Stdout that blocks forever on readline (simulates a long-running process)."""

    async def readline(self) -> bytes:
        await asyncio.sleep(60)
        return b""

    async def read(self) -> bytes:
        return b""


# ── _classify_event tests ─────────────────────────────────────────────


def test_classify_event_tool_use():
    """tool_use events should be classified with tool name and target."""
    event = {
        "type": "tool_use",
        "name": "read",
        "input": {"path": "src/main.py"},
    }
    result = OpenCodeClient._classify_event(event)
    assert result is not None
    assert result["step_type"] == "tool_use"
    assert result["tool"] == "read"
    assert result["target"] == "src/main.py"


def test_classify_event_tool_use_edit():
    """edit tool_use should extract file_path from input."""
    event = {
        "type": "tool_use",
        "name": "edit",
        "input": {"file_path": "src/utils.py", "content": "..."},
    }
    result = OpenCodeClient._classify_event(event)
    assert result is not None
    assert result["step_type"] == "tool_use"
    assert result["tool"] == "edit"
    assert result["target"] == "src/utils.py"


def test_classify_event_tool_use_shell():
    """shell tool_use should extract command from input."""
    event = {
        "type": "tool_use",
        "name": "shell",
        "input": {"command": "pytest tests/"},
    }
    result = OpenCodeClient._classify_event(event)
    assert result is not None
    assert result["step_type"] == "tool_use"
    assert result["tool"] == "shell"
    assert result["target"] == "pytest tests/"


def test_classify_event_text_parts():
    """Events with text parts should be classified as text with summary."""
    event = {
        "parts": [{"type": "text", "text": "I will now read the file and make changes."}],
    }
    result = OpenCodeClient._classify_event(event)
    assert result is not None
    assert result["step_type"] == "text"
    assert "I will now read" in result["summary"]


def test_classify_event_text_parts_truncated():
    """Long text summaries should be truncated to 200 chars."""
    long_text = "x" * 500
    event = {
        "parts": [{"type": "text", "text": long_text}],
    }
    result = OpenCodeClient._classify_event(event)
    assert result is not None
    assert len(result["summary"]) <= 203  # 200 + "..."


def test_classify_event_unknown():
    """Events without tool_use or text parts should return None."""
    event = {"type": "start", "data": {}}
    result = OpenCodeClient._classify_event(event)
    assert result is None


def test_classify_event_nested_data_parts():
    """Parts nested under 'data' key should also be classified."""
    event = {
        "data": {"parts": [{"type": "text", "text": "Analyzing code..."}]},
    }
    result = OpenCodeClient._classify_event(event)
    assert result is not None
    assert result["step_type"] == "text"
    assert "Analyzing code" in result["summary"]


# ── Streaming on_event tests ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_prompt_streaming_calls_on_event(monkeypatch):
    """on_event callback should be called for each classified event during streaming."""
    lines = [
        json.dumps({"type": "tool_use", "name": "read", "input": {"path": "foo.py"}}).encode() + b"\n",
        json.dumps({"parts": [{"type": "text", "text": "final result"}]}).encode() + b"\n",
    ]

    async def fake_create_subprocess_exec(*args, **kwargs):
        return StreamingFakeProcess(stdout_lines=lines, returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    events_received: list[dict] = []

    def on_event(evt: dict):
        events_received.append(evt)

    client = OpenCodeClient(command="opencode", timeout=10)
    result = await client.run_prompt("do something", cwd="/tmp", on_event=on_event)

    # Final result should still work (last wins)
    assert result == "final result"

    # on_event should have been called for classified events
    assert len(events_received) >= 1
    # First event should be tool_use
    tool_events = [e for e in events_received if e.get("step_type") == "tool_use"]
    assert len(tool_events) >= 1
    assert tool_events[0]["tool"] == "read"


@pytest.mark.asyncio
async def test_run_prompt_streaming_final_result_unchanged(monkeypatch):
    """Streaming mode should produce the same final result as batch mode."""
    lines = [
        json.dumps({"type": "start"}).encode() + b"\n",
        json.dumps({"parts": [{"type": "text", "text": "intermediate"}]}).encode() + b"\n",
        json.dumps({"parts": [{"type": "text", "text": "final answer"}]}).encode() + b"\n",
    ]

    async def fake_create_subprocess_exec(*args, **kwargs):
        return StreamingFakeProcess(stdout_lines=lines, returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    client = OpenCodeClient(command="opencode", timeout=10)
    # With on_event
    result_streaming = await client.run_prompt("test", cwd="/tmp", on_event=lambda e: None)
    assert result_streaming == "final answer"

    # Without on_event (backward compatible)
    result_batch = await client.run_prompt("test", cwd="/tmp")
    assert result_batch == "final answer"


@pytest.mark.asyncio
async def test_run_prompt_streaming_cancel(monkeypatch):
    """Cancel during streaming should kill process and raise CancelledError."""
    killed = {"value": False}

    async def fake_create_subprocess_exec(*args, **kwargs):
        return SlowStreamingFakeProcess(killed_flag=killed)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    client = OpenCodeClient(command="opencode", timeout=10)
    cancel = asyncio.Event()

    async def fire_cancel():
        await asyncio.sleep(0.05)
        cancel.set()

    asyncio.create_task(fire_cancel())

    with pytest.raises(asyncio.CancelledError):
        await client.run_prompt("hello", cwd="/tmp", cancel_event=cancel, on_event=lambda e: None)

    assert killed["value"], "Process should have been killed"


@pytest.mark.asyncio
async def test_run_prompt_streaming_no_on_event_backward_compatible(monkeypatch):
    """Without on_event, streaming mode still works correctly."""
    lines = [
        json.dumps({"parts": [{"type": "text", "text": "hello world"}]}).encode() + b"\n",
    ]

    async def fake_create_subprocess_exec(*args, **kwargs):
        return StreamingFakeProcess(stdout_lines=lines, returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    client = OpenCodeClient(command="opencode", timeout=10)
    result = await client.run_prompt("greet", cwd="/tmp")
    assert result == "hello world"


@pytest.mark.asyncio
async def test_run_prompt_streaming_nonzero_exit(monkeypatch):
    """Non-zero exit code in streaming mode should raise RuntimeError."""
    lines = [
        json.dumps({"parts": [{"type": "text", "text": "partial"}]}).encode() + b"\n",
    ]

    async def fake_create_subprocess_exec(*args, **kwargs):
        return StreamingFakeProcess(stdout_lines=lines, stderr=b"fatal error", returncode=1)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    client = OpenCodeClient(command="opencode", timeout=10)
    with pytest.raises(RuntimeError, match="fatal error"):
        await client.run_prompt("fail", cwd="/tmp")
