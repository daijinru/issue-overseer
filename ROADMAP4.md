# Mango ROADMAP 4 — Project + Clone

> Issue 进来，PR 出去。项目隔离，自动 Clone。

---

## 里程碑 3 完成情况

Kanban Board + Spec 阶段全部完成。五列看板（Backlog / Todo / Dev / Review / Done）映射 Issue 全生命周期，Card Detail Modal 左右分栏展示元数据和实时 Session。PlanSkill 生成结构化 Spec，GenericSkill 注入 Spec 执行。状态机扩展至 8 个状态，Issue 编辑/删除按状态守卫。后端 ~900 行 Python，前端 ~1500 行 TypeScript。

**当前核心限制**：

| 限制 | 现状 | 影响 |
|------|------|------|
| 无 Project 概念 | `workspace` 是 Issue 上的路径字符串，git 配置（`default_branch`/`remote`/`pr_base`）全局共享 | 多仓库场景下 Issue 混杂，无法按项目过滤，git 配置冲突 |
| 无 Clone 管理 | 用户必须手动指定本地路径，Mango 不管仓库从哪来 | 部署到新环境需要手动 clone，脏状态无自动恢复 |

---

## 里程碑 4 目标

引入两个核心能力：

1. **Project 实体** — 最上层组织单元，DB + Web UI 动态管理。`repo_url` 是唯一入口，Mango 自动 clone。Issue 隶属 Project。
2. **Clone 管理** — 异步 clone + 脏状态检测 + 自动恢复 + SSE 通知前端。

### 设计约束

- **仍然 1:1**：1 Issue = 1 次执行，不做任务拆分
- **仍然串行**：不并发，不做多 Agent 后端
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

## 数据模型变更

### 新增表

```sql
-- ============================================================
-- Migration 007: Project + Clone
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

-- 3. 索引
CREATE INDEX idx_issues_status ON issues(status);
CREATE INDEX idx_issues_project ON issues(project_id);

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
```

---

## 实施步骤

### 第一步：DB + Models + Config + Repos

> Project 表 + Clone 字段 + Issue 迁移 + Repo 层。一次 migration，不分两步。

**新增** `src/mango/db/migrations/007_project_clone.sql`（见上文完整 SQL）

**修改** `src/mango/models.py`
- 新增 `CloneStatus`、`Project`、`ProjectCreate`、`ProjectUpdate`
- `Issue`：删除 `workspace`，新增 `project_id`
- `IssueCreate`：`workspace` → `project_id`（必填）
- `IssueRetry`：删除 `workspace`

**修改** `src/mango/config.py`
- `ProjectConfig.workspace` 默认值 `"."` → `"./workspaces"`

**修改** `src/mango/db/repos.py`
- 新增 `ProjectRepo`（create / get / list_all / update_fields / delete）
  - `delete()` 检查关联 Issue，有 Issue 则拒绝
- `_ALLOWED_ISSUE_FIELDS`：移除 `workspace`，新增 `project_id`
- `IssueRepo.create()`：INSERT SQL `workspace` → `project_id`
- `IssueRepo.retry_reset()`：删除 `workspace` 参数及相关 SQL
- `IssueRepo.list_all()`：新增 `project_id` 可选过滤参数

**涉及文件**

| 文件 | 变更类型 |
|------|---------|
| `src/mango/db/migrations/007_project_clone.sql` | **新增** |
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
DELETE /api/projects/{id}           删除（有 Issue 则 409）
POST   /api/projects/{id}/reclone   强制重新 clone
GET    /api/projects/{id}/stream    SSE clone 状态流
```

修改 Issue 端点：
- `POST /api/issues`：校验 `project_id` 对应的 Project 存在
- `POST /api/issues/{id}/run`：校验 project `clone_status == ready`，否则 409
- `POST /api/issues/{id}/plan`：同上
- `POST /api/issues/{id}/retry`：去掉 `workspace`
- `GET /api/issues`：新增 `project_id` 查询参数

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

### 第五步：前端

> Project 管理 + Clone 状态。

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

---

### 第六步：测试

> 基础测试适配在各步骤中同步完成，本步骤聚焦新增测试和端到端验证。

**修改** `tests/conftest.py`
- `mock_runtime` fixture：创建 DB Project 记录替代 `settings.project.workspace`

**修改** `tests/test_db.py`
- Migration 007 验证 + Project DB 测试

**修改** `tests/test_api.py`
- Issue 创建加 `project_id`、Project API 测试、clone 守卫测试

**修改** `tests/test_runtime.py`
- 删除 `_resolve_workspace` 测试、改用 Project、测试 sync_repo

**新增** `tests/test_project_service.py`
- clone / reclone / dirty state / sync / _is_valid_repo 测试

**端到端验证流程**

- [ ] **完整链路**：创建 Project → clone ready → 创建 Issue → Run → PR → review
- [ ] **多 Project 隔离**：两个 Project 各自的 Issue 不互相影响
- [ ] **Clone 异常恢复**：clone 失败 → 前端看到 error → reclone → 成功
- [ ] **脏状态恢复**：手动损坏 local_path → reclone → 自动清理 + 重新 clone

---

## 文件清单汇总

### 新增文件（8 个）

| # | 文件 | 所属阶段 |
|---|------|---------|
| 1 | `src/mango/db/migrations/007_project_clone.sql` | 第一步 |
| 2 | `src/mango/agent/project_service.py` | 第二步 |
| 3 | `web/src/components/ProjectForm.tsx` | 第五步 |
| 4 | `web/src/components/ProjectList.tsx` | 第五步 |
| 5 | `web/src/components/ProjectSelector.tsx` | 第五步 |
| 6 | `web/src/components/ProjectSettings.tsx` | 第五步 |
| 7 | `web/src/hooks/useProjects.ts` | 第五步 |
| 8 | `tests/test_project_service.py` | 第六步 |

### 修改文件（16 个）

| # | 文件 | 涉及阶段 |
|---|------|---------|
| 1 | `src/mango/models.py` | 第一步 |
| 2 | `src/mango/config.py` | 第一步 |
| 3 | `src/mango/db/repos.py` | 第一步 |
| 4 | `src/mango/server/sse.py` | 第二步 |
| 5 | `src/mango/agent/runtime.py` | 第三步 |
| 6 | `src/mango/server/routes.py` | 第四步 |
| 7 | `web/src/types/index.ts` | 第五步 |
| 8 | `web/src/api/client.ts` | 第五步 |
| 9 | `web/src/components/IssueForm.tsx` | 第五步 |
| 10 | `web/src/components/RetryInput.tsx` | 第五步 |
| 11 | `web/src/components/CardDetailModal.tsx` | 第五步 |
| 12 | `web/src/components/TopBar.tsx` | 第五步 |
| 13 | `web/src/hooks/useIssues.ts` | 第五步 |
| 14 | `web/src/App.tsx` | 第五步 |
| 15 | `tests/conftest.py` | 第六步 |
| 16 | `tests/test_api.py` | 第六步 |
| 17 | `tests/test_runtime.py` | 第六步 |

---

## 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Migration 007 重建 issues 表丢失数据 | 旧 Issue 无 project_id，workspace 列删除 | 用户要求不兼容遗留；生产执行前备份 DB 文件 |
| 大仓库 clone 超时 | 用户等待过久 | SSE 实时反馈状态；后续可加 clone 进度 |
| 并发 reclone + run 竞态 | 文件在执行中被删除 | 路由守卫 `clone_status == ready`；后续可加 project-level 锁 |
| `IssueCreate.workspace → project_id` 是破坏性 API 变更 | 前端和测试同时失败 | 第一步同时改前端和所有测试，不留过渡期 |

---

## 推迟到 ROADMAP 5

| 方向 | 前提条件 |
|------|---------|
| 多 Agent / 多模型后端 | Project 稳定，有明确的 Agent 特化需求 |
| Docker 沙箱隔离 | 生产环境安全问题突显 |
| 拖拽排序 | 用户对操作按钮体验不满意 |
| CI Webhook 集成（Review → Done 自动化） | Webhook 基础设施就绪 |
| 跨 Project 知识共享 | 多 Project 运行成熟，有共性知识需求 |
| Clone 进度展示（git clone --progress 解析） | 大仓库 clone 体验不佳时 |
