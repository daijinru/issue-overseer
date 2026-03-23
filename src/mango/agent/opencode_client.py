"""OpenCode client — runs ``opencode run`` as a subprocess."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

# Maximum length for text summaries in classified events.
_MAX_SUMMARY_LEN = 200


class OpenCodeClient:
    """Executes prompts via the ``opencode run`` CLI command."""

    def __init__(self, command: str = "opencode", timeout: int = 300) -> None:
        self.command = command
        self.timeout = timeout

    async def run_prompt(
        self,
        prompt: str,
        *,
        cwd: str = ".",
        cancel_event: asyncio.Event | None = None,
        on_event: Callable[[dict], None] | None = None,
    ) -> str:
        """Run a prompt through ``opencode run --format json`` and return the
        final text result.

        If *cancel_event* is set before or during execution the subprocess is
        killed immediately.

        If *on_event* is provided, each NDJSON event from the subprocess stdout
        is classified via :meth:`_classify_event` and forwarded to the callback
        in real time.  The final aggregated text result is still returned.
        """
        if cancel_event and cancel_event.is_set():
            raise asyncio.CancelledError("Task cancelled before running opencode")

        proc = await asyncio.create_subprocess_exec(
            self.command, "run", "--dir", cwd, "--format", "json", prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )

        try:
            raw_lines: list[str] = []
            text_parts: list[str] = []

            # ── Stream stdout line by line ──────────────────────────
            while True:
                # Check cancel before each read
                if cancel_event and cancel_event.is_set():
                    proc.kill()
                    await proc.wait()
                    logger.info("opencode process killed due to cancel")
                    raise asyncio.CancelledError(
                        "Task cancelled during opencode execution"
                    )

                try:
                    line_bytes = await asyncio.wait_for(
                        proc.stdout.readline(), timeout=1.0,
                    )
                except asyncio.TimeoutError:
                    # No data yet — loop back to check cancel / overall timeout
                    continue

                if not line_bytes:
                    break  # EOF — process finished writing stdout

                line = line_bytes.decode().strip()
                if not line:
                    continue

                raw_lines.append(line)

                # Try to parse as JSON
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if not isinstance(event, dict):
                    continue

                # ── Forward classified event via callback ───────────
                if on_event is not None:
                    classified = self._classify_event(event)
                    if classified is not None:
                        on_event(classified)

                # ── Accumulate text parts (last wins) ───────────────
                parts = self._extract_parts(event)
                if parts:
                    extracted = [
                        p.get("text", "")
                        for p in parts
                        if isinstance(p, dict) and p.get("type") == "text"
                    ]
                    if extracted:
                        text_parts = extracted  # keep overwriting — last wins

            # ── Wait for process to finish ──────────────────────────
            await proc.wait()

        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise TimeoutError(
                f"opencode process timed out after {self.timeout}s"
            )

        # ── Read stderr for error reporting ─────────────────────────
        stderr_bytes = await proc.stderr.read()

        if proc.returncode != 0:
            err_msg = stderr_bytes.decode().strip() if stderr_bytes else "unknown error"
            raise RuntimeError(
                f"opencode exited with code {proc.returncode}: {err_msg}"
            )

        # Build final result from accumulated text parts
        result = "\n".join(text_parts).strip()
        if not result:
            # Fallback: return raw collected lines
            raw = "\n".join(raw_lines).strip()
            return raw if raw else ""
        return result

    @staticmethod
    def _extract_parts(event: dict) -> list | None:
        """Extract the ``parts`` list from various event shapes."""
        parts = event.get("parts")
        if parts is None and isinstance(event.get("data"), dict):
            parts = event["data"].get("parts")
        if parts is None and isinstance(event.get("message"), dict):
            parts = event["message"].get("parts")
        if parts and isinstance(parts, list):
            return parts
        return None

    @staticmethod
    def _classify_event(event: dict) -> dict | None:
        """Classify an NDJSON event into a step description.

        Returns a dict with ``step_type`` and contextual fields, or ``None``
        if the event is not user-interesting.

        Recognised patterns:
        - ``tool_use`` events → ``{"step_type": "tool_use", "tool": ..., "target": ...}``
        - Events with ``parts`` containing text → ``{"step_type": "text", "summary": ...}``
        """
        # ── tool_use events ─────────────────────────────────────────
        if event.get("type") == "tool_use":
            tool_name = event.get("name", "unknown")
            inp = event.get("input", {})
            if not isinstance(inp, dict):
                inp = {}
            # Extract the most relevant target depending on tool
            target = (
                inp.get("path")
                or inp.get("file_path")
                or inp.get("command")
                or inp.get("query")
                or ""
            )
            return {"step_type": "tool_use", "tool": tool_name, "target": target}

        # ── text parts events ───────────────────────────────────────
        parts = event.get("parts")
        if parts is None and isinstance(event.get("data"), dict):
            parts = event["data"].get("parts")
        if parts is None and isinstance(event.get("message"), dict):
            parts = event["message"].get("parts")

        if parts and isinstance(parts, list):
            texts = [
                p.get("text", "")
                for p in parts
                if isinstance(p, dict) and p.get("type") == "text"
            ]
            summary = " ".join(texts).strip()
            if summary:
                if len(summary) > _MAX_SUMMARY_LEN:
                    summary = summary[:_MAX_SUMMARY_LEN] + "..."
                return {"step_type": "text", "summary": summary}

        return None

    @staticmethod
    def _parse_output(raw: str) -> str:
        """Extract the final text result from ``--format json`` output.

        ``opencode run --format json`` outputs newline-delimited JSON events.
        We scan for message events and extract ``type: "text"`` parts from the
        last one.

        .. note::
           This method is kept for backward compatibility with tests and any
           code that calls it directly.  The streaming ``run_prompt`` now does
           inline accumulation instead.
        """
        text_parts: list[str] = []

        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Try to extract text parts from the event
            parts = None
            if isinstance(event, dict):
                parts = event.get("parts")
                # Nested under "data" or "message" in some event shapes
                if parts is None and isinstance(event.get("data"), dict):
                    parts = event["data"].get("parts")
                if parts is None and isinstance(event.get("message"), dict):
                    parts = event["message"].get("parts")

            if parts and isinstance(parts, list):
                extracted = [
                    p.get("text", "")
                    for p in parts
                    if isinstance(p, dict) and p.get("type") == "text"
                ]
                if extracted:
                    text_parts = extracted  # keep overwriting — last wins

        result = "\n".join(text_parts).strip()
        if not result:
            # Fallback: return raw stdout if we couldn't parse events
            return raw.strip()
        return result

    async def close(self) -> None:
        """No persistent resources to clean up in subprocess mode."""
