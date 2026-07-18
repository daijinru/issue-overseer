# cc-connect Project Issues Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace issue-overseer’s local agent runtime with a minimal Issue lifecycle that selects a cc-connect project, submits one Bridge task, and renders the final reply.

**Architecture:** `CCConnectClient` is the sole execution adapter. It reads Bridge capabilities to list projects and sends each task with `message.project`. The runtime persists only `pending → running → finished` and one terminal outcome; the web UI consumes those records without workspace paths, local tools, or provider credentials.

**Tech Stack:** Python 3.12, FastAPI, aiosqlite, websockets, pytest, React, TypeScript, Ant Design, react-markdown.

## Global Constraints

- Do not modify files in `../cc-connect`.
- A cc-connect project is the only Agent identifier and determines work directory, permissions, WisCode discovery, provider credentials, and `.claude` behavior.
- Send `CC_CONNECT_BRIDGE_TOKEN` only from the server process. Never persist it in browser code, SQLite, or tracked TOML.
- Without a token, connect without an authentication header and let cc-connect decide whether to accept it.
- Issue states are exactly `pending`, `running`, and `finished`; terminal success/failure belongs to `outcome`.
- The new path has no OpenCode subprocess, local Git/PR, Spec, retry, command audit, workspace picker, or CLI path.

---

### Task 1: Add project discovery and explicit Bridge project routing

**Files:**
- Modify: `agent/agent/cc_connect_client.py`
- Create: `tests/test_cc_connect_client.py`
- Modify: `agent/config.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- `ProjectInfo(name: str)`.
- `async CCConnectClient.list_projects() -> list[ProjectInfo]`.
- `async CCConnectClient.run_task(project: str, content: str, issue_id: str) -> str`.

- [ ] **Step 1: Write the failing project-list test**

```python
@pytest.mark.asyncio
async def test_list_projects_reads_capabilities_snapshot():
    socket = FakeSocket([
        {"type": "register_ack", "ok": True},
        {"type": "capabilities_snapshot", "projects": [{"project": "api"}]},
    ])
    client = CCConnectClient(url="ws://bridge", token="", platform="issue-overseer", connect=lambda *_a, **_k: socket)
    assert [project.name for project in await client.list_projects()] == ["api"]
    assert socket.connect_headers is None
```

- [ ] **Step 2: Write the failing selected-project test**

```python
@pytest.mark.asyncio
async def test_run_task_sends_project_and_stable_issue_session():
    client, socket = bridge_client_replying("done", request_id="r1")
    assert await client.run_task("api", "fix login", "issue-1") == "done"
    assert socket.sent[1]["project"] == "api"
    assert socket.sent[1]["session_key"] == "issue-overseer:issue-1:issue"
```

- [ ] **Step 3: Run the tests and verify red**

Run: `./.venv/bin/python -m pytest tests/test_cc_connect_client.py -q`

Expected: FAIL because `list_projects` and `run_task` do not exist.

- [ ] **Step 4: Implement the minimum protocol methods**

```python
@dataclass(frozen=True)
class ProjectInfo:
    name: str

def _headers(self) -> dict[str, str] | None:
    return {"X-Bridge-Token": self.token} if self.token else None

async def run_task(self, project: str, content: str, issue_id: str) -> str:
    await socket.send(json.dumps({
        "type": "message", "msg_id": request_id, "project": project,
        "session_key": f"{self.platform}:{issue_id}:issue",
        "user_id": "issue-overseer", "content": content, "reply_ctx": request_id,
    }))
```

Read until the matching `reply`. Convert error frames, malformed frames, close events, and timeouts to `CCConnectBridgeError`. Use `Field(default_factory=lambda: os.environ.get("CC_CONNECT_BRIDGE_TOKEN", ""))` for token lookup.

- [ ] **Step 5: Run the focused tests and commit**

Run: `./.venv/bin/python -m pytest tests/test_cc_connect_client.py tests/test_config.py -q`

Expected: PASS.

Commit message: `feat: discover and route cc-connect projects`.

### Task 2: Simplify Issue persistence to project, lifecycle, and outcome

**Files:**
- Modify: `agent/models.py`
- Modify: `agent/db/repos.py`
- Create: `agent/db/migrations/008_simplify_issue_lifecycle.sql`
- Modify: `tests/test_api.py`

**Interfaces:**
- `IssueStatus = pending | running | finished`.
- `IssueOutcome = success | error`.
- `IssueCreate(content: str, project: str)`.
- `IssueRepo.start(issue_id: str) -> bool` atomically changes only `pending` to `running`.
- `IssueRepo.finish(issue_id, outcome, result, error_message) -> None` writes `finished` and `finished_at`.

- [ ] **Step 1: Write failing creation and terminal-outcome tests**

```python
async def test_create_issue_persists_project(client):
    response = await client.post("/api/issues", json={"content": "修复登录", "project": "api"})
    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    assert response.json()["project"] == "api"

async def test_finish_keeps_error_as_terminal_outcome(initialized_db):
    issue = await IssueRepo().create(IssueCreate(content="x", project="api"))
    await IssueRepo().finish(issue.id, IssueOutcome.error, None, "Bridge disconnected")
    saved = await IssueRepo().get(issue.id)
    assert (saved.status, saved.outcome) == (IssueStatus.finished, IssueOutcome.error)
```

- [ ] **Step 2: Run tests and verify red**

Run: `./.venv/bin/python -m pytest tests/test_api.py -k 'persists_project or terminal_outcome' -q`

Expected: FAIL because the title/workspace/agent schema is active.

- [ ] **Step 3: Create migration and model/repository code**

```sql
ALTER TABLE issues ADD COLUMN project TEXT NOT NULL DEFAULT '';
ALTER TABLE issues ADD COLUMN content TEXT NOT NULL DEFAULT '';
ALTER TABLE issues ADD COLUMN outcome TEXT CHECK(outcome IN ('success', 'error'));
ALTER TABLE issues ADD COLUMN result TEXT;
ALTER TABLE issues ADD COLUMN finished_at TEXT;
UPDATE issues SET content = description WHERE content = '';
UPDATE issues SET status = 'pending' WHERE status IN ('open', 'planning', 'planned', 'waiting_human', 'cancelled');
UPDATE issues SET status = 'finished' WHERE status IN ('review', 'done');
```

Expose only content, project, status, outcome, result, error message, and timestamps in new API models. Preserve old database columns only for migration compatibility.

- [ ] **Step 4: Run tests and commit**

Run: `./.venv/bin/python -m pytest tests/test_api.py -k 'persists_project or terminal_outcome' -q`

Expected: PASS.

Commit message: `feat: simplify issue lifecycle data`.

### Task 3: Replace Runtime with one Bridge task and a project-list API

**Files:**
- Modify: `agent/agent/runtime.py`
- Modify: `agent/server/app.py`
- Modify: `agent/server/routes.py`
- Modify: `tests/test_runtime.py`

**Interfaces:**
- `async AgentRuntime.list_projects() -> list[ProjectInfo]`.
- `GET /api/cc-connect/projects` returns `{ "projects": [{"name": "api"}] }`.
- `POST /api/issues/{id}/run` returns HTTP 409 when `IssueRepo.start` returns false.

- [ ] **Step 1: Write failing runtime success and error tests**

```python
@pytest.mark.asyncio
async def test_runtime_sends_content_to_selected_project(mock_runtime):
    issue = await IssueRepo().create(IssueCreate(content="修复登录", project="api"))
    mock_runtime.client.run_task = AsyncMock(return_value="已完成")
    await mock_runtime.start_task(issue.id)
    await mock_runtime.wait_for_task(issue.id)
    mock_runtime.client.run_task.assert_awaited_once_with("api", "修复登录", issue.id)
    assert (await IssueRepo().get(issue.id)).outcome == IssueOutcome.success

@pytest.mark.asyncio
async def test_bridge_failure_finishes_issue_as_error(mock_runtime):
    issue = await IssueRepo().create(IssueCreate(content="x", project="api"))
    mock_runtime.client.run_task = AsyncMock(side_effect=CCConnectBridgeError("offline"))
    await mock_runtime.start_task(issue.id)
    await mock_runtime.wait_for_task(issue.id)
    saved = await IssueRepo().get(issue.id)
    assert (saved.status, saved.outcome, saved.error_message) == (IssueStatus.finished, IssueOutcome.error, "offline")
```

- [ ] **Step 2: Run tests and verify red**

Run: `./.venv/bin/python -m pytest tests/test_runtime.py -k 'selected_project or bridge_failure' -q`

Expected: FAIL because Runtime still enters its old turn, plan, Git, and audit loop.

- [ ] **Step 3: Implement the one-request runtime**

```python
async def _run_task(self, issue_id: str) -> None:
    issue = await self.issue_repo.get(issue_id)
    self._emit(issue_id, "task_start", {"issue_id": issue_id})
    try:
        result = await self.client.run_task(issue.project, issue.content, issue.id)
    except CCConnectBridgeError as exc:
        await self.issue_repo.finish(issue_id, IssueOutcome.error, None, str(exc))
        self._emit(issue_id, "task_end", {"success": False, "error": str(exc)})
    else:
        await self.issue_repo.finish(issue_id, IssueOutcome.success, result, None)
        self._emit(issue_id, "task_end", {"success": True})
```

Remove plan, retry, Git, command-audit, execution-step, and workspace-picker routes. Return HTTP 503 from project discovery when the Bridge is unavailable.

- [ ] **Step 4: Run tests and commit**

Run: `./.venv/bin/python -m pytest tests/test_runtime.py tests/test_api.py -q`

Expected: PASS.

Commit message: `feat: execute issues through cc-connect projects`.

### Task 4: Replace the creation and detail UI with cc-connect project views

**Files:**
- Modify: `web/src/types/index.ts`
- Modify: `web/src/api/client.ts`
- Modify: `web/src/components/IssueForm.tsx`
- Modify: `web/src/components/IssueList.tsx`
- Modify: `web/src/components/CardDetailModal.tsx`
- Modify: `web/src/hooks/useIssueDetail.ts`
- Modify: `web/src/components/ActionButtons.tsx`
- Modify: `web/package.json`

**Interfaces:**
- `type IssueStatus = 'pending' | 'running' | 'finished'`.
- `createIssue({ content: string, project: string }): Promise<Issue>`.
- `getCCConnectProjects(): Promise<Array<{name: string}>>`.

- [ ] **Step 1: Write the failing form and detail tests**

```tsx
await user.type(screen.getByLabelText('任务目标'), '修复登录')
await user.selectOptions(screen.getByLabelText('Agent'), 'api')
await user.click(screen.getByRole('button', { name: '创建' }))
expect(createIssue).toHaveBeenCalledWith({ content: '修复登录', project: 'api' })

render(<CardDetailModal issue={{ status: 'finished', outcome: 'success', result: '## Done', project: 'api' }} />)
expect(screen.getByRole('heading', { name: 'Done' })).toBeInTheDocument()
```

- [ ] **Step 2: Run tests and verify red**

Run: `npm run test -- --run IssueForm CardDetailModal`

Expected: FAIL because the UI still asks for workspace and fixed WisCode and displays executions, logs, steps, PRs, and retry controls.

- [ ] **Step 3: Implement minimal screens**

Fetch `/api/cc-connect/projects` when the create modal opens. Disable submit and show its error if project discovery fails. Retain only required task content and project select. Detail shows project, timestamps, status, Markdown result via `react-markdown`, or terminal error. Use SSE only to refetch after `task_end`; remove execution/log/step polling and old actions.

- [ ] **Step 4: Build and commit**

Run: `npm run build`

Expected: PASS.

Commit message: `feat: render cc-connect project issue results`.

### Task 5: Delete obsolete local-agent modules and verify isolation

**Files:**
- Delete: `agent/agent/opencode_client.py`
- Delete: `agent/skills/base.py`
- Delete: `agent/skills/plan.py`
- Delete: `tests/test_opencode_client.py`
- Delete: `tests/test_plan_skill.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: setup documentation nearest to `README.md`

- [ ] **Step 1: Write the failing legacy guard test**

```python
def test_runtime_has_no_local_opencode_dependency():
    source = Path('agent/agent/runtime.py').read_text()
    assert 'OpenCodeClient' not in source
    assert 'create_subprocess_exec' not in source
```

- [ ] **Step 2: Run guard and verify red**

Run: `./.venv/bin/python -m pytest tests/test_runtime.py::test_runtime_has_no_local_opencode_dependency -q`

Expected: FAIL until old modules and imports are removed.

- [ ] **Step 3: Delete legacy files and document the new setup**

Document only cc-connect Bridge URL and optional `CC_CONNECT_BRIDGE_TOKEN`. Do not document a WisCode path, Anthropic key, OpenCode command, or workspace picker.

- [ ] **Step 4: Run full verification and commit**

Run: `./.venv/bin/python -m pytest -q && npm run build && git diff --check && git -C ../cc-connect status --short`

Expected: tests/build PASS, no whitespace errors, and no cc-connect output.

Commit message: `refactor: make cc-connect the only issue executor`.

## Plan self-review

- Spec coverage: Tasks 1–3 cover project discovery, selected project routing, optional authentication, error handling, concurrency, and the three-state lifecycle. Task 4 covers the minimal creation/result UI. Task 5 removes the old execution surface and confirms cc-connect remains untouched.
- Placeholder scan: no TODO, TBD, or deferred implementation markers are present.
- Type consistency: `ProjectInfo`, `IssueStatus`, `IssueOutcome`, `IssueCreate(content, project)`, `list_projects`, and `run_task(project, content, issue_id)` are introduced before they are consumed.
