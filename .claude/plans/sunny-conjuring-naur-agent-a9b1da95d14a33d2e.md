# Comprehensive Project Exploration — Mango (issue-overseer)

## Executive Summary

**Mango** (project name `issue-overseer`) is an **AI-driven code generation platform** with the tagline "Issue in, code out." It takes user-defined Issues, runs an AI agent (via OpenCode CLI) to generate code solutions, creates git branches, commits, pushes, and opens PRs automatically. The architecture is a **3-tier system**: a React/Ant Design **Kanban Web UI** → a FastAPI **Agent Runtime** (the brain) → and a separate FastAPI **Gateway** service (for external integrations and session management).

---

## 1. Overall Project Structure

```
issue-overseer/
├── .claude/                    # Claude Code configuration
│   ├── settings.local.json     # Permission allow-list
│   └── skills/roadmap-reviewer/SKILL.md  # ROADMAP reviewer agent skill
├── agent/                      # 🧠 Core Agent Runtime (Python package)
│   ├── __init__.py             # Version: 0.1.0
│   ├── __main__.py             # Entry: `python -m agent` → main.main()
│   ├── main.py                 # Uvicorn startup (port 18800)
│   ├── config.py               # Settings from overseer.toml (Pydantic)
│   ├── models.py               # All Pydantic models + enums + TurnContext
│   ├── agent/                  # Agent execution core
│   │   ├── runtime.py          # ⭐ AgentRuntime — THE core orchestrator
│   │   ├── context.py          # TurnContext builder (truncation logic)
│   │   ├── opencode_client.py  # OpenCode CLI subprocess wrapper (NDJSON streaming)
│   │   └── safety.py           # Command validation, safety prompts
│   ├── skills/                 # Skill abstraction layer
│   │   ├── base.py             # BaseSkill ABC + GenericSkill (prompt builder)
│   │   └── plan.py             # PlanSkill — generates Specs (JSON extraction)
│   ├── server/                 # FastAPI HTTP layer
│   │   ├── app.py              # Application factory + lifespan (DB init, runtime recovery)
│   │   ├── routes.py           # All REST API routes (/api/*)
│   │   ├── event_bus.py        # In-memory pub/sub for SSE (per-issue queues)
│   │   └── sse.py              # SSE stream generator (heartbeat, terminal events)
│   ├── db/                     # Database layer (SQLite + aiosqlite)
│   │   ├── connection.py       # Shared connection, WAL mode, migration runner
│   │   ├── repos.py            # IssueRepo, ExecutionRepo, ExecutionLogRepo, ExecutionStepRepo
│   │   └── migrations/         # SQL migrations (001–006)
│   └── cli/                    # CLI client (`mango` command)
│       ├── __init__.py         # Re-exports main
│       ├── parser.py           # Argparse command tree
│       ├── commands.py         # Command handlers (create, list, run, plan, etc.)
│       ├── client.py           # MangoClient — sync HTTP wrapper (httpx)
│       ├── output.py           # ANSI terminal output, table rendering
│       └── stream.py           # SSE stream consumer + terminal renderer
├── gateway/                    # 🌐 Gateway Service (separate Python package)
│   ├── pyproject.toml          # name: mango-gateway
│   ├── gateway.toml            # Config (port 18900, runtime URL, session timeout)
│   ├── start-gateway.sh        # `uv run python -m mango_gateway`
│   ├── uv.lock
│   ├── src/mango_gateway/
│   │   ├── __init__.py
│   │   ├── __main__.py         # Entry: `python -m mango_gateway`
│   │   ├── main.py             # Uvicorn startup (port 18900)
│   │   ├── config.py           # Settings from gateway.toml
│   │   ├── models.py           # Session, Message, GatewayMessageSend, GatewayReply
│   │   ├── server/
│   │   │   ├── app.py          # Application factory + lifespan (cleanup loop)
│   │   │   └── routes.py       # Gateway REST API routes
│   │   ├── service/
│   │   │   ├── gateway.py      # ⭐ GatewayService — session + message routing logic
│   │   │   └── runtime_client.py  # Async HTTP client to Agent Runtime API
│   │   └── db/
│   │       ├── connection.py   # Same pattern as agent's DB layer
│   │       ├── repos.py        # SessionRepo, MessageRepo
│   │       └── migrations/001_init.sql
│   └── tests/                  # Gateway-specific tests
│       ├── conftest.py
│       ├── test_api.py
│       ├── test_gateway_service.py
│       └── test_runtime_client.py
├── web/                        # 🖥️ Frontend (React + Ant Design Kanban)
│   ├── package.json            # React 19, Ant Design 6, Vite 8
│   ├── vite.config.ts          # Dev proxy: /api → localhost:18800
│   ├── src/
│   │   ├── main.tsx            # React DOM entry
│   │   ├── App.tsx             # Root: TopBar + KanbanBoard + CardDetailModal
│   │   ├── App.css
│   │   ├── api/client.ts       # Fetch-based API client (all REST endpoints)
│   │   ├── types/index.ts      # TypeScript interfaces mirroring backend models
│   │   ├── hooks/
│   │   │   ├── useIssues.ts    # Issue list + 5s polling when active
│   │   │   ├── useIssueDetail.ts  # Issue detail + SSE + polling fallback
│   │   │   └── usePolling.ts   # Generic polling hook
│   │   ├── utils/
│   │   │   ├── kanban.ts       # Column definitions, issue-to-column mapping
│   │   │   └── status.ts       # Status/priority → color/label mappings
│   │   └── components/
│   │       ├── TopBar.tsx
│   │       ├── KanbanBoard.tsx
│   │       ├── KanbanColumn.tsx
│   │       ├── IssueCard.tsx
│   │       ├── CardDetailModal.tsx  # Left/right split: metadata + real-time session
│   │       ├── ActionButtons.tsx    # Full status→action matrix
│   │       ├── IssueForm.tsx        # Create issue modal
│   │       ├── IssueDetail.tsx
│   │       ├── IssueList.tsx
│   │       ├── StatusTag.tsx
│   │       ├── RetryInput.tsx
│   │       ├── SpecCard.tsx
│   │       ├── ExecutionTimeline.tsx
│   │       ├── LogViewer.tsx
│   │       └── StepList.tsx
│   └── tsconfig*.json
├── tests/                      # Agent module tests
│   ├── conftest.py             # Test fixtures (tmp DB, mock runtime with local git)
│   ├── test_api.py
│   ├── test_cli.py
│   ├── test_cli_client.py
│   ├── test_config.py
│   ├── test_context.py
│   ├── test_db.py
│   ├── test_e2e.py             # E2E tests (require real opencode CLI)
│   ├── test_event_bus.py
│   ├── test_health.py
│   ├── test_opencode_client.py
│   ├── test_plan_skill.py
│   ├── test_runtime.py
│   ├── test_safety.py
│   ├── test_sse.py
│   └── fixtures/e2e_repo/      # Fixture repo for E2E tests
├── data/                       # Runtime data directory
│   └── mango.db                # SQLite database (gitignored)
├── pyproject.toml              # Root project config (name: mango, Python ≥3.12)
├── overseer.toml               # ⭐ Main configuration file
├── uv.lock                     # UV lockfile
├── start-server.sh             # `uv run python -m agent`
├── start-web.sh                # `cd web && npm run dev`
└── .gitignore
```

---

## 2. Package Management & Build System

### Root Project (`pyproject.toml`)
- **Name**: `mango`
- **Python**: ≥3.12
- **Build**: Hatchling
- **Dependencies**: FastAPI, Uvicorn, aiosqlite, Pydantic, pydantic-settings, httpx
- **CLI entry**: `mango = "agent.cli:main"`
- **Dev deps**: pytest, pytest-asyncio, pytest-timeout
- **NOT a monorepo** — no lerna/nx/turborepo/pnpm-workspace

### Gateway (`gateway/pyproject.toml`)
- **Name**: `mango-gateway` (separate package)
- **Same deps** as root
- Has its own `uv.lock`

### Web (`web/package.json`)
- **Framework**: React 19.2 + Ant Design 6.3
- **Build**: Vite 8, TypeScript 5.9
- **No routing library** (single-page Kanban view)

---

## 3. Configuration Files

### `overseer.toml` — Main Agent Runtime Config
```toml
[server]         port = 18800
[agent]          max_turns = 3, task_timeout = 1800, plan_timeout = 600
[opencode]       command = "opencode", timeout = 300
[project]        workspace = ".", default_branch = "main", remote = "origin", pr_base = "main"
[database]       path = "./data/mango.db"
[security]       allowed_commands = [...], blocked_patterns = [...]
[context]        max_git_diff_lines = 2000, max_result_chars = 5000
```

### `gateway/gateway.toml` — Gateway Config
```toml
[server]         port = 18900, host = "0.0.0.0"
[runtime]        url = "http://localhost:18800", timeout = 30
[session]        timeout_hours = 24, cleanup_interval_minutes = 60
[gateway]        max_wait_timeout = 1800
[database]       path = "./data/gateway.db"
```

### `web/vite.config.ts`
- Dev server port: 5173
- Proxy: `/api` → `http://localhost:18800`

---

## 4. Gateway Module — Communication & Routing

### Entry & Startup
- `gateway/src/mango_gateway/__main__.py` → `main.py` → Uvicorn on port 18900
- `gateway/src/mango_gateway/server/app.py` — FastAPI factory with lifespan:
  - Initializes Gateway DB
  - Creates `RuntimeClient` (HTTP client to Agent Runtime at port 18800)
  - Creates `GatewayService`
  - Starts background cleanup task

### API Routes (`gateway/src/mango_gateway/server/routes.py`)
All under `/api` prefix:
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check + Runtime connectivity probe |
| `/gateway/sessions` | POST | Create session |
| `/gateway/sessions/{id}` | GET | Get session |
| `/gateway/sessions/{id}/close` | POST | Close session |
| `/gateway/sessions/{id}/messages` | GET | Get session messages |
| `/gateway/sessions/{id}/stream` | GET | SSE proxy (relays Runtime SSE) |
| `/gateway/messages` | POST | ⭐ Core endpoint: send message → route to Runtime |

### Core Logic: `GatewayService.send_message()`
The message routing state machine:
1. **No current_issue** → create new Issue + trigger run
2. **current_issue = waiting_human** → retry with message as instruction
3. **current_issue = done/review/cancelled** → unbind, create new issue
4. **current_issue = running/planning** → reject (409)
5. If `wait=true` → consume Runtime SSE until terminal event
6. Persist user + assistant messages

### Communication: `RuntimeClient`
- Pure HTTP client (httpx async) to Agent Runtime's REST API
- Operations: `create_issue`, `run_issue`, `retry_issue`, `get_issue`, `cancel_issue`, `get_issue_executions`
- SSE stream consumption: `stream_issue_events()` — yields parsed event dicts
- **No direct code imports** from agent module — fully decoupled via HTTP

---

## 5. Web Module (React/Kanban)

### Architecture
- **Framework**: React 19 + Ant Design 6 + Vite 8
- **Pattern**: Custom hooks + function components (no Redux/Zustand)
- **State**: `useState` + polling + SSE for real-time updates
- **Proxy**: Vite dev proxy `/api` → `http://localhost:18800` (connects directly to Agent Runtime, NOT Gateway)

### Kanban Column Definitions (`utils/kanban.ts`)
| Column | Title | Agent Role | Statuses |
|--------|-------|------------|----------|
| backlog | Backlog | Refiner | `open` |
| todo | Todo | Orchestrator | `planning`, `planned` |
| dev | Dev | Crafter | `running` |
| review | Review | Guard | `review` |
| done | Done | Reporter | `done` |

**Special**: `waiting_human` and `cancelled` are "overlay states" — card stays in its last logical column (inferred from `pr_url`/`branch_name`/`spec`).

### Key Hooks
- `useIssues()` — fetches all issues, polls every 5s when any are running/planning
- `useIssueDetail(id)` — fetches detail + executions + logs + steps; connects SSE for real-time updates; polling fallback when SSE fails
- `usePolling(callback, interval, enabled)` — generic polling

### Action Matrix (`ActionButtons.tsx`)
| Status | Available Actions |
|--------|-------------------|
| open | Refine (plan), Run, Delete |
| planning | Cancel |
| planned | Run, Reject |
| running | Cancel |
| review | Complete |
| done | Delete |
| waiting_human | Delete (retry via RetryInput) |
| cancelled | Restart (run), Delete |

---

## 6. Agent Execution Module — THE CORE

### Overall Flow
```
Issue created (open)
    │
    ├──[Plan]──→ planning ──→ planned (Spec generated)
    │                              │
    ├──[Run]───────────────────────┤
    │                              ▼
    │                         running
    │                    ┌─── runTask() ───┐
    │                    │  for turn 1..N  │
    │                    │   runTurn()     │
    │                    │    runAttempt() │
    │                    │      ↓ OpenCode│
    │                    └────────────────┘
    │                          │
    │                    ┌─────┴─────┐
    │                    ▼           ▼
    │               success       failure
    │               git commit    ↓
    │               git push      waiting_human
    │               create PR     (human can retry)
    │                   ↓
    │               review
    │                   ↓
    │                 done
    └──[Cancel]──→ cancelled
```

### `AgentRuntime` (agent/agent/runtime.py) — 755 lines, the brain
- **State management**: `_cancel_tokens` (asyncio.Event per issue), `_running_tasks` (asyncio.Task per issue)
- **Entry points**:
  - `start_task(issue_id)` — creates asyncio.Task → `_run_task()`
  - `start_plan(issue_id)` — creates asyncio.Task → `_run_plan()`
  - `cancel_task(issue_id)` — sets cancel event
  - `recover_from_restart()` — recovers stuck running/planning → waiting_human

### `_run_task()` — The main execution loop
1. Update status → `running`
2. Create git branch `agent/{issue_id[:8]}`
3. Create lifecycle execution record (turn=0)
4. Loop `turn = 1..max_turns`:
   - Check cancellation
   - Call `_run_turn()` → `_run_attempt()`
   - If success → break
   - Otherwise accumulate history → next turn
5. On success:
   - `_git_commit()` — stage modified + untracked, commit
   - `_git_push()` — push to remote
   - `_create_pr()` — via `gh pr create` CLI
   - Status → `review` (or `done` if PR creation fails)
6. On failure after all turns: status → `waiting_human`
7. Handles: TimeoutError, CancelledError

### `_run_plan()` — Spec generation
1. Status → `planning`
2. Build plan prompt via `PlanSkill`
3. Run through OpenCode
4. Extract JSON from output (3 strategies: direct parse, code block, regex brace matching)
5. Validate spec (truncation limits)
6. On success: store spec, status → `planned`
7. On failure: retry once with strict prompt, then → `waiting_human`

### `_run_turn()` — Single turn
1. Refresh issue from DB
2. Get git diff
3. Build `TurnContext` (issue, turn number, last result/error, git diff, execution history, human instruction, spec)
4. Create execution record
5. Call `_run_attempt()`
6. Emit SSE events

### `_run_attempt()` — Single attempt
1. Execute via `GenericSkill.execute()` → `OpenCodeClient.run_prompt()`
2. Audit commands in result (safety check)
3. Record duration, status
4. Emit events

### OpenCode Client (`agent/agent/opencode_client.py`)
- Runs `opencode run --dir <cwd> --format json <prompt>` as subprocess
- Streams NDJSON stdout line by line
- Classifies events: `tool_use`, `text`, `step_start`, `step_finish`
- Concurrent stderr drain to prevent pipe deadlock
- Cancel support via asyncio.Event → `proc.kill()`

### Skills System
- `BaseSkill` (ABC): `execute(ctx, cwd, cancel_event, on_event) → str`
- `GenericSkill`: builds rich prompts with safety rules, task context, execution history, spec
- `PlanSkill`: builds spec generation prompts, with strict retry mode

### Safety (`agent/agent/safety.py`)
- `build_safety_prompt()` — injects allowed/blocked commands into prompts
- `validate_command()` — checks first token against allowed list
- `extract_commands_from_result()` — extracts shell commands from AI output for auditing

---

## 7. State Machine / Workflow / Control Flow

### Issue Status State Machine (implicit, in runtime.py + routes.py)
```
                   ┌─────────────────┐
                   │                 │
         ┌────────▼─────────┐       │
         │      open        │◄──────┤ reject-spec (planned→open)
         └──┬───────┬───────┘       │ retry_reset (waiting_human→open)
            │       │               │
       [plan]│  [run]│               │
            │       │               │
    ┌───────▼──┐    │               │
    │ planning │    │               │
    └────┬─────┘    │               │
         │          │               │
    ┌────▼────┐     │               │
    │ planned ├─[run]┤               │
    └─────────┘     │               │
                    │               │
              ┌─────▼─────┐        │
              │  running   │        │
              └─────┬──────┘        │
                    │               │
          ┌─────────┼──────────┐   │
          ▼         ▼          ▼   │
       review     done    waiting_human
          │                    │
     [complete]           [retry]──┘
          │
          ▼
         done

  (cancelled can be reached from running/planning via cancel)
  (waiting_human can be reached from any failure)
```

### No formal state machine library — transitions are enforced via:
1. **API routes**: Check `issue.status` before allowing actions (409 Conflict)
2. **Runtime**: Status updates via `IssueRepo.update_status()`
3. **DB**: Originally had CHECK constraints in SQL, but migration 006 removed them (app-layer validation now)

### No workflow engine — the "workflow" is the `_run_task()` loop:
- Task → Turn → Attempt (3-level nesting)
- Cancel via `asyncio.Event`
- Timeout via `asyncio.timeout()`
- EventBus for real-time SSE streaming

---

## 8. Database Schema (SQLite)

### Agent Runtime DB (`data/mango.db`)

**issues** table:
| Column | Type | Notes |
|--------|------|-------|
| id | TEXT PK | UUID |
| title | TEXT NOT NULL | |
| description | TEXT | Default '' |
| status | TEXT | open/planning/planned/running/review/done/waiting_human/cancelled |
| branch_name | TEXT | `agent/{id[:8]}` |
| human_instruction | TEXT | Retry instruction |
| pr_url | TEXT | GitHub PR URL |
| failure_reason | TEXT | User-visible failure reason |
| workspace | TEXT | Override working directory |
| priority | TEXT | high/medium/low (default: medium) |
| spec | TEXT | JSON spec from PlanSkill |
| created_at | TEXT | datetime |
| updated_at | TEXT | datetime |

**executions** table:
| Column | Type | Notes |
|--------|------|-------|
| id | TEXT PK | UUID |
| issue_id | TEXT FK→issues | |
| turn_number | INTEGER | 0=lifecycle, 1..N=turns |
| attempt_number | INTEGER | |
| status | TEXT | running/completed/failed/cancelled/timeout |
| prompt | TEXT | The prompt sent to OpenCode |
| result | TEXT | Raw OpenCode output |
| error_message | TEXT | |
| context_snapshot | TEXT | JSON of TurnContext |
| git_diff_snapshot | TEXT | |
| duration_ms | INTEGER | |
| started_at | TEXT | |
| finished_at | TEXT | |

**execution_logs** table:
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK AUTO | |
| execution_id | TEXT FK→executions | |
| level | TEXT | info/warn/error |
| message | TEXT | |
| created_at | TEXT | |

**execution_steps** table (migration 004):
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK AUTO | |
| execution_id | TEXT FK→executions | |
| step_type | TEXT | tool_use/text/step |
| tool | TEXT | read/edit/bash/grep/glob/... |
| target | TEXT | file path or command |
| summary | TEXT | |
| created_at | TEXT | |

### Gateway DB (`data/gateway.db`)

**sessions** table:
| Column | Type | Notes |
|--------|------|-------|
| id | TEXT PK | UUID |
| source | TEXT | 'api' / 'cli' / external system |
| source_id | TEXT | External user/channel ID |
| current_issue_id | TEXT | Active issue linked to this session |
| status | TEXT | active/closed/expired |
| runtime_url | TEXT | |
| metadata | TEXT | JSON |
| created_at | TEXT | |
| updated_at | TEXT | |
| closed_at | TEXT | |

**messages** table:
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK AUTO | |
| session_id | TEXT FK→sessions (CASCADE) | |
| role | TEXT | user/assistant/system |
| content | TEXT | |
| issue_id | TEXT | Links message to an issue |
| metadata | TEXT | |
| created_at | TEXT | |

---

## 9. Key Architectural Observations

### What EXISTS:
- ✅ Well-structured 3-tier architecture (Web → Agent Runtime → Gateway)
- ✅ Event-driven real-time updates (EventBus → SSE → Web)
- ✅ Implicit state machine in Issue lifecycle (open→planning→planned→running→review→done)
- ✅ Turn-based retry system (max_turns with context accumulation)
- ✅ Safety/audit system for command validation
- ✅ Skill abstraction (GenericSkill, PlanSkill)
- ✅ Comprehensive test suite
- ✅ Migration-based schema evolution
- ✅ CLI client with SSE streaming

### What DOES NOT EXIST:
- ❌ No formal state machine library (transitions are ad-hoc checks)
- ❌ No workflow engine (just nested async loops)
- ❌ No Docker/Dockerfile/docker-compose
- ❌ No monorepo tooling (each module is independent)
- ❌ No authentication/authorization
- ❌ No queue system (tasks run directly as asyncio.Tasks)
- ❌ No caching layer
- ❌ No observability (no OpenTelemetry/metrics)
- ❌ No WebSocket — uses SSE only
- ❌ No ORM — raw SQL via aiosqlite

### Communication Patterns:
```
[Web UI :5173] ──proxy──→ [Agent Runtime :18800] ←──HTTP──→ [Gateway :18900]
                              ↕ SSE                            ↕ SSE proxy
                              ↕ asyncio subprocess             ↕ HTTP client
                        [OpenCode CLI]
                              ↕
                        [AI Model (external)]
```

