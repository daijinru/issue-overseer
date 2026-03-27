# Mango ROADMAP 4 — Project + Clone + Memory

> Issue 进来，PR 出去。项目隔离，自动 Clone，经验沉淀。

---

## 里程碑 3 完成情况

Kanban Board + Spec 阶段全部完成。五列看板（Backlog / Todo / Dev / Review / Done）映射 Issue 全生命周期，Card Detail Modal 左右分栏展示元数据和实时 Session。PlanSkill 生成结构化 Spec，GenericSkill 注入 Spec 执行。状态机扩展至 8 个状态，Issue 编辑/删除按状态守卫。后端 ~900 行 Python，前端 ~1500 行 TypeScript。

**当前核心限制**：

| 限制 | 现状 | 影响 |
|------|------|------|
| 无 Project 概念 | `workspace` 是 Issue 上的路径字符串，git 配置（`default_branch`/`remote`/`pr_base`）全局共享 | 多仓库场景下 Issue 混杂，无法按项目过滤，git 配置冲突 |
| 无 Clone 管理 | 用户必须手动指定本地路径，Mango 不管仓库从哪来 | 部署到新环境需要手动 clone，脏状态无自动恢复 |
| 无 Memory 系统 | 每个 Issue 执行从零开始，不了解项目约定和历史经验 | AI 重复犯同样的错误，不知道项目的编码风格、测试惯例、已踩过的坑 |
| Skill 无项目感知 | GenericSkill / PlanSkill 的 prompt 只包含 Issue + Turn 状态 | AI 无法利用跨 Issue 积累的知识 |

---

## 里程碑 4 目标

引入三个核心能力（原 M4 + M4.5 合并，一步到位）：

1. **Project 实体** — 最上层组织单元，DB + Web UI 动态管理。`repo_url` 是唯一入口，Mango 自动 clone。Issue 隶属 Project。
2. **Clone 管理** — 异步 clone + 脏状态检测 + 自动恢复 + SSE 通知前端。
3. **Memory 系统** — 两层架构（Issue Memory + Project Memory），与 Skill 深度集成。

### 设计约束

- **仍然 1:1**：1 Issue = 1 次执行，不做任务拆分
- **仍然串行**：不并发，不做多 Agent 后端
- **Memory 是被动的**：Issue Memory 自动生成，Project Memory 按需归纳，不做主动学习
- **Project 是必选的**：里程碑 4 完成后，每个 Issue 必须属于一个 Project
- **不兼容遗留**：不创建 default Project，不保留 `workspace` 列，干净切换
- **`repo_url` 唯一入口**：不允许手动填 `local_path`，`local_path = {workspace}/{project_id}` 自动生成
- **脏状态统一处理**：local_path 存在但不是有效 git repo、clone 不完整、remote 不匹配 → 删除目录重新 clone

### 关键设计决策

| # | 决策 | 理由 |
|---|------|------|
| 1 | 沿用 `workspace`（不用 `cache_dir`） | TOML `[project].workspace` 语义变为 clone 的父目录，保持配置键名不变 |
| 2 | `local_path = {workspace}/{project_id}` | 用 project_id 作为目录名，天然唯一，无冲突 |
| 3 | 不兼容遗留 Project | 无需 `default` 项目、无需迁移旧 Issue 的 workspace，干净起步 |
| 4 | 脏状态删除重 clone | 不做复杂恢复逻辑，遇到任何异常状态直接 `shutil.rmtree` + 重新 clone |
| 5 | SSE 通知 clone 状态 | 复用现有 EventBus（`"project:{id}"` 作为 channel key），前端订阅即时感知 |
| 6 | 删除 `_resolve_workspace` | clone 管理后 `local_path` 是确定性的，三层搜索逻辑多余 |
| 7 | Project 存 DB，不存 TOML | TOML 是静态配置，Project 需要动态增删。`[project]` 段保留为创建 Project 时的默认值 |
| 8 | Issue Memory 自动生成，Project Memory 手动归纳 | 自动生成低风险（失败不影响流程）；自动归纳可能消耗大量 token，时机不好控制，由用户决定 |
| 9 | Memory 注入 prompt 最前面（Task 之前） | 让 AI 先了解项目背景再看任务，类似人类先看 README 再写代码 |
| 10 | Memory 生成失败不阻塞主流程 | Memory 是增值功能，不应影响核心链路（Issue → PR）的可靠性 |

---

## Project 设计

### 现状

```python
# config.py — 全局单例
class ProjectConfig(BaseModel):
    workspace: str = "."
    default_branch: str = "main"
    remote: str = "origin"
    pr_base: str = "main"

# models.py — Issue 上的路径字符串
class Issue(BaseModel):
    workspace: str | None = None  # 无 FK，无分组
```

### 新设计

Project 成为一等实体，存 DB，通过 Web UI 动态管理。`repo_url` 是唯一入口，`local_path` 自动生成：

```python
class Project(BaseModel):
    id: str
    name: str
    repo_url: str                          # "git@github.com:user/repo.git"（用户填写）
    local_path: str                        # 自动生成："{workspace}/{project_id}"
    clone_status: CloneStatus = CloneStatus.pending   # pending → cloning → ready → error
    clone_error: str | None = None         # clone 失败时的错误信息
    default_branch: str = "main"
    remote: str = "origin"
    pr_base: str = "main"
    description: str = ""
    created_at: str | None = None
    updated_at: str | None = None
```

Issue 用 `project_id` 替代 `workspace`（非废弃保留，直接删除 workspace 列）：

```python
class Issue(BaseModel):
    project_id: str | None = None          # FK → projects.id
    # workspace 列已删除
```

Runtime 从 Project 读取 git 配置和工作目录，不再依赖全局 `[project]`：

```python
# runtime.py — 之前
workspace = self._resolve_workspace(issue)
remote = self.settings.project.remote

# runtime.py — 之后
project = await self._get_project_for_issue(issue)
workspace = project.local_path
remote = project.remote
```

`overseer.toml` 的 `[project]` 段语义变更：

```toml
[project]
workspace = "./workspaces"    # clone 的父目录（不再是 git repo 路径）
default_branch = "main"       # 创建 Project 时的默认值
remote = "origin"             # 创建 Project 时的默认值
pr_base = "main"              # 创建 Project 时的默认值
```

### Clone 管理

```
用户创建 Project:
  repo_url: "git@github.com:user/vue3-template.git"

                    ↓ POST /api/projects

Mango 自动:
  1. project_id = uuid4()
  2. local_path = "{workspace}/{project_id}"
  3. asyncio.create_task(clone)
  4. Project.clone_status = "cloning"
  5. SSE emit "clone_status_changed" to channel "project:{project_id}"

                    ↓ clone 完成

  6. Project.clone_status = "ready"
  7. SSE emit "clone_status_changed" {status: "ready"}
  8. 此时才允许创建 Issue / Run
```

**脏状态检测**（clone 前执行）：

```python
def _is_valid_repo(path, expected_url, remote) -> bool:
    """检查 path 是否是有效 git repo 且 remote URL 匹配。"""
    # 1. .git/HEAD 是否存在
    # 2. git remote get-url {remote} 输出是否匹配 expected_url
    # 任一不满足 → 返回 False
```

- `local_path` 不存在 → 正常 clone
- `local_path` 存在 + 有效 repo + remote 匹配 → 跳到 ready
- `local_path` 存在 + 任何异常 → `shutil.rmtree` → 重新 clone

**Repo 同步**（每次 Run 前）：

```python
async def sync_repo(project) -> bool:
    """fetch --all → checkout default_branch → pull --ff-only"""
```

### ProjectService

clone 管理逻辑独立为 `ProjectService` 类，与 Runtime 分离：

```
AgentRuntime
  ├── ProjectService (clone / validate / sync / reclone)
  │     ├── start_clone(project) → asyncio.create_task
  │     ├── reclone(project) → rmtree + start_clone
  │     ├── sync_repo(project) → fetch + checkout + pull
  │     └── _is_valid_repo(path, url, remote) → bool
  └── ... 现有 Runtime 逻辑
```

---

## Memory 设计

### 两层架构

```
┌─────────────────────────────────────────────────────┐
│                   Project Memory                     │
│  "项目使用 pytest-asyncio，测试文件放 tests/ 下"       │
│  "API 路由在 routes.py，使用 APIRouter prefix"        │
│  "修改 models.py 后必须同步更新 migration"              │
│                                                      │
│  ← DistillSkill 从多条 Issue Memory 归纳              │
│  → 注入 GenericSkill + PlanSkill 的 prompt             │
├──────────────────────────────────────────────────────┤
│  Issue Memory #1   │  Issue Memory #2   │  Issue #3  │
│  "修复了登录 bug,   │  "添加了 SSE 端点,  │  (进行中)  │
│   根因是 token 过   │   关键是 EventBus   │            │
│   期未刷新，改了    │   的 pub/sub 模式,  │            │
│   auth.py 和       │   前端 EventSource  │            │
│   test_auth.py"    │   需要 fallback"    │            │
└────────────────────┴────────────────────┴────────────┘
```

### Issue Memory — 执行后的原始总结

**触发时机**：Issue 进入 `review` 状态后（PR 创建成功），Runtime 自动调用 `SummarizeSkill` 生成总结。

**SummarizeSkill 输入**：
- Issue title + description
- 最终 git diff（实际改动）
- 执行历史（哪些轮成功/失败，遇到了什么问题）
- Spec（如果有的话）

**SummarizeSkill 输出**（结构化 JSON）：

```json
{
  "summary": "修复了登录页面 token 过期后未自动刷新的 bug",
  "root_cause": "auth.py 中 refresh_token() 在 401 时未触发",
  "changes": ["src/auth.py", "tests/test_auth.py"],
  "lessons": [
    "修改认证逻辑后必须同时更新 test_auth.py",
    "token 刷新逻辑在 auth.py:L45 的 try-except 中"
  ],
  "tags": ["bugfix", "auth", "token"]
}
```

**存储**：`issue_memories` 表，与 Issue 1:1 关联。

**容错**：Memory 生成失败不影响 Issue 状态（已经是 `review`），只记录 warn 日志。

### Project Memory — 归纳的项目级知识

**触发方式**：用户手动触发 `POST /api/projects/{id}/distill`（不做自动归纳，避免不可控的 token 消耗）。

**DistillSkill 输出**（纯文本，Markdown 格式）：

```markdown
## 项目约定
- 测试框架: pytest-asyncio，测试文件放 tests/ 目录
- API 路由使用 FastAPI APIRouter，prefix="/api"
- 数据库变更需同步 migration SQL

## 常见陷阱
- 修改 models.py 后必须更新 repos.py 的字段白名单
- OpenCode 子进程需要 cancel_event 传播

## 代码结构
- Agent Runtime: src/mango/agent/runtime.py
- Skills: src/mango/skills/
- DB Repos: src/mango/db/repos.py
```

**存储**：`project_memories` 表，每次归纳插入新版本（保留历史），查询时取最新。

### Memory 与 Skill 的关系

```
                    ┌──────────────┐
                    │ TurnContext  │
                    │              │
                    │  issue       │
                    │  turn_number │
                    │  git_diff    │
                    │  spec        │
                    │  ...         │
                    │              │
                    │ +project_memory ← 新增字段
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        GenericSkill   PlanSkill   SummarizeSkill
              │            │            │
              ▼            ▼            ▼
    ## Project Context  ## Context   (不注入 memory,
    {project_memory}    {memory}     它生成 memory)
    ## Task             ## Task
    ## Safety Rules     ## Instructions
    ...                 ...
```

**注入位置**：prompt 最前面，在 Task 之前。

**token 预算**：Project Memory 注入前截断到 `context.max_project_memory_chars`（默认 3000 字符）。

---

## 数据模型变更

### 新增表

```sql
-- ============================================================
-- Migration 007: Project + Clone + Memory（合并 M4 + M4.5）
-- ============================================================

PRAGMA foreign_keys=OFF;

-- 1. projects 表（含 clone 管理字段）
CREATE TABLE projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  repo_url TEXT NOT NULL,
  local_path TEXT NOT NULL,
  clone_status TEXT NOT NULL DEFAULT 'pending',
  clone_error TEXT,
  default_branch TEXT NOT NULL DEFAULT 'main',
  remote TEXT NOT NULL DEFAULT 'origin',
  pr_base TEXT NOT NULL DEFAULT 'main',
  description TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);

-- 2. 重建 issues 表：删除 workspace 列，新增 project_id
CREATE TABLE issues_new (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'open',
  branch_name TEXT,
  human_instruction TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now')),
  pr_url TEXT,
  failure_reason TEXT,
  priority TEXT DEFAULT 'medium',
  spec TEXT,
  project_id TEXT REFERENCES projects(id)
);

INSERT INTO issues_new (id, title, description, status, branch_name,
  human_instruction, created_at, updated_at, pr_url, failure_reason, priority, spec)
SELECT id, title, description, status, branch_name,
  human_instruction, created_at, updated_at, pr_url, failure_reason, priority, spec
FROM issues;

DROP TABLE issues;
ALTER TABLE issues_new RENAME TO issues;

-- 3. issue_memories 表
CREATE TABLE issue_memories (
  id TEXT PRIMARY KEY,
  issue_id TEXT NOT NULL UNIQUE REFERENCES issues(id),
  project_id TEXT NOT NULL REFERENCES projects(id),
  summary TEXT NOT NULL,
  root_cause TEXT,
  changes TEXT,                             -- JSON: 变更文件列表
  lessons TEXT,                             -- JSON: 经验教训列表
  tags TEXT,                                -- JSON: 标签列表
  raw_json TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now'))
);

-- 4. project_memories 表（带版本）
CREATE TABLE project_memories (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  version INTEGER NOT NULL DEFAULT 1,
  content TEXT NOT NULL,                    -- Markdown 格式的项目知识
  source_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now'))
);

-- 5. 索引
CREATE INDEX idx_issues_status ON issues(status);
CREATE INDEX idx_issues_project ON issues(project_id);
CREATE INDEX idx_issue_memories_project ON issue_memories(project_id);
CREATE INDEX idx_project_memories_project ON project_memories(project_id);
CREATE UNIQUE INDEX idx_project_memories_version ON project_memories(project_id, version);

PRAGMA foreign_keys=ON;
```

### 模型变更

```python
# models.py 新增

class CloneStatus(str, Enum):
    pending = "pending"
    cloning = "cloning"
    ready = "ready"
    error = "error"

class Project(BaseModel):
    id: str
    name: str
    repo_url: str
    local_path: str
    clone_status: CloneStatus = CloneStatus.pending
    clone_error: str | None = None
    default_branch: str = "main"
    remote: str = "origin"
    pr_base: str = "main"
    description: str = ""
    created_at: str | None = None
    updated_at: str | None = None

class ProjectCreate(BaseModel):
    name: str
    repo_url: str
    description: str = ""
    default_branch: str | None = None       # None → 用 TOML 默认值
    remote: str | None = None
    pr_base: str | None = None

class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    default_branch: str | None = None
    remote: str | None = None
    pr_base: str | None = None

class IssueMemory(BaseModel):
    id: str
    issue_id: str
    project_id: str
    summary: str
    root_cause: str | None = None
    changes: list[str] = []
    lessons: list[str] = []
    tags: list[str] = []
    raw_json: str
    created_at: str | None = None

class ProjectMemory(BaseModel):
    id: str
    project_id: str
    version: int
    content: str                            # Markdown
    source_count: int = 0
    created_at: str | None = None

# Issue 变更
class Issue(BaseModel):
    # ... 现有字段 ...
    project_id: str | None = None           # 替代 workspace（workspace 列已删除）

# IssueCreate 变更
class IssueCreate(BaseModel):
    title: str
    description: str = ""
    project_id: str                         # 必填
    priority: IssuePriority = IssuePriority.medium

# IssueRetry 变更
class IssueRetry(BaseModel):
    human_instruction: str | None = None
    # workspace 已删除——路径由 Project 决定，retry 时不允许改

# TurnContext 变更
@dataclass
class TurnContext:
    # ... 现有字段 ...
    project_memory: str | None = None       # 新增：Project Memory 文本
```

---

## 新增 Skill

### SummarizeSkill

```python
# skills/summarize.py

class SummarizeSkill:
    """Issue 完成后生成结构化总结，存入 issue_memories。

    不继承 BaseSkill——纯 prompt 构建 + JSON 提取，
    直接调用 client.run_prompt()，类似 _run_plan 的模式。
    """
```

**触发位置**：`runtime.py` 的 `_run_task()` 中，PR 创建成功、Issue 进入 `review` 之后。

**JSON 提取函数迁移**：`extract_spec_json()` 从 `plan.py` 提取为公共函数 `utils/json_extract.py`，SummarizeSkill 复用。

### DistillSkill

```python
# skills/distill.py

class DistillSkill:
    """从多条 Issue Memory 归纳 Project Memory。

    不继承 BaseSkill——纯 prompt 构建类，
    由 Runtime 的 _run_distill() 调用 client.run_prompt() 执行。
    """
```

**触发方式**：`POST /api/projects/{id}/distill`，用户手动触发。

---

## 实施步骤

### 第一步：DB + Models + Config + Repos

> Project 表 + Clone 字段 + Issue 迁移 + Repo 层。一次 migration，不分两步。

**新增** `src/mango/db/migrations/007_project_clone_memory.sql`（见上文完整 SQL）

**修改** `src/mango/models.py`
- 新增 `CloneStatus`、`Project`、`ProjectCreate`、`ProjectUpdate`、`IssueMemory`、`ProjectMemory`
- `Issue`：删除 `workspace`，新增 `project_id`
- `IssueCreate`：`workspace` → `project_id`（必填）
- `IssueRetry`：删除 `workspace`
- `TurnContext`：新增 `project_memory`

**修改** `src/mango/config.py`
- `ProjectConfig.workspace` 默认值 `"."` → `"./workspaces"`
- 新增 `ContextConfig.max_project_memory_chars = 3000`
- 新增 `ContextConfig.max_memory_versions = 10`

**修改** `src/mango/db/repos.py`
- 新增 `ProjectRepo`（create / get / list_all / update_fields / delete）
  - `delete()` 检查关联 Issue，有 Issue 则拒绝
- 新增 `IssueMemoryRepo`（create / list_by_project / get_by_issue）
- 新增 `ProjectMemoryRepo`（create / get_latest_by_project / 版本清理）
- `_ALLOWED_ISSUE_FIELDS`：移除 `workspace`，新增 `project_id`
- `IssueRepo.create()`：INSERT SQL `workspace` → `project_id`
- `IssueRepo.retry_reset()`：删除 `workspace` 参数及相关 SQL
- `IssueRepo.list_all()`：新增 `project_id` 可选过滤参数
- `IssueRepo.delete()`：级联删除 `issue_memories`

**涉及文件**

| 文件 | 变更类型 |
|------|---------|
| `src/mango/db/migrations/007_project_clone_memory.sql` | **新增** |
| `src/mango/models.py` | 修改 |
| `src/mango/config.py` | 修改 |
| `src/mango/db/repos.py` | 修改 |

**验收标准**

- [ ] Migration 007 干净执行
- [ ] Project CRUD 正常（ProjectRepo）
- [ ] Issue 创建用 `project_id`
- [ ] `IssueRepo.list_all(project_id=xxx)` 过滤正常
- [ ] `retry_reset()` 不再接受 `workspace`

---

### 第二步：ProjectService（Clone 管理）

> 独立的 clone / validate / sync / reclone 逻辑。

**新增** `src/mango/agent/project_service.py`

```python
class ProjectService:
    """管理 Project 的 git clone 生命周期。"""

    def compute_local_path(self, project_id: str) -> str:
        """local_path = {workspace}/{project_id}"""

    async def start_clone(self, project: Project) -> None:
        """异步 clone，通过 SSE 通知前端。"""

    async def _do_clone(self, project: Project) -> None:
        """clone 主流程：脏状态检测 → 清理 → clone → 更新状态。"""

    async def reclone(self, project: Project) -> None:
        """强制删除 + 重新 clone。"""

    async def sync_repo(self, project: Project) -> bool:
        """fetch --all → checkout default_branch → pull --ff-only。"""

    def _is_valid_repo(self, path, expected_url, remote) -> bool:
        """检查 .git/HEAD + remote URL 匹配。"""
```

- SSE 通知：通过 EventBus，channel key = `"project:{project_id}"`
- 脏状态处理：`local_path` 存在但 `_is_valid_repo()` 返回 False → `shutil.rmtree` → 继续 clone
- `_is_valid_repo` 检查：`.git/HEAD` 存在 + `git remote get-url {remote}` 输出匹配 `repo_url`

**修改** `src/mango/server/sse.py`
- 新增 `project_sse_stream(event_bus, channel)`：收到 `clone_status_changed` 且 `status in (ready, error)` 时自动终止

**涉及文件**

| 文件 | 变更类型 |
|------|---------|
| `src/mango/agent/project_service.py` | **新增** |
| `src/mango/server/sse.py` | 修改 |

**验收标准**

- [ ] `compute_local_path` 正确拼接 `{workspace}/{project_id}`
- [ ] clone 成功 → DB 状态 `ready` + SSE 事件
- [ ] clone 失败 → DB 状态 `error` + `clone_error` + SSE 事件
- [ ] 脏状态 → 删除目录 → 重新 clone
- [ ] `sync_repo` 执行 fetch + checkout + pull
- [ ] reclone 强制删除后重新 clone

---

### 第三步：Runtime 改造

> 删除 `_resolve_workspace`，接入 Project 和 ProjectService。

**修改** `src/mango/agent/runtime.py`

- `__init__`：新增 `ProjectRepo` + `ProjectService`
- **删除** `_resolve_workspace()` 和 `_is_git_repo()` 两个方法
- **新增** `_get_project_for_issue(issue)` → 查 DB + 校验 `clone_status == ready`
- `_run_plan()`：`self._resolve_workspace(issue)` → `project = await self._get_project_for_issue(issue); workspace = project.local_path`
- `_run_task()`：同上 + 在创建分支前调用 `self.project_service.sync_repo(project)`（sync 失败只 warn，不阻塞）
- `_run_turn()`：同上
- Git 操作方法改为接收参数（不再读 `self.settings.project.*`）：
  - `_git_push(branch, *, cwd, remote)` — 新增 `remote` 参数
  - `_create_pr(branch, issue, *, cwd, pr_base)` — 新增 `pr_base` 参数
  - `_get_changed_files(branch, *, cwd, pr_base)` — 新增 `pr_base` 参数
  - `_get_git_diff(*, cwd, default_branch)` — 新增 `default_branch` 参数
- 调用处传入 `project.remote` / `project.pr_base` / `project.default_branch`

**涉及文件**

| 文件 | 变更类型 |
|------|---------|
| `src/mango/agent/runtime.py` | 修改 |

**验收标准**

- [ ] `_resolve_workspace` 和 `_is_git_repo` 已删除
- [ ] Runtime 从 Project 读取 git 配置（remote / pr_base / default_branch）
- [ ] `_run_task` 执行前调用 `sync_repo`
- [ ] project `clone_status != ready` 时 `_get_project_for_issue` 抛 ValueError

---

### 第四步：Routes（Project CRUD + SSE + Issue 适配）

> API 端点变更，前后端接口对齐。

**修改** `src/mango/server/routes.py`

新增 Project 端点：
```
POST   /api/projects                创建 Project（触发异步 clone）
GET    /api/projects                列表（可选 clone_status 过滤）
GET    /api/projects/{id}           详情
PATCH  /api/projects/{id}           编辑
DELETE /api/projects/{id}           删除（有 Issue 则 409，级联清理 project_memories）
POST   /api/projects/{id}/reclone   强制重新 clone
GET    /api/projects/{id}/stream    SSE clone 状态流
```

修改 Issue 端点：
- `POST /api/issues`：校验 `project_id` 对应的 Project 存在
- `POST /api/issues/{id}/run`：校验 project `clone_status == ready`，否则 409
- `POST /api/issues/{id}/plan`：同上
- `POST /api/issues/{id}/retry`：去掉 `workspace`
- `GET /api/issues`：新增 `project_id` 查询参数

Memory 端点（第五步实现时才加，此处预留）：
```
POST   /api/projects/{id}/distill          触发归纳 Project Memory
GET    /api/projects/{id}/memory           查看最新 Project Memory
GET    /api/projects/{id}/memories         查看历史版本
GET    /api/projects/{id}/issue-memories   查看 Project 下所有 Issue Memory
GET    /api/issues/{id}/memory             查看单条 Issue Memory
```

**涉及文件**

| 文件 | 变更类型 |
|------|---------|
| `src/mango/server/routes.py` | 修改 |

**验收标准**

- [ ] Project CRUD API 正常工作
- [ ] 创建 Project 触发异步 clone
- [ ] clone 状态通过 SSE stream 推送
- [ ] 创建 Issue 时必须指定有效 `project_id`
- [ ] Run / Plan 检查 project clone_status
- [ ] retry 不再传 workspace

---

### 第五步：Issue Memory + Project Memory（SummarizeSkill + DistillSkill）

> Memory 生成和注入。

**新增** `src/mango/skills/summarize.py`
- `SummarizeSkill`：不继承 `BaseSkill`，纯 prompt 构建 + JSON 提取
- 复用 `extract_spec_json()` 的 JSON 提取逻辑

**新增** `src/mango/utils/json_extract.py`
- 从 `plan.py` 提取 `extract_spec_json()` 为公共函数

**新增** `src/mango/skills/distill.py`
- `DistillSkill`：纯 Markdown 输出，不需要 JSON 提取

**修改** `src/mango/skills/plan.py`
- `extract_spec_json` 改为从 `utils/json_extract.py` 导入

**修改** `src/mango/agent/context.py`
- `build_turn_context()` 新增 `project_memory` 参数 + 截断逻辑

**修改** `src/mango/skills/base.py`（GenericSkill）
- `_build_prompt()`：在 Task 之前注入 `## Project Context`

**修改** `src/mango/skills/plan.py`（PlanSkill）
- `_build_plan_prompt()`：同上

**修改** `src/mango/agent/runtime.py`
- `_run_task()`：PR 创建成功后异步生成 Issue Memory
- `_run_turn()`：构建 TurnContext 时从 DB 读取最新 Project Memory 注入
- 新增 `start_distill(project_id)` + `_run_distill(project_id)`

**修改** `src/mango/server/routes.py`
- 新增 Memory 相关端点

**涉及文件**

| 文件 | 变更类型 |
|------|---------|
| `src/mango/skills/summarize.py` | **新增** |
| `src/mango/utils/json_extract.py` | **新增** |
| `src/mango/skills/distill.py` | **新增** |
| `src/mango/skills/plan.py` | 修改 |
| `src/mango/agent/context.py` | 修改 |
| `src/mango/skills/base.py` | 修改 |
| `src/mango/agent/runtime.py` | 修改 |
| `src/mango/server/routes.py` | 修改 |

**验收标准**

- [ ] Issue 进入 `review` 后 `issue_memories` 表自动写入
- [ ] Memory 生成失败不影响 Issue 状态
- [ ] `POST /api/projects/{id}/distill` 从 Issue Memories 归纳 Project Memory
- [ ] GenericSkill / PlanSkill prompt 包含 `## Project Context`
- [ ] Project Memory 超过 3000 字符时自动截断
- [ ] 无 Project Memory 时 Skill prompt 不包含空段落

---

### 第六步：前端

> Project 管理 + Clone 状态 + Memory 展示。

**修改** `web/src/types/index.ts`
- 新增 `CloneStatus`、`Project`、`ProjectCreateRequest`、`ProjectUpdateRequest`
- `Issue`：`workspace` → `project_id`
- `IssueCreateRequest`：`workspace` → `project_id`（必填）
- `IssueRetryRequest`：删除 `workspace`

**修改** `web/src/api/client.ts`
- 新增 Project API（createProject, listProjects, getProject, updateProject, deleteProject, recloneProject）
- `listIssues` 新增 `projectId` 可选参数

**新增** `web/src/components/ProjectForm.tsx`
- 创建 Project 的 Modal（name, repo_url, description, 可选 git 配置）
- 创建后订阅 SSE 监听 clone 状态

**新增** `web/src/components/ProjectList.tsx`
- Project 列表 + clone 状态指示 + reclone / delete 操作

**修改** `web/src/components/IssueForm.tsx`
- workspace 文本输入 → Project 下拉选择（只显示 `clone_status=ready` 的 Project）

**修改** `web/src/components/RetryInput.tsx`
- 删除 workspace 输入框和相关逻辑

**修改** `web/src/components/CardDetailModal.tsx`
- workspace 显示 → project 信息显示

**修改** `web/src/components/TopBar.tsx`
- 新增 Project 选择器 / Project 管理入口

**修改** `web/src/hooks/useIssues.ts`
- 新增 `project_id` 过滤参数

**新增** `web/src/hooks/useProjects.ts`

**新增** `web/src/components/ProjectSelector.tsx`
**新增** `web/src/components/ProjectSettings.tsx`
**新增** `web/src/components/MemoryTab.tsx`

**修改** `web/src/App.tsx`
- 新增 `currentProjectId` 状态管理（localStorage 持久化）

**涉及文件**

| 文件 | 变更类型 |
|------|---------|
| `web/src/types/index.ts` | 修改 |
| `web/src/api/client.ts` | 修改 |
| `web/src/components/ProjectForm.tsx` | **新增** |
| `web/src/components/ProjectList.tsx` | **新增** |
| `web/src/components/ProjectSelector.tsx` | **新增** |
| `web/src/components/ProjectSettings.tsx` | **新增** |
| `web/src/components/MemoryTab.tsx` | **新增** |
| `web/src/hooks/useProjects.ts` | **新增** |
| `web/src/components/IssueForm.tsx` | 修改 |
| `web/src/components/RetryInput.tsx` | 修改 |
| `web/src/components/CardDetailModal.tsx` | 修改 |
| `web/src/components/TopBar.tsx` | 修改 |
| `web/src/hooks/useIssues.ts` | 修改 |
| `web/src/App.tsx` | 修改 |

**验收标准**

- [ ] TopBar Project 选择器正确切换，Kanban 按 Project 过滤
- [ ] 创建 Project 后前端实时显示 clone 进度
- [ ] clone 完成 / 失败后前端正确更新状态
- [ ] 新建 Issue 时必须选 Project（下拉选择当前 Project）
- [ ] retry 不再显示 workspace 输入
- [ ] Project 设置页展示 Memory，"归纳知识" 按钮可用

---

### 第七步：测试

> 基础测试适配在各步骤中同步完成，本步骤聚焦新增测试和端到端验证。

**修改** `tests/conftest.py`
- `mock_runtime` fixture：创建 DB Project 记录替代 `settings.project.workspace`

**修改** `tests/test_db.py`
- Migration 007 验证 + Project / Memory DB 测试

**修改** `tests/test_api.py`
- Issue 创建加 `project_id`、Project API 测试、clone 守卫测试

**修改** `tests/test_runtime.py`
- 删除 `_resolve_workspace` 测试、改用 Project、测试 sync_repo

**修改** `tests/test_plan_skill.py`
- `extract_spec_json` 测试迁移到 `test_json_extract.py`，import 路径更新

**新增** `tests/test_project_service.py`
- clone / reclone / dirty state / sync / _is_valid_repo 测试

**新增** `tests/test_json_extract.py`
- 公共 JSON 提取函数的边界用例

**新增** `tests/test_memory.py`
- SummarizeSkill / DistillSkill / Memory 注入 prompt

**端到端验证流程**

- [ ] **完整链路**：创建 Project → clone ready → 创建 Issue → Run → PR → review → Issue Memory 自动生成 → 手动 Distill → Project Memory 生成 → 新 Issue Run → prompt 包含 Project Context
- [ ] **多 Project 隔离**：两个 Project 各自的 Issue 不互相影响，Memory 隔离
- [ ] **Clone 异常恢复**：clone 失败 → 前端看到 error → reclone → 成功
- [ ] **脏状态恢复**：手动损坏 local_path → reclone → 自动清理 + 重新 clone
- [ ] **Memory 容错**：SummarizeSkill 失败 → Issue 仍为 review，warn 日志
- [ ] **token 预算**：超长 Project Memory 被截断，不影响 Skill 执行

---

## 文件清单汇总

### 新增文件（14 个）

| # | 文件 | 所属阶段 |
|---|------|---------|
| 1 | `src/mango/db/migrations/007_project_clone_memory.sql` | 第一步 |
| 2 | `src/mango/agent/project_service.py` | 第二步 |
| 3 | `src/mango/skills/summarize.py` | 第五步 |
| 4 | `src/mango/utils/json_extract.py` | 第五步 |
| 5 | `src/mango/skills/distill.py` | 第五步 |
| 6 | `web/src/components/ProjectForm.tsx` | 第六步 |
| 7 | `web/src/components/ProjectList.tsx` | 第六步 |
| 8 | `web/src/components/ProjectSelector.tsx` | 第六步 |
| 9 | `web/src/components/ProjectSettings.tsx` | 第六步 |
| 10 | `web/src/components/MemoryTab.tsx` | 第六步 |
| 11 | `web/src/hooks/useProjects.ts` | 第六步 |
| 12 | `tests/test_project_service.py` | 第七步 |
| 13 | `tests/test_json_extract.py` | 第七步 |
| 14 | `tests/test_memory.py` | 第七步 |

### 修改文件（20 个）

| # | 文件 | 涉及阶段 |
|---|------|---------|
| 1 | `src/mango/models.py` | 第一步 |
| 2 | `src/mango/config.py` | 第一步 |
| 3 | `src/mango/db/repos.py` | 第一步 |
| 4 | `src/mango/server/sse.py` | 第二步 |
| 5 | `src/mango/agent/runtime.py` | 第三步、第五步 |
| 6 | `src/mango/server/routes.py` | 第四步、第五步 |
| 7 | `src/mango/agent/context.py` | 第五步 |
| 8 | `src/mango/skills/base.py` | 第五步 |
| 9 | `src/mango/skills/plan.py` | 第五步 |
| 10 | `web/src/types/index.ts` | 第六步 |
| 11 | `web/src/api/client.ts` | 第六步 |
| 12 | `web/src/components/IssueForm.tsx` | 第六步 |
| 13 | `web/src/components/RetryInput.tsx` | 第六步 |
| 14 | `web/src/components/CardDetailModal.tsx` | 第六步 |
| 15 | `web/src/components/TopBar.tsx` | 第六步 |
| 16 | `web/src/hooks/useIssues.ts` | 第六步 |
| 17 | `web/src/App.tsx` | 第六步 |
| 18 | `tests/conftest.py` | 第七步 |
| 19 | `tests/test_api.py` | 第七步 |
| 20 | `tests/test_runtime.py` | 第七步 |

---

## 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Migration 007 重建 issues 表丢失数据 | 旧 Issue 无 project_id，workspace 列删除 | 用户要求不兼容遗留；生产执行前备份 DB 文件 |
| 大仓库 clone 超时 | 用户等待过久 | SSE 实时反馈状态；后续可加 clone 进度 |
| 并发 reclone + run 竞态 | 文件在执行中被删除 | 路由守卫 `clone_status == ready`；后续可加 project-level 锁 |
| SummarizeSkill LLM 输出不可控 | issue_memories 写入垃圾数据 | `validate_memory()` 校验 + 字段长度限制；失败不写入 |
| `IssueCreate.workspace → project_id` 是破坏性 API 变更 | 前端和测试同时失败 | 第一步同时改前端和所有测试，不留过渡期 |

---

## 推迟到 ROADMAP 5

| 方向 | 前提条件 |
|------|---------|
| Memory 自动归纳（Issue 完成 N 条后自动 Distill） | 手动归纳模式验证 token 消耗和质量后 |
| Memory 搜索 / RAG（语义检索相关 Memory） | Issue Memory 积累足够多、简单注入不够用时 |
| 多 Agent / 多模型后端 | Project + Memory 稳定，有明确的 Agent 特化需求 |
| Docker 沙箱隔离 | 生产环境安全问题突显 |
| 拖拽排序 | 用户对操作按钮体验不满意 |
| CI Webhook 集成（Review → Done 自动化） | Webhook 基础设施就绪 |
| Memory 编辑（用户手动修正 AI 总结） | Memory 质量问题频发时 |
| 跨 Project 知识共享 | 多 Project 运行成熟，有共性知识需求 |
| Clone 进度展示（git clone --progress 解析） | 大仓库 clone 体验不佳时 |
