# Agent Execution System — Comprehensive Architecture Analysis

**Project**: Mango (issue-overseer) — "AI-driven code generation platform — Issue in, code out."

---

## Table of Contents
1. System Overview
2. Agent-Related Files
3. State Machine Patterns
4. Control Plane / Orchestration
5. AI/LLM Integration
6. Strategy / Policy Patterns
7. Event-Driven Patterns
8. TypeScript/JavaScript Types & Interfaces
9. Configuration & Constraints
10. Key Architectural Insights

---

## 1. System Overview

Mango is a three-tier AI agent platform that converts Issues into code via autonomous LLM-driven execution.

Three deployment units:
- **Agent Runtime** (`agent/`) — Core engine: issue management, execution runtime, skills, DB, SSE (port 18800)
- **Gateway Service** (`gateway/`) — Session management, message routing, external integration bridge (port 18900)
- **Web Frontend** (`web/`) — React Kanban UI with real-time SSE streaming (port 5173)

---

## 2. Agent-Related Files (full inventory)

### 2.1 Core Agent Runtime
- `agent/agent/runtime.py` — **AgentRuntime class** — Central orchestrator: runTask → runTurn → runAttempt loop
- `agent/agent/context.py` — **build_turn_context()** — Assembles per-turn context (TurnContext dataclass)
- `agent/agent/opencode_client.py` — **OpenCodeClient** — Subprocess wrapper for `opencode run --format json`
- `agent/agent/safety.py` — Safety constraints — Command allowlists, blocked patterns, execution audit

### 2.2 Skills Layer
- `agent/skills/base.py` — **BaseSkill (ABC)** + **GenericSkill** — Prompt builder and execution adapter
- `agent/skills/plan.py` — **PlanSkill** — Generates structured specs (execution plans) without code changes

### 2.3 Data Layer
- `agent/models.py` — All Pydantic models + enums: Issue, Execution, ExecutionLog, ExecutionStep, TurnContext
- `agent/db/repos.py` — Repository pattern: IssueRepo, ExecutionRepo, ExecutionLogRepo, ExecutionStepRepo
- `agent/db/connection.py` — SQLite connection management + migration runner
- `agent/db/migrations/*.sql` — 6 migration files defining schema evolution

### 2.4 Server Layer
- `agent/server/app.py` — FastAPI app factory + lifespan (init DB → create EventBus → create AgentRuntime → recover)
- `agent/server/routes.py` — REST API: 17 endpoints for CRUD, execution triggers, SSE streaming
- `agent/server/event_bus.py` — **EventBus** — Per-issue pub/sub via asyncio.Queue
- `agent/server/sse.py` — **sse_stream()** — SSE generator with heartbeats and terminal event detection

### 2.5 CLI
- `agent/cli/parser.py` — Argparse CLI tree (mango serve|health|issue create|list|show|run|cancel|retry|plan|spec|...)
- `agent/cli/commands.py` — 14 command handlers
- `agent/cli/client.py` — **MangoClient** — Synchronous HTTP client wrapper
- `agent/cli/stream.py` — SSE consumer + terminal renderer
- `agent/cli/output.py` — ANSI colors, table formatting, status styling

### 2.6 Gateway Service
- `gateway/src/mango_gateway/service/gateway.py` — **GatewayService** — Session management, message routing
- `gateway/src/mango_gateway/service/runtime_client.py` — **RuntimeClient** — Async HTTP client to Agent Runtime
- `gateway/src/mango_gateway/models.py` — Gateway models: Session, Message, GatewayMessageSend, GatewayReply
- `gateway/src/mango_gateway/config.py` — Gateway settings
- `gateway/src/mango_gateway/server/app.py` — Gateway FastAPI factory
- `gateway/src/mango_gateway/server/routes.py` — Gateway API routes

### 2.7 Frontend
- `web/src/types/index.ts` — All TypeScript interfaces mirroring backend models
- `web/src/utils/kanban.ts` — Kanban column definitions with agent role labels
- `web/src/utils/status.ts` — Status/priority color and label mappings
- `web/src/api/client.ts` — Frontend API client
- `web/src/hooks/useIssueDetail.ts` — SSE + polling hook for real-time updates

---

## 3. State Machine Patterns

### 3.1 Issue Status State Machine (Implicit FSM)

**`agent/models.py` lines 14-23:**
```python
class IssueStatus(str, Enum):
    open = "open"           # Initial state
    planning = "planning"   # Spec generation in progress
    planned = "planned"     # Spec ready, awaiting human approval
    running = "running"     # Agent execution in progress
    review = "review"       # PR created, awaiting human review
    done = "done"           # Completed
    waiting_human = "waiting_human"  # Failed, needs human intervention
    cancelled = "cancelled" # User-cancelled
```

**Transition graph** (reconstructed from runtime.py + routes.py):

```
                    ┌──── reject-spec ────┐
                    v                     │
    open ──plan──> planning ──success──> planned
     │                │                    │
     │             fail/timeout           run
     │                v                    │
     │          waiting_human <───────┐    v
     │               │                │  running
     │            retry               │   │    │
     │               │             fail  │  cancel
     │               v                │  │    │
     └────run──> running ─────────────┘  │    v
                    │                    │ cancelled
                  success                │
                    │                    │
                    v                    │
         git commit → git push          │
              │          │              │
          PR created → review ──complete──> done
              │
          PR failed → done (no PR)
          no changes → waiting_human
```

**Key transition enforcement from routes.py:**
- `run`: only from `open | planned | waiting_human | cancelled`
- `plan`: only from `open`
- `retry`: only from `waiting_human`
- `complete`: only from `review`
- `reject-spec`: only from `planned`
- `edit`: only from `open | planned`
- `delete`: only from `open | done | waiting_human | cancelled`

### 3.2 Execution Status Machine (`agent/models.py` lines 31-36)
```python
class ExecutionStatus(str, Enum):
    running = "running"       # In progress
    completed = "completed"   # Success
    failed = "failed"         # Error
    cancelled = "cancelled"   # User-cancelled
    timeout = "timeout"       # Timed out
```

### 3.3 Session Status Machine (`gateway/.../models.py`)
```python
class SessionStatus(str, Enum):
    active = "active"     # Open and accepting messages
    closed = "closed"     # Manually closed
    expired = "expired"   # Timed out (24h default)
```

### 3.4 Recovery from Interrupted States

`agent/agent/runtime.py` lines 70-95 — `recover_from_restart()`: On service restart, issues stuck in `running` or `planning` are force-transitioned to `waiting_human`.

---

## 4. Control Plane / Orchestration

### 4.1 AgentRuntime — The Orchestrator

`agent/agent/runtime.py` — `class AgentRuntime` — Three-level execution loop:

```
AgentRuntime
├── start_task(issue_id)        # Entry: validates + creates asyncio.Task
│   └── _run_task()             # L1: TASK loop (git, retries across turns)
│       └── _run_turn()         # L2: TURN loop (builds context, calls attempt)
│           └── _run_attempt()  # L3: ATTEMPT (single OpenCode invocation)
│
├── start_plan(issue_id)        # Entry: plan generation
│   └── _run_plan()             # Plan flow with retry (normal → strict prompt)
│
├── cancel_task(issue_id)       # Sets asyncio.Event to cancel
├── is_running(issue_id)        # Check if task is active
└── recover_from_restart()      # Startup recovery
```

**Concurrency model** (runtime.py lines 41-42):
```python
self._cancel_tokens: dict[str, asyncio.Event] = {}
self._running_tasks: dict[str, asyncio.Task] = {}
```

### 4.2 Gateway as Message Router

`gateway/.../service/gateway.py` — `_route_message()` decision logic:
```
if session has current_issue:
    if status == "waiting_human" → retry with user message as instruction
    if status in ("running", "planning") → reject (409)
    else → create new Issue
else:
    → create new Issue + run
```

### 4.3 Full Pipeline: Plan → Execute → Git → PR

`_run_task()` (runtime.py lines 360-498):
```
1. Update issue → running
2. Create git branch: agent/{issue_id[:8]}
3. FOR turn in 1..max_turns:
   a. Build TurnContext with full history
   b. _run_turn() → _run_attempt() → OpenCode
   c. If success → break
   d. Accumulate execution_history
4. If success:
   a. git add + commit
   b. git push to remote
   c. gh pr create
   d. Update issue → review (or done)
5. If failure:
   → waiting_human with failure reason
```

---

## 5. AI/LLM Integration

### 5.1 OpenCode as the LLM Abstraction

`agent/agent/opencode_client.py` — `class OpenCodeClient`

Mango does NOT call OpenAI/Anthropic APIs directly. It uses `opencode` CLI as a subprocess:
```python
proc = await asyncio.create_subprocess_exec(
    self.command, "run", "--dir", cwd, "--format", "json", prompt, ...
)
```

OpenCode outputs NDJSON events: `step_start`, `step_finish`, `tool_use`, `text`, `error`

### 5.2 Prompt Engineering

`agent/skills/base.py` — `GenericSkill._build_prompt()` (lines 35-57) assembles:
```
## Task — issue title + description
## Safety Rules — allowed/blocked commands
## Progress — current turn N of max_turns
## Previous Error — if retry
## Previous Result — if retry
## Current Changes (git diff) — accumulated changes
## Execution History — all past turn summaries
## Additional Instructions from User — human_instruction
## Execution Plan (Spec) — if planned
```

`agent/skills/plan.py` — `PlanSkill._build_plan_prompt()` requests JSON spec:
```json
{
  "plan": "Description of the approach...",
  "acceptance_criteria": ["Criterion 1", "Criterion 2"],
  "files_to_modify": ["path/to/file.py"],
  "estimated_complexity": "low | medium | high"
}
```

### 5.3 Event Classification

`opencode_client.py` `_classify_event()` (lines 238-331) maps raw NDJSON to UI steps:
- `tool_use` → `{step_type: "tool_use", tool: "read", target: "/path"}`
- `text` → `{step_type: "text", summary: "..."}`
- `step_start/finish` → `{step_type: "step", summary: "AI 推理开始/完成"}`

---

## 6. Strategy / Policy Patterns

### 6.1 Safety Policy (Allowlist/Blocklist)

`agent/agent/safety.py` — Dual-layer:

**Layer 1 — Prompt injection** (`build_safety_prompt()`): Safety rules embedded in every prompt.
**Layer 2 — Post-execution audit** (`validate_command()` + `extract_commands_from_result()`): Commands in output are verified against allowed list.

### 6.2 Retry Strategies

**Plan generation** (runtime.py `_run_plan()`):
- Max 2 attempts: normal prompt → strict prompt ("Output ONLY valid JSON")
- On JSON parse failure or timeout: retry once, then → waiting_human

**Task execution** (runtime.py `_run_task()`):
- Max N turns (default 3 via `agent.max_turns`)
- Each turn carries full execution history
- All turns exhausted → waiting_human

### 6.3 Context Truncation Policy

`agent/agent/context.py`:
```python
max_git_diff_lines = 2000    # Truncate git diff
max_result_chars = 5000      # Truncate previous results
```

### 6.4 Spec Validation Policy

`agent/skills/plan.py` `validate_spec()` (lines 70-128):
- Plan: max 2000 chars
- Each criterion: max 200 chars, max 20 criteria
- Files list: max 50 files
- Total spec JSON: max 10,000 chars
- Progressive truncation: criteria first, then plan

### 6.5 Workspace Resolution Strategy

`runtime.py` `_resolve_workspace()` — Three-level heuristic:
1. Exact match — path is a git repo
2. Scan children — user gave parent directory
3. Walk upward — user gave subdirectory

---

## 7. Event-Driven Patterns

### 7.1 EventBus (In-Memory Pub/Sub)

`agent/server/event_bus.py` — `class EventBus`:
```python
_subscribers: dict[str, list[asyncio.Queue[dict]]]
subscribe(issue_id) → Queue
unsubscribe(issue_id, queue)
publish(issue_id, event_type, data)  # Fan-out to all queues
```
Back-pressure: full queues (maxsize=1000) silently drop events.

### 7.2 Event Taxonomy (14 event types)

| Event Type | Emitter | Data |
|------------|---------|------|
| `task_start` | _run_task | {issue_id, branch_name} |
| `task_end` | _run_task/_fail_task | {issue_id, success, pr_url?, failure_reason?} |
| `task_cancelled` | _run_task/_run_plan | {issue_id} |
| `turn_start` | _run_turn | {turn_number, max_turns} |
| `turn_end` | _run_turn | {turn_number, success} |
| `attempt_start` | _run_attempt | {execution_id} |
| `attempt_end` | _run_attempt | {execution_id, status, duration_ms} |
| `opencode_step` | OpenCode callback | {step_type, tool?, target?, summary?} |
| `execution_log` | _log() | {execution_id, level, message} |
| `git_commit` | _run_task | {branch_name} |
| `git_push` | _run_task | {branch_name} |
| `pr_created` | _run_task | {pr_url} |
| `plan_start` | _run_plan | {issue_id} |
| `plan_end` | _run_plan | {issue_id, success, spec?, failure_reason?} |

### 7.3 SSE Stream

`agent/server/sse.py` — `sse_stream()`: Subscribes to EventBus, yields SSE-formatted strings, heartbeat every 30s, terminal events close stream.

### 7.4 Frontend SSE + Polling

`web/src/hooks/useIssueDetail.ts`: EventSource when running, 3s polling fallback when SSE disconnects.

### 7.5 Gateway SSE Relay

`gateway/.../runtime_client.py` `stream_issue_events()`: Consumes Runtime SSE and yields parsed events.

---

## 8. TypeScript/JavaScript Types & Interfaces

### 8.1 Core Types (`web/src/types/index.ts`)

```typescript
type IssueStatus = 'open' | 'planning' | 'planned' | 'running' | 'review' | 'done' | 'waiting_human' | 'cancelled';
type ExecutionStatus = 'running' | 'completed' | 'failed' | 'cancelled' | 'timeout';
type IssuePriority = 'high' | 'medium' | 'low';

interface Issue { id, title, description, status, branch_name, human_instruction, failure_reason, workspace, pr_url, priority, spec, created_at, updated_at }
interface Execution { id, issue_id, turn_number, attempt_number, status, prompt, result, error_message, ... }
interface ExecutionLog { id, execution_id, level, message, created_at }
interface ExecutionStep { id, execution_id, step_type, tool, target, summary, created_at }

type SSEEventType = 'task_start' | 'task_end' | 'turn_start' | ... | 'opencode_step' | 'execution_log';
interface OpenCodeStep { step_type, tool?, target?, summary?, timestamp? }
```

### 8.2 Kanban Column Definitions with Agent Roles (`web/src/utils/kanban.ts`)

```typescript
const KANBAN_COLUMNS = [
  { key: 'backlog',  title: 'Backlog',  agentRole: 'Refiner',      statuses: ['open'] },
  { key: 'todo',     title: 'Todo',     agentRole: 'Orchestrator', statuses: ['planning', 'planned'] },
  { key: 'dev',      title: 'Dev',      agentRole: 'Crafter',      statuses: ['running'] },
  { key: 'review',   title: 'Review',   agentRole: 'Guard',        statuses: ['review'] },
  { key: 'done',     title: 'Done',     agentRole: 'Reporter',     statuses: ['done'] },
];
```

### 8.3 waiting_human / cancelled Column Logic

```typescript
function getColumnForIssue(issue: Issue): string {
  if (issue.status === 'waiting_human' || issue.status === 'cancelled') {
    if (issue.pr_url) return 'review';
    if (issue.branch_name) return 'dev';
    if (issue.spec) return 'todo';
    return 'backlog';
  }
  return statusToColumn[issue.status] ?? 'backlog';
}
```

---

## 9. Configuration & Constraints

### 9.1 Agent Runtime (`overseer.toml`)
```toml
[agent]        max_turns=3, task_timeout=1800, plan_timeout=600
[opencode]     command="opencode", timeout=300
[project]      workspace=".", default_branch="main", remote="origin", pr_base="main"
[security]     allowed_commands=[...14 commands...], blocked_patterns=[...6 patterns...]
[context]      max_git_diff_lines=2000, max_result_chars=5000
[database]     path="./data/mango.db"
[server]       port=18800
```

### 9.2 Gateway (`gateway.toml`)
```toml
[runtime]      url="http://localhost:18800", timeout=30
[session]      timeout_hours=24, cleanup_interval_minutes=60
[gateway]      max_wait_timeout=1800
[database]     path="./data/gateway.db"
[server]       port=18900, host="0.0.0.0"
```

### 9.3 Settings Architecture

`agent/config.py` — 7 nested Pydantic config sections with source priority: init → env vars → dotenv → file secrets → TOML.

---

## 10. Key Architectural Insights

### 10.1 What EXISTS

1. **Implicit State Machine** — IssueStatus enum with transitions enforced by route guards + runtime logic (no formal FSM library)
2. **Three-Level Execution Loop** — Task → Turn → Attempt, with full context carry-through
3. **Event-Driven Architecture** — In-memory EventBus → SSE → Frontend, 14 event types
4. **Skills Abstraction** — BaseSkill ABC with GenericSkill (execution) and PlanSkill (planning)
5. **Safety Layer** — Dual: prompt injection rules + post-execution command audit
6. **Gateway Pattern** — Separate service for sessions/routing (HTTP-only coupling to Runtime)
7. **Subprocess LLM Integration** — Delegates to opencode CLI, not direct API calls
8. **Kanban-as-State-Visualization** — Maps statuses to columns with named agent personas

### 10.2 What DOES NOT EXIST (extension points)

1. **No formal state machine library** — Transitions scattered across routes.py and runtime.py
2. **No multi-agent orchestration** — Single AgentRuntime, one task at a time per issue
3. **No direct OpenAI/Anthropic SDK** — All LLM via opencode subprocess
4. **No plugin system** — Skills are hardcoded (GenericSkill + PlanSkill)
5. **No task queue/scheduler** — Each start_task() creates asyncio.Task directly
6. **No evaluation framework** — No automated acceptance criteria verification
7. **No multi-model routing** — Single opencode command, no model selection
8. **No persistent event log** — EventBus is in-memory only (steps are persisted, SSE events not)
9. **No agent-to-agent communication** — Despite kanban agentRole labels, only ONE runtime
10. **No rollback/undo** — Git branches created but never auto-cleaned on failure
