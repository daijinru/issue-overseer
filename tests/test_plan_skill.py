"""Tests for PlanSkill — prompt construction, JSON extraction, and validation."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from mango.models import Issue, IssueStatus, IssuePriority, TurnContext
from mango.skills.plan import (
    PlanSkill,
    extract_spec_json,
    validate_spec,
    _MAX_PLAN_CHARS,
    _MAX_CRITERION_CHARS,
    _MAX_CRITERIA_COUNT,
    _MAX_FILES_COUNT,
    _MAX_SPEC_TOTAL_CHARS,
)


# ── Fixtures ──────────────────────────────────────────────────────────


def _make_ctx(
    title: str = "Fix login bug",
    description: str = "The login page crashes on submit",
    human_instruction: str | None = None,
    spec: str | None = None,
) -> TurnContext:
    """Create a minimal TurnContext for testing."""
    issue = Issue(
        id="test-issue-id",
        title=title,
        description=description,
        status=IssueStatus.open,
        priority=IssuePriority.medium,
    )
    return TurnContext(
        issue=issue,
        turn_number=1,
        max_turns=1,
        human_instruction=human_instruction,
        spec=spec,
    )


@pytest.fixture()
def mock_client():
    """A mock OpenCodeClient for PlanSkill."""
    client = AsyncMock()
    client.run_prompt = AsyncMock(return_value='{"plan": "test"}')
    client.close = AsyncMock()
    return client


@pytest.fixture()
def plan_skill(mock_client):
    return PlanSkill(mock_client)


# ── extract_spec_json tests ──────────────────────────────────────────


class TestExtractSpecJson:
    """Tests for the robust JSON extraction utility."""

    def test_direct_json(self):
        """Strategy 1: Raw JSON string."""
        raw = '{"plan": "Fix the bug", "acceptance_criteria": ["Test passes"]}'
        result = extract_spec_json(raw)
        assert result is not None
        assert result["plan"] == "Fix the bug"
        assert result["acceptance_criteria"] == ["Test passes"]

    def test_json_with_whitespace(self):
        """Strategy 1: JSON with leading/trailing whitespace."""
        raw = '  \n  {"plan": "Do the thing"}  \n  '
        result = extract_spec_json(raw)
        assert result is not None
        assert result["plan"] == "Do the thing"

    def test_markdown_code_block_json(self):
        """Strategy 2: JSON inside ```json ... ``` block."""
        raw = """Here is the plan:

```json
{
  "plan": "Refactor authentication",
  "acceptance_criteria": ["All tests pass", "No regressions"],
  "files_to_modify": ["auth.py"],
  "estimated_complexity": "medium"
}
```

Let me know if you'd like any changes."""
        result = extract_spec_json(raw)
        assert result is not None
        assert result["plan"] == "Refactor authentication"
        assert len(result["acceptance_criteria"]) == 2
        assert result["files_to_modify"] == ["auth.py"]

    def test_markdown_code_block_no_lang(self):
        """Strategy 2: JSON inside ``` ... ``` block (no language tag)."""
        raw = """```
{"plan": "Simple plan", "files_to_modify": ["main.py"]}
```"""
        result = extract_spec_json(raw)
        assert result is not None
        assert result["plan"] == "Simple plan"

    def test_explanation_with_json_embedded(self):
        """Strategy 3: JSON embedded in explanation text."""
        raw = """After analyzing the codebase, I recommend the following plan:

{"plan": "Add input validation to the login endpoint", "acceptance_criteria": ["Validates email format", "Returns 400 on invalid input"], "files_to_modify": ["routes/login.py", "models/user.py"], "estimated_complexity": "low"}

This should resolve the issue efficiently."""
        result = extract_spec_json(raw)
        assert result is not None
        assert result["plan"] == "Add input validation to the login endpoint"
        assert len(result["files_to_modify"]) == 2
        assert result["estimated_complexity"] == "low"

    def test_nested_json_braces(self):
        """Strategy 3: JSON with nested structures (arrays of objects)."""
        raw = 'Some text {"plan": "test", "details": {"nested": true}} more text'
        result = extract_spec_json(raw)
        assert result is not None
        assert result["plan"] == "test"
        assert result["details"]["nested"] is True

    def test_invalid_json_returns_none(self):
        """All strategies fail → None."""
        raw = "This is just plain text with no JSON at all."
        result = extract_spec_json(raw)
        assert result is None

    def test_empty_string_returns_none(self):
        """Empty input → None."""
        result = extract_spec_json("")
        assert result is None

    def test_malformed_json_returns_none(self):
        """Broken JSON that looks like JSON but isn't valid."""
        raw = '{"plan": "missing closing brace"'
        result = extract_spec_json(raw)
        assert result is None

    def test_json_array_not_object(self):
        """A JSON array should be parsed by strategy 1 but won't match { ... }."""
        raw = '["item1", "item2"]'
        # Strategy 1 will parse this as a list
        result = extract_spec_json(raw)
        # It returns a list (valid JSON), not None
        assert result is not None
        assert isinstance(result, list)


# ── validate_spec tests ──────────────────────────────────────────────


class TestValidateSpec:
    """Tests for Spec field validation and normalization."""

    def test_snake_case_fields(self):
        """Standard snake_case fields are preserved."""
        data = {
            "plan": "Fix the bug",
            "acceptance_criteria": ["Tests pass"],
            "files_to_modify": ["file.py"],
            "estimated_complexity": "high",
        }
        result = validate_spec(data)
        assert result["plan"] == "Fix the bug"
        assert result["acceptance_criteria"] == ["Tests pass"]
        assert result["files_to_modify"] == ["file.py"]
        assert result["estimated_complexity"] == "high"

    def test_camel_case_fields(self):
        """camelCase field names are accepted and normalized."""
        data = {
            "Plan": "Fix the bug",
            "acceptanceCriteria": ["Tests pass"],
            "filesToModify": ["file.py"],
            "complexity": "low",
        }
        result = validate_spec(data)
        assert result["plan"] == "Fix the bug"
        assert result["acceptance_criteria"] == ["Tests pass"]
        assert result["files_to_modify"] == ["file.py"]
        assert result["estimated_complexity"] == "low"

    def test_missing_fields_default(self):
        """Missing fields get sensible defaults."""
        data = {}
        result = validate_spec(data)
        assert result["plan"] == ""
        assert result["acceptance_criteria"] == []
        assert result["files_to_modify"] == []
        assert result["estimated_complexity"] == "medium"

    def test_snake_case_takes_priority(self):
        """If both snake_case and camelCase exist, snake_case wins."""
        data = {
            "plan": "Snake wins",
            "Plan": "Camel loses",
            "acceptance_criteria": ["snake"],
            "acceptanceCriteria": ["camel"],
        }
        result = validate_spec(data)
        assert result["plan"] == "Snake wins"
        assert result["acceptance_criteria"] == ["snake"]

    def test_output_has_correct_keys(self):
        """validate_spec always returns exactly 4 keys."""
        data = {"plan": "test", "extra_field": "ignored"}
        result = validate_spec(data)
        assert set(result.keys()) == {
            "plan", "acceptance_criteria", "files_to_modify", "estimated_complexity",
        }

    # ── Length limit tests ────────────────────────────────────────────

    def test_plan_truncated_when_too_long(self):
        """Plan field exceeding _MAX_PLAN_CHARS is truncated."""
        long_plan = "x" * (_MAX_PLAN_CHARS + 500)
        data = {"plan": long_plan}
        result = validate_spec(data)
        assert len(result["plan"]) < len(long_plan)
        assert result["plan"].endswith("…[truncated]")

    def test_criterion_truncated_when_too_long(self):
        """Individual acceptance criteria exceeding limit are truncated."""
        long_criterion = "y" * (_MAX_CRITERION_CHARS + 100)
        data = {"acceptance_criteria": [long_criterion, "short one"]}
        result = validate_spec(data)
        assert len(result["acceptance_criteria"]) == 2
        assert result["acceptance_criteria"][0].endswith("…[truncated]")
        assert result["acceptance_criteria"][1] == "short one"

    def test_criteria_count_capped(self):
        """Number of acceptance criteria is capped at _MAX_CRITERIA_COUNT."""
        many_criteria = [f"criterion {i}" for i in range(_MAX_CRITERIA_COUNT + 10)]
        data = {"acceptance_criteria": many_criteria}
        result = validate_spec(data)
        assert len(result["acceptance_criteria"]) == _MAX_CRITERIA_COUNT

    def test_files_count_capped(self):
        """Number of files_to_modify is capped at _MAX_FILES_COUNT."""
        many_files = [f"src/file_{i}.py" for i in range(_MAX_FILES_COUNT + 20)]
        data = {"files_to_modify": many_files}
        result = validate_spec(data)
        assert len(result["files_to_modify"]) == _MAX_FILES_COUNT

    def test_total_spec_size_capped(self):
        """Total serialized spec is kept within _MAX_SPEC_TOTAL_CHARS."""
        # Create a spec that is huge in total but each field is within its own limit
        data = {
            "plan": "a" * _MAX_PLAN_CHARS,
            "acceptance_criteria": ["b" * _MAX_CRITERION_CHARS] * _MAX_CRITERIA_COUNT,
            "files_to_modify": [f"src/very/long/path/file_{i}.py" for i in range(_MAX_FILES_COUNT)],
            "estimated_complexity": "high",
        }
        result = validate_spec(data)
        serialized = json.dumps(result, ensure_ascii=False)
        assert len(serialized) <= _MAX_SPEC_TOTAL_CHARS

    def test_normal_spec_unchanged(self):
        """A normal-sized spec passes through without any truncation."""
        data = {
            "plan": "Implement SSE stream processing HTTP client method",
            "acceptance_criteria": [
                "Client can connect to SSE endpoint",
                "Events are parsed correctly",
                "Connection errors are handled",
            ],
            "files_to_modify": ["src/client.py", "tests/test_client.py"],
            "estimated_complexity": "medium",
        }
        result = validate_spec(data)
        assert result["plan"] == data["plan"]
        assert result["acceptance_criteria"] == data["acceptance_criteria"]
        assert result["files_to_modify"] == data["files_to_modify"]

    def test_non_list_criteria_becomes_empty(self):
        """Non-list acceptance_criteria is normalized to empty list."""
        data = {"acceptance_criteria": "not a list"}
        result = validate_spec(data)
        assert result["acceptance_criteria"] == []

    def test_non_list_files_becomes_empty(self):
        """Non-list files_to_modify is normalized to empty list."""
        data = {"files_to_modify": "not a list"}
        result = validate_spec(data)
        assert result["files_to_modify"] == []


# ── PlanSkill prompt tests ──────────────────────────────────────────


class TestPlanSkillPrompt:
    """Tests for PlanSkill prompt construction."""

    def test_normal_prompt_contains_issue_info(self, plan_skill):
        """Normal prompt contains issue title and description."""
        ctx = _make_ctx(title="Add dark mode", description="Implement theme toggle")
        prompt = plan_skill._build_plan_prompt(ctx)
        assert "Add dark mode" in prompt
        assert "Implement theme toggle" in prompt
        assert "Generate Execution Plan" in prompt

    def test_normal_prompt_requests_json(self, plan_skill):
        """Normal prompt asks for JSON output format."""
        ctx = _make_ctx()
        prompt = plan_skill._build_plan_prompt(ctx)
        assert "JSON" in prompt
        assert "plan" in prompt
        assert "acceptance_criteria" in prompt
        assert "files_to_modify" in prompt
        assert "estimated_complexity" in prompt

    def test_strict_prompt_adds_emphasis(self, plan_skill):
        """Strict prompt adds extra JSON-only emphasis."""
        ctx = _make_ctx()
        strict = plan_skill._build_plan_prompt(ctx, strict=True)
        normal = plan_skill._build_plan_prompt(ctx, strict=False)
        assert "IMPORTANT" in strict
        assert "ONLY valid JSON" in strict
        assert "json.loads()" in strict
        # Strict is longer due to extra instructions
        assert len(strict) > len(normal)

    def test_build_strict_prompt_method(self, plan_skill):
        """build_strict_prompt() is a convenience wrapper."""
        ctx = _make_ctx()
        direct = plan_skill._build_plan_prompt(ctx, strict=True)
        via_method = plan_skill.build_strict_prompt(ctx)
        assert direct == via_method

    def test_human_instruction_included(self, plan_skill):
        """Human instruction is included in the prompt when provided."""
        ctx = _make_ctx(human_instruction="Focus on the authentication module")
        prompt = plan_skill._build_plan_prompt(ctx)
        assert "Focus on the authentication module" in prompt
        assert "Additional Instructions" in prompt

    def test_no_human_instruction_excluded(self, plan_skill):
        """No human instruction section when not provided."""
        ctx = _make_ctx(human_instruction=None)
        prompt = plan_skill._build_plan_prompt(ctx)
        assert "Additional Instructions" not in prompt


# ── PlanSkill execution tests ────────────────────────────────────────


class TestPlanSkillExecution:
    """Tests for PlanSkill.execute()."""

    @pytest.mark.asyncio
    async def test_execute_calls_client(self, plan_skill, mock_client):
        """execute() calls the OpenCode client with built prompt."""
        ctx = _make_ctx()
        result = await plan_skill.execute(ctx, "/tmp/test")
        mock_client.run_prompt.assert_awaited_once()
        call_args = mock_client.run_prompt.call_args
        assert "Fix login bug" in call_args[0][0]  # prompt contains issue title
        assert call_args[1]["cwd"] == "/tmp/test"

    @pytest.mark.asyncio
    async def test_execute_returns_raw_output(self, plan_skill, mock_client):
        """execute() returns the raw output from the client."""
        mock_client.run_prompt.return_value = '{"plan": "result"}'
        ctx = _make_ctx()
        result = await plan_skill.execute(ctx, "/tmp/test")
        assert result == '{"plan": "result"}'

    @pytest.mark.asyncio
    async def test_execute_passes_cancel_event(self, plan_skill, mock_client):
        """execute() forwards the cancel_event to the client."""
        cancel = asyncio.Event()
        ctx = _make_ctx()
        await plan_skill.execute(ctx, "/tmp/test", cancel_event=cancel)
        call_kwargs = mock_client.run_prompt.call_args[1]
        assert call_kwargs["cancel_event"] is cancel

    @pytest.mark.asyncio
    async def test_execute_passes_on_event(self, plan_skill, mock_client):
        """execute() forwards the on_event callback to the client."""
        callback = lambda e: None
        ctx = _make_ctx()
        await plan_skill.execute(ctx, "/tmp/test", on_event=callback)
        call_kwargs = mock_client.run_prompt.call_args[1]
        assert call_kwargs["on_event"] is callback

    @pytest.mark.asyncio
    async def test_execute_propagates_error(self, plan_skill, mock_client):
        """execute() propagates exceptions from the client."""
        mock_client.run_prompt.side_effect = RuntimeError("OpenCode crashed")
        ctx = _make_ctx()
        with pytest.raises(RuntimeError, match="OpenCode crashed"):
            await plan_skill.execute(ctx, "/tmp/test")


# ── Integration: extract + validate pipeline ─────────────────────────


class TestExtractAndValidatePipeline:
    """End-to-end tests for the extract → validate pipeline."""

    def test_realistic_llm_output_with_markdown(self):
        """Simulate realistic LLM output wrapped in markdown."""
        llm_output = """Based on my analysis of the codebase, here is the execution plan:

```json
{
  "plan": "Fix the authentication middleware to properly validate JWT tokens. The current implementation skips signature verification when the token is expired.",
  "acceptance_criteria": [
    "JWT signature is always verified before processing claims",
    "Expired tokens return 401 with clear error message",
    "All existing auth tests continue to pass",
    "New test covers the signature bypass vulnerability"
  ],
  "files_to_modify": [
    "src/middleware/auth.py",
    "tests/test_auth_middleware.py"
  ],
  "estimated_complexity": "medium"
}
```

This plan addresses the security vulnerability while maintaining backward compatibility."""

        # Extract
        spec_data = extract_spec_json(llm_output)
        assert spec_data is not None

        # Validate
        validated = validate_spec(spec_data)
        assert "JWT" in validated["plan"]
        assert len(validated["acceptance_criteria"]) == 4
        assert len(validated["files_to_modify"]) == 2
        assert validated["estimated_complexity"] == "medium"

        # Should be serializable
        spec_json = json.dumps(validated, ensure_ascii=False)
        round_tripped = json.loads(spec_json)
        assert round_tripped == validated

    def test_realistic_llm_output_bare_json(self):
        """LLM returns bare JSON (ideal case)."""
        llm_output = json.dumps({
            "plan": "Add pagination to the issues API endpoint",
            "acceptance_criteria": ["GET /api/issues supports ?page=&limit= params"],
            "files_to_modify": ["src/mango/server/routes.py"],
            "estimated_complexity": "low",
        })

        spec_data = extract_spec_json(llm_output)
        assert spec_data is not None
        validated = validate_spec(spec_data)
        assert validated["plan"] == "Add pagination to the issues API endpoint"
        assert validated["estimated_complexity"] == "low"

    def test_extraction_failure_returns_none(self):
        """When extraction fails, the pipeline handles it gracefully."""
        llm_output = "I couldn't analyze the codebase. Please provide more context."
        spec_data = extract_spec_json(llm_output)
        assert spec_data is None
        # Caller (runtime) should handle None → retry or waiting_human
