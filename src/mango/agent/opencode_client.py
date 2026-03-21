"""OpenCode client — runs ``opencode run`` as a subprocess."""

from __future__ import annotations

import asyncio
import json
import logging

logger = logging.getLogger(__name__)


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
    ) -> str:
        """Run a prompt through ``opencode run --format json`` and return the
        final text result.

        If *cancel_event* is set before or during execution the subprocess is
        killed immediately.
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
            if cancel_event is None:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=self.timeout,
                )
            else:
                # Race: subprocess vs cancel_event
                comm_task = asyncio.create_task(proc.communicate())
                cancel_wait = asyncio.create_task(cancel_event.wait())
                done, pending = await asyncio.wait(
                    {comm_task, cancel_wait},
                    timeout=self.timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for p in pending:
                    p.cancel()

                if not done:
                    # Timeout — neither finished
                    proc.kill()
                    await proc.wait()
                    raise TimeoutError(
                        f"opencode process timed out after {self.timeout}s"
                    )

                if cancel_wait in done:
                    # User cancelled — kill the process
                    proc.kill()
                    await proc.wait()
                    logger.info("opencode process killed due to cancel")
                    raise asyncio.CancelledError(
                        "Task cancelled during opencode execution"
                    )

                stdout, stderr = comm_task.result()

        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise TimeoutError(
                f"opencode process timed out after {self.timeout}s"
            )

        if proc.returncode != 0:
            err_msg = stderr.decode().strip() if stderr else "unknown error"
            raise RuntimeError(
                f"opencode exited with code {proc.returncode}: {err_msg}"
            )

        return self._parse_output(stdout.decode())

    @staticmethod
    def _parse_output(raw: str) -> str:
        """Extract the final text result from ``--format json`` output.

        ``opencode run --format json`` outputs newline-delimited JSON events.
        We scan for message events and extract ``type: "text"`` parts from the
        last one.
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
