# Mango ROADMAP 4 — Project + Memory

> Issue 进来，PR 出去。项目隔离，经验沉淀。

---

## 里程碑 3 完成情况

Kanban Board + Spec 阶段全部完成。五列看板（Backlog / Todo / Dev / Review / Done）映射 Issue 全生命周期，Card Detail Modal 左右分栏展示元数据和实时 Session。PlanSkill 生成结构化 Spec，GenericSkill 注入 Spec 执行。状态机扩展至 8 个状态，Issue 编辑/删除按状态守卫。后端 ~900 行 Python，前端 ~1500 行 TypeScript。

**当前核心限制**：

| 限制 | 现状 | 影响 |
|------|------|------|
| 无 Project 概念 | `workspace` 是 Issue 上的路径字符串，git 配置（`default_branch`/`remote`/`pr_base`）全局共享 | 多仓库场景下 Issue 混杂，无法按项目过滤，git 配置冲突 |
| 无 Memory 系统 | 每个 Issue 执行从零开始，不了解项目约定和历史经验 | AI 重复犯同样的错误，不知道项目的编码风格、测试惯例、已踩过的坑 |
| Skill 无项目感知 | GenericSkill / PlanSkill 的 prompt 只包含 Issue + Turn 状态 | AI 无法利用跨 Issue 积累的知识 |

---

## 里程碑 4 目标

引入两个核心能力：

1. **Project 实体** — 最上层组织单元，DB + Web UI 动态管理。每个 Project 绑定一个 git 仓库，独立 git 配置。Issue 隶属 Project。
2. **Memory 系统** — 两层架构（Issue Memory + Project Memory），与 Skill 深度集成。AI 在规划和编码时携带项目级经验。

### 设计约束

- **仍然 1:1**：1 Issue = 1 次执行，不做任务拆分
- **仍然串行**：不并发，不做多 Agent 后端
- **Memory 是被动的**：Issue Memory 自动生成，Project Memory 按需归纳，不做主动学习
- **Project 是必选的**：里程碑 4 完成后，每个 Issue 必须属于一个 Project（迁移时创建默认 Project）

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

Project 成为一等实体，存 DB，通过 Web UI 动态管理：

```python
class Project(BaseModel):
    id: str
    name: str                              # "mango", "frontend-app"
    repo_path: str                         # "/Users/x/repos/mango"
    default_branch: str = "main"
    remote: str = "origin"
    pr_base: str = "main"
    description: str = ""
    created_at: str | None = None
    updated_at: str | None = None
```

Issue 新增 `project_id` FK，废弃 `workspace`：

```python
class Issue(BaseModel):
    project_id: str                        # FK → projects.id
    # workspace: str | None = None         # 废弃，由 project.repo_path 替代
```

Runtime 从 Project 读取 git 配置，不再依赖全局 `[project]`：

```python
# runtime.py — 之前
remote = self.settings.project.remote          # 全局

# runtime.py — 之后
project = await self.project_repo.get(issue.project_id)
remote = project.remote                         # per-project
```

`overseer.toml` 的 `[project]` 段保留为 **创建 Project 时的默认值**，不再直接用于执行。

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

### Project Memory — 归纳的项目级知识

**触发方式**：用户手动触发 `POST /api/projects/{id}/distill`（不做自动归纳，避免不可控的 token 消耗）。

**DistillSkill 输入**：
- 项目名 + 描述
- 所有 Issue Memory（或最近 N 条，受 token 预算约束）
- 现有 Project Memory（增量更新，不重写全部）

**DistillSkill 输出**（纯文本，Markdown 格式）：

```markdown
## 项目约定
- 测试框架: pytest-asyncio，测试文件放 tests/ 目录
- API 路由使用 FastAPI APIRouter，prefix="/api"
- 数据库变更需同步 migration SQL

## 常见陷阱
- 修改 models.py 后必须更新 repos.py 的字段白名单
- OpenCode 子进程需要 cancel_event 传播
- git commit 前必须检查 --cached --quiet

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

**注入位置**：prompt 最前面，在 Task 之前。让 AI 先了解项目背景，再看具体任务。

**token 预算**：Project Memory 注入前截断到 `context.max_project_memory_chars`（默认 3000 字符），避免挤占任务描述和 git diff 的空间。

```python
# GenericSkill._build_prompt():
sections: list[str] = []
if ctx.project_memory:                                              # 新增
    sections.append(f"## Project Context\n{ctx.project_memory}")    # 新增
sections.append(f"## Task\n**{ctx.issue.title}**\n...")
# ... 其余不变

# PlanSkill._build_plan_prompt():
sections: list[str] = []
if ctx.project_memory:                                              # 新增
    sections.append(f"## Project Context\n{ctx.project_memory}")    # 新增
sections.append(f"## Task: Generate Execution Plan\n...")
# ... 其余不变
```

---

## 数据模型变更

### 新增表

```sql
-- ============================================================
-- Migration 007: Project + Memory
-- ============================================================

-- 1. projects 表
CREATE TABLE projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  repo_path TEXT NOT NULL,
  default_branch TEXT NOT NULL DEFAULT 'main',
  remote TEXT NOT NULL DEFAULT 'origin',
  pr_base TEXT NOT NULL DEFAULT 'main',
  description TEXT NOT NULL DEFAULT '',
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);

-- 2. 默认项目（迁移现有 Issue）
INSERT INTO projects (id, name, repo_path, default_branch, remote, pr_base, description)
VALUES (
  'default',
  'default',
  '.',
  'main',
  'origin',
  'main',
  '自动迁移的默认项目'
);

-- 3. issues 新增 project_id（所有现有 Issue 归入 default 项目）
ALTER TABLE issues ADD COLUMN project_id TEXT NOT NULL DEFAULT 'default' REFERENCES projects(id);

-- 4. issue_memories 表
CREATE TABLE issue_memories (
  id TEXT PRIMARY KEY,
  issue_id TEXT NOT NULL UNIQUE REFERENCES issues(id),
  project_id TEXT NOT NULL REFERENCES projects(id),
  summary TEXT NOT NULL,                    -- 一句话总结
  root_cause TEXT,                          -- 根因（bugfix 类）
  changes TEXT,                             -- JSON: 变更文件列表
  lessons TEXT,                             -- JSON: 经验教训列表
  tags TEXT,                                -- JSON: 标签列表
  raw_json TEXT NOT NULL,                   -- 完整 JSON（备份）
  created_at TEXT DEFAULT (datetime('now'))
);

-- 5. project_memories 表（带版本）
CREATE TABLE project_memories (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  version INTEGER NOT NULL DEFAULT 1,       -- 归纳版本号
  content TEXT NOT NULL,                    -- Markdown 格式的项目知识
  source_count INTEGER NOT NULL DEFAULT 0,  -- 基于多少条 Issue Memory 归纳
  created_at TEXT DEFAULT (datetime('now'))
);

-- 6. 索引
CREATE INDEX idx_issues_project ON issues(project_id);
CREATE INDEX idx_issue_memories_project ON issue_memories(project_id);
CREATE INDEX idx_project_memories_project ON project_memories(project_id);
CREATE UNIQUE INDEX idx_project_memories_version ON project_memories(project_id, version);
```

### 模型变更

```python
# models.py 新增

class Project(BaseModel):
    id: str
    name: str
    repo_path: str
    default_branch: str = "main"
    remote: str = "origin"
    pr_base: str = "main"
    description: str = ""
    created_at: str | None = None
    updated_at: str | None = None

class ProjectCreate(BaseModel):
    name: str
    repo_path: str
    default_branch: str = "main"
    remote: str = "origin"
    pr_base: str = "main"
    description: str = ""

class ProjectUpdate(BaseModel):
    name: str | None = None
    repo_path: str | None = None
    default_branch: str | None = None
    remote: str | None = None
    pr_base: str | None = None
    description: str | None = None

class IssueMemory(BaseModel):
    id: str
    issue_id: str
    project_id: str
    summary: str
    root_cause: str | None = None
    changes: list[str] = []           # 从 JSON 解析
    lessons: list[str] = []           # 从 JSON 解析
    tags: list[str] = []              # 从 JSON 解析
    raw_json: str
    created_at: str | None = None

class ProjectMemory(BaseModel):
    id: str
    project_id: str
    version: int
    content: str                      # Markdown
    source_count: int = 0
    created_at: str | None = None

# Issue 变更
class Issue(BaseModel):
    # ... 现有字段 ...
    project_id: str = "default"       # 新增
    # workspace: str | None = None    # 废弃（保留字段兼容旧数据，不再使用）

# IssueCreate 变更
class IssueCreate(BaseModel):
    title: str
    description: str = ""
    project_id: str                   # 必填（替代 workspace）
    priority: IssuePriority = IssuePriority.medium

# TurnContext 变更
@dataclass
class TurnContext:
    # ... 现有字段 ...
    project_memory: str | None = None  # 新增：Project Memory 文本
```

---

## 新增 Skill

### SummarizeSkill

```python
# skills/summarize.py

class SummarizeSkill(BaseSkill):
    """Issue 完成后生成结构化总结，存入 issue_memories。"""

    def _build_prompt(self, issue: Issue, git_diff: str,
                      execution_history: list[dict], spec: str | None) -> str:
        return f"""## Task: Summarize Completed Issue

**Issue**: {issue.title}
**Description**: {issue.description}

## Changes Made (git diff)
```diff
{git_diff}
```

## Execution History
{self._format_history(execution_history)}

{f"## Original Plan\\n{spec}" if spec else ""}

## Instructions
Generate a structured summary of what was done and what was learned.
Do NOT modify any files.

Output MUST be valid JSON:
{{
  "summary": "一句话总结做了什么",
  "root_cause": "根因分析（如果是 bugfix）或 null",
  "changes": ["file1.py", "file2.py"],
  "lessons": ["经验1", "经验2"],
  "tags": ["bugfix", "auth"]
}}"""
```

**触发位置**：`runtime.py` 的 `_run_task()` 中，PR 创建成功、Issue 进入 `review` 之后：

```python
# runtime.py — PR 创建成功后
await self.issue_repo.update_status(issue_id, IssueStatus.review)

# 新增：异步生成 Issue Memory（不阻塞主流程）
asyncio.create_task(self._generate_issue_memory(issue_id))
```

**容错**：Memory 生成失败不影响 Issue 状态（已经是 `review`），只记录 warn 日志。

### DistillSkill

```python
# skills/distill.py

class DistillSkill(BaseSkill):
    """从多条 Issue Memory 归纳 Project Memory。"""

    def _build_prompt(self, project: Project,
                      issue_memories: list[IssueMemory],
                      existing_memory: str | None) -> str:
        memories_text = self._format_memories(issue_memories)
        return f"""## Task: Distill Project Knowledge

**Project**: {project.name}
**Description**: {project.description}

## Issue Memories ({len(issue_memories)} entries)
{memories_text}

{f"## Existing Project Memory\\n{existing_memory}" if existing_memory else ""}

## Instructions
Analyze the issue memories and distill reusable project knowledge.
Output Markdown text covering:
1. **项目约定** — 编码风格、测试框架、文件结构等
2. **常见陷阱** — 反复出现的问题和解决方案
3. **代码结构** — 关键文件和模块的位置

If there is existing project memory, update it incrementally — keep valid knowledge,
add new insights, remove outdated information.

Output ONLY Markdown text, no JSON wrapping."""
```

**触发方式**：`POST /api/projects/{id}/distill`，用户手动触发。

---

## 实施步骤

### 第一步：Project 实体（后端）

> 新增 Project 表和 CRUD API，Issue 关联 Project，Runtime 从 Project 读取 git 配置。

**DB Migration `007_project_memory.sql`**

- 新增 `projects` 表
- 创建 `default` Project
- `issues` 新增 `project_id` 字段（DEFAULT 'default'）
- 新增 `issue_memories`、`project_memories` 表
- 索引

**模型变更 `models.py`**

- 新增 `Project`、`ProjectCreate`、`ProjectUpdate`、`IssueMemory`、`ProjectMemory`
- `Issue` 新增 `project_id`
- `IssueCreate` 用 `project_id` 替代 `workspace`
- `TurnContext` 新增 `project_memory`

**仓库变更 `repos.py`**

- 新增 `ProjectRepo`（CRUD + `list_all`）
- 新增 `IssueMemoryRepo`（create + `list_by_project` + `get_by_issue`）
- 新增 `ProjectMemoryRepo`（create + `get_latest_by_project`）
- `IssueRepo.list_all()` 新增 `project_id` 筛选参数
- `IssueRepo.create()` 写入 `project_id`
- `_ALLOWED_ISSUE_FIELDS` 新增 `project_id`

**Runtime 变更 `runtime.py`**

- `__init__` 新增 `ProjectRepo` 实例
- `_resolve_workspace()` 从 `project.repo_path` 取值，不再从 `issue.workspace` 或全局配置
- `_git_push()` / `_create_pr()` / `_get_git_diff()` 从 Project 读取 `remote` / `pr_base` / `default_branch`
- 方法签名变更：需要传入 `project` 对象（或在 `_run_task` 开头加载一次，贯穿整个流程）

**路由变更 `routes.py`**

```
POST   /api/projects                创建 Project
GET    /api/projects                列出 Project
GET    /api/projects/{id}           获取 Project 详情
PATCH  /api/projects/{id}           编辑 Project
DELETE /api/projects/{id}           删除 Project（仅无 Issue 时可删）
GET    /api/issues?project_id=xxx   按 Project 过滤 Issue
```

**Config 变更 `config.py`**

- `ProjectConfig` 字段保留，作为 `ProjectCreate` 的默认值来源
- 新增 `ContextConfig.max_project_memory_chars = 3000`

**涉及文件**

| 文件 | 变更类型 |
|------|---------|
| `src/mango/db/migrations/007_project_memory.sql` | **新增** |
| `src/mango/models.py` | 修改 |
| `src/mango/db/repos.py` | 修改 |
| `src/mango/agent/runtime.py` | 修改 |
| `src/mango/server/routes.py` | 修改 |
| `src/mango/config.py` | 修改 |

**验收标准**

- [ ] Project CRUD API 正常工作
- [ ] Migration 007 在现有 DB 上干净执行，现有 Issue 归入 `default` Project
- [ ] 创建 Issue 时必须指定 `project_id`
- [ ] `GET /api/issues?project_id=xxx` 按 Project 过滤
- [ ] Runtime 从 Project 读取 git 配置（remote / pr_base / default_branch）
- [ ] 删除 Project 时校验无关联 Issue
- [ ] 现有测试适配通过

---

### 第二步：Issue Memory（SummarizeSkill）

> Issue 进入 review 后，自动生成结构化总结。

**新增 `skills/summarize.py`**

- `SummarizeSkill` 实现（参见上文）
- 复用 `extract_spec_json()` 的 JSON 提取逻辑（从 plan.py 提取为公共函数 `utils/json_extract.py`）
- 新增 `validate_memory()` 校验 + 规范化字段

**Runtime 变更 `runtime.py`**

- `_run_task()` 中 PR 创建成功后，`asyncio.create_task(self._generate_issue_memory(...))`
- `_generate_issue_memory()` 方法：
  1. 调用 `SummarizeSkill`
  2. 提取 JSON
  3. 写入 `issue_memories` 表
  4. 失败只记 warn 日志，不影响 Issue 状态

**涉及文件**

| 文件 | 变更类型 |
|------|---------|
| `src/mango/skills/summarize.py` | **新增** |
| `src/mango/utils/json_extract.py` | **新增**（从 plan.py 提取） |
| `src/mango/skills/plan.py` | 修改（引用提取后的函数） |
| `src/mango/agent/runtime.py` | 修改 |

**验收标准**

- [ ] Issue 进入 `review` 后，`issue_memories` 表自动写入总结记录
- [ ] 总结 JSON 包含 summary / changes / lessons / tags 字段
- [ ] Memory 生成失败不影响 Issue 状态（已 `review`）
- [ ] `extract_spec_json()` 提取为公共函数后，PlanSkill 行为不变

---

### 第三步：Project Memory（DistillSkill + 注入 Skill）

> 用户手动触发归纳，Memory 注入 GenericSkill + PlanSkill。

**新增 `skills/distill.py`**

- `DistillSkill` 实现（参见上文）
- 输出纯 Markdown 文本（不需要 JSON 提取）

**Context 变更 `context.py`**

- `build_turn_context()` 新增 `project_memory` 参数
- 截断逻辑：`_truncate_by_chars(project_memory, ctx_cfg.max_project_memory_chars)`

**Skill 变更**

- `GenericSkill._build_prompt()`：在 Task 段之前注入 `## Project Context`
- `PlanSkill._build_plan_prompt()`：同上

**Runtime 变更 `runtime.py`**

- `_run_turn()` 中构建 TurnContext 时，从 DB 读取最新 Project Memory 注入
- `start_distill()` 方法：加载 Issue Memories → 调用 DistillSkill → 写入 `project_memories`

**路由变更 `routes.py`**

```
POST   /api/projects/{id}/distill          触发归纳 Project Memory
GET    /api/projects/{id}/memory           查看最新 Project Memory
GET    /api/projects/{id}/memories         查看 Project Memory 历史版本
GET    /api/projects/{id}/issue-memories   查看 Project 下所有 Issue Memory
GET    /api/issues/{id}/memory             查看单条 Issue Memory
```

**涉及文件**

| 文件 | 变更类型 |
|------|---------|
| `src/mango/skills/distill.py` | **新增** |
| `src/mango/agent/context.py` | 修改 |
| `src/mango/skills/base.py` (GenericSkill) | 修改 |
| `src/mango/skills/plan.py` (PlanSkill) | 修改 |
| `src/mango/agent/runtime.py` | 修改 |
| `src/mango/server/routes.py` | 修改 |

**验收标准**

- [ ] `POST /api/projects/{id}/distill` 从 Issue Memories 归纳 Project Memory
- [ ] Project Memory 写入带版本号，`GET /memory` 返回最新版本
- [ ] GenericSkill prompt 在 Task 之前包含 `## Project Context` 段
- [ ] PlanSkill prompt 在 Task 之前包含 `## Project Context` 段
- [ ] Project Memory 超过 3000 字符时自动截断
- [ ] 无 Project Memory 时 Skill prompt 不包含空段落

---

### 第四步：前端 — Project 切换 + Memory 展示

> TopBar 增加 Project 选择器，Kanban 按 Project 过滤，Card Detail 展示 Memory。

**TopBar 改造**

```
┌─────────────────────────────────────────────────────────────────┐
│  🥭 Mango    [📂 mango ▼]  [+ 新建 Issue]  Running: 0  Queued: 0 │
│              └── Project 选择器（Ant Design Select）              │
│                  · mango                                         │
│                  · frontend-app                                  │
│                  · ──────────                                    │
│                  · [+ 新建 Project]                               │
└─────────────────────────────────────────────────────────────────┘
```

**Project 管理弹窗**

新增 Project 时填写：name、repo_path（必填），default_branch / remote / pr_base（选填，有默认值）。

**Kanban 过滤**

`useIssues.ts` 的 `GET /api/issues` 加 `project_id` 查询参数，Kanban 只显示当前 Project 的 Issue。

**Card Detail Modal — Memory Tab**

右侧 Tabs 新增 "Memory" tab：
- 展示 Issue Memory（如有）：summary、lessons、tags
- 展示 Project Memory 链接（跳转 Project 设置）

**Project 设置页**

新增简单页面（或 Modal）：
- Project 基本信息编辑
- Project Memory 展示（Markdown 渲染）
- "归纳知识" 按钮（触发 `POST /distill`）
- Issue Memory 列表（该项目下所有 Issue 的总结）

**涉及文件**

| 文件 | 变更类型 |
|------|---------|
| `web/src/components/TopBar.tsx` | 修改 |
| `web/src/components/ProjectSelector.tsx` | **新增** |
| `web/src/components/ProjectModal.tsx` | **新增** |
| `web/src/components/ProjectSettings.tsx` | **新增** |
| `web/src/components/MemoryTab.tsx` | **新增** |
| `web/src/components/CardDetailModal.tsx` | 修改 |
| `web/src/components/IssueForm.tsx` | 修改（project_id 替代 workspace） |
| `web/src/hooks/useIssues.ts` | 修改（加 project_id 过滤） |
| `web/src/hooks/useProjects.ts` | **新增** |
| `web/src/api/client.ts` | 修改（Project API + Memory API） |
| `web/src/types/index.ts` | 修改（新增 Project / Memory 类型） |
| `web/src/App.tsx` | 修改（Project 状态管理） |

**验收标准**

- [ ] TopBar Project 选择器正确切换，Kanban 按 Project 过滤
- [ ] 新建 Issue 时必须选 Project（下拉选择当前 Project）
- [ ] Card Detail 展示 Issue Memory
- [ ] Project 设置页展示 Project Memory，"归纳知识"按钮可用
- [ ] 创建/编辑/删除 Project 正常工作

---

### 第五步：测试 + 集成验证

**新增测试**

| 文件 | 覆盖内容 |
|------|---------|
| `tests/test_project.py` | **新增**：Project CRUD、Issue 关联、删除守卫 |
| `tests/test_memory.py` | **新增**：SummarizeSkill / DistillSkill、JSON 提取、Memory 注入 prompt |
| `tests/test_json_extract.py` | **新增**：公共 JSON 提取函数的边界用例 |

**修改测试**

| 文件 | 改动 |
|------|------|
| `tests/test_api.py` | 所有 Issue 创建加 project_id；新增 Project API 测试 |
| `tests/test_runtime.py` | Runtime 从 Project 读 git 配置；Issue Memory 自动生成 |
| `tests/test_db.py` | Migration 007 执行验证 |

**端到端验证流程**

- [ ] **完整 Memory 链路**：创建 Project → 创建 Issue → Run → PR → review → Issue Memory 自动生成 → 手动 Distill → Project Memory 生成 → 新 Issue Run → prompt 包含 Project Context
- [ ] **多 Project 隔离**：两个 Project 各自的 Issue 不互相影响，Memory 隔离
- [ ] **向后兼容**：现有 Issue 归入 default Project，核心链路不受影响
- [ ] **Memory 容错**：SummarizeSkill 失败 → Issue 仍为 review，warn 日志
- [ ] **token 预算**：超长 Project Memory 被截断，不影响 Skill 执行

---

## 文件清单汇总

### 新增文件（10 个）

| # | 文件 | 所属阶段 |
|---|------|---------|
| 1 | `src/mango/db/migrations/007_project_memory.sql` | 第一步 |
| 2 | `src/mango/skills/summarize.py` | 第二步 |
| 3 | `src/mango/utils/json_extract.py` | 第二步 |
| 4 | `src/mango/skills/distill.py` | 第三步 |
| 5 | `web/src/components/ProjectSelector.tsx` | 第四步 |
| 6 | `web/src/components/ProjectModal.tsx` | 第四步 |
| 7 | `web/src/components/ProjectSettings.tsx` | 第四步 |
| 8 | `web/src/components/MemoryTab.tsx` | 第四步 |
| 9 | `web/src/hooks/useProjects.ts` | 第四步 |
| 10 | `tests/test_project.py` | 第五步 |
| 11 | `tests/test_memory.py` | 第五步 |
| 12 | `tests/test_json_extract.py` | 第五步 |

### 修改文件（16 个）

| # | 文件 | 涉及阶段 |
|---|------|---------|
| 1 | `src/mango/models.py` | 第一步 |
| 2 | `src/mango/db/repos.py` | 第一步、第三步 |
| 3 | `src/mango/agent/runtime.py` | 第一步、第二步、第三步 |
| 4 | `src/mango/server/routes.py` | 第一步、第三步 |
| 5 | `src/mango/config.py` | 第一步 |
| 6 | `src/mango/agent/context.py` | 第三步 |
| 7 | `src/mango/skills/base.py` | 第三步 |
| 8 | `src/mango/skills/plan.py` | 第二步、第三步 |
| 9 | `web/src/components/TopBar.tsx` | 第四步 |
| 10 | `web/src/components/CardDetailModal.tsx` | 第四步 |
| 11 | `web/src/components/IssueForm.tsx` | 第四步 |
| 12 | `web/src/hooks/useIssues.ts` | 第四步 |
| 13 | `web/src/api/client.ts` | 第四步 |
| 14 | `web/src/types/index.ts` | 第四步 |
| 15 | `web/src/App.tsx` | 第四步 |
| 16 | `tests/test_api.py` | 第五步 |
| 17 | `tests/test_runtime.py` | 第五步 |
| 18 | `tests/test_db.py` | 第五步 |

---

## 工期预估

| 阶段 | 范围 | 工期 |
|------|------|------|
| 第一步 | Project 实体 + DB + API + Runtime 适配 | ~3 天 |
| 第二步 | SummarizeSkill + Issue Memory | ~2 天 |
| 第三步 | DistillSkill + Project Memory + Skill 注入 | ~2.5 天 |
| 第四步 | 前端 Project 切换 + Memory 展示 | ~3 天 |
| 第五步 | 测试 + 集成验证 | ~2 天 |
| **总计** | | **~12.5 天** |

---

## 关键设计决策

| # | 决策 | 理由 |
|---|------|------|
| 1 | Project 存 DB，不存 TOML | TOML 是静态配置，Project 需要动态增删。`[project]` 段保留为创建 Project 时的默认值 |
| 2 | Issue Memory 自动生成，Project Memory 手动归纳 | 自动生成低风险（失败不影响流程）；自动归纳可能消耗大量 token，时机不好控制，由用户决定 |
| 3 | Memory 注入 prompt 最前面（Task 之前） | 让 AI 先了解项目背景再看任务，类似人类先看 README 再写代码 |
| 4 | Project Memory 带版本，不覆盖更新 | 保留历史版本供回溯；最新版本通过 `MAX(version)` 查询 |
| 5 | `extract_spec_json()` 提取为公共函数 | SummarizeSkill 也需要从 LLM 输出提取 JSON，消除重复 |
| 6 | Memory 生成失败不阻塞主流程 | Memory 是增值功能，不应影响核心链路（Issue → PR）的可靠性 |
| 7 | `workspace` 字段保留但废弃 | 避免破坏性迁移，旧数据仍可读，新代码不再写入 |

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
