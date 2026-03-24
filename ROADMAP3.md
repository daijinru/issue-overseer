# Mango ROADMAP 3 — Kanban Board + Spec 阶段

> Issue 进来，PR 出去。看板驱动，流程可见。

---

## 里程碑 2 完成情况

Phase A–B 全部完成。P0/P1 问题已修。核心链路可靠运行：Issue CRUD → Agent Runtime 三层循环 → OpenCode 执行 → git commit → push → PR 创建 → SSE 实时步骤流。后端 ~800 行 Python，前端 ~1200 行 TypeScript，15 个测试文件。

**未完成项（carry over）**：
- Spec 阶段（planning/planned 状态、PlanSkill、/plan API、Spec 卡片）
- Issue 编辑/删除
- workspace 路径白名单

---

## 里程碑 3 目标

将 Mango 从列表视图升级为 **五列 Kanban Board**，灵感来自 Routa 平台。五列看板映射 Issue 完整生命周期，每列对应一个 Agent 角色：

```
┌───────────────────────────────────────────────────────────────────────────────┐
│  🥭 Mango · AI Issue Board              [+ 新建 Issue]  Running: 0  Queued: 0 │
├─────────────┬─────────────┬─────────────┬─────────────┬─────────────────────┤
│  📋 BACKLOG  │  📝 TODO     │  🔨 DEV      │  🔍 REVIEW   │  ✅ DONE             │
│  Refiner    │  Orchestr.  │  Crafter    │  Guard      │  Reporter           │
├─────────────┼─────────────┼─────────────┼─────────────┼─────────────────────┤
│ ┌─────────┐ │ ┌─────────┐ │ ┌─────────┐ │ ┌─────────┐ │ ┌─────────────────┐ │
│ │ Issue #1│ │ │ Issue #3│ │ │ Issue #5│ │ │ Issue #7│ │ │ Issue #9  ✓     │ │
│ │ HIGH    │ │ │ MED     │ │ │ HIGH 🔄 │ │ │ MED  🔗│ │ │ LOW   PR merged │ │
│ └─────────┘ │ └─────────┘ │ └─────────┘ │ └─────────┘ │ └─────────────────┘ │
│ ┌─────────┐ │             │             │             │                     │
│ │ Issue #2│ │             │             │             │                     │
│ │ LOW     │ │             │             │             │                     │
│ └─────────┘ │             │             │             │                     │
└─────────────┴─────────────┴─────────────┴─────────────┴─────────────────────┘
                    卡片点击 → 弹出 Card Detail 大弹窗（Modal）
```

### Card Detail Modal（参考 Routa）

卡片点击后弹出全屏级大弹窗，左右分栏布局：

```
┌─────────────────────────────────────────────────────────────────────┐
│  Card Detail                                                  Close │
│  Task: f08e36b7-191f-...                              Open full page│
├────────────────────────┬────────────────────────────────────────────┤
│                        │                                            │
│  TITLE                 │  ● Session a3706517-454...    Chat | Trace │
│  ┌──────────────────┐  │                                            │
│  │ Fix login bug    │  │  BA ▸ bash       npx tsc --noEmit ...   > │
│  └──────────────────┘  │  BA ▸ bash       npx tsc --noEmit ...   > │
│                        │  CH ● Check TypeScript compilation      > │
│  OBJECTIVE             │  > THINKING                                │
│  ┌──────────────────┐  │  │ Let me find the correct tsconfig...    │
│  │ 修复登录页面的    │  │  BA ▸ bash       npx tsc --noEmit ...   > │
│  │ 测试失败问题...   │  │  CH ● Check TypeScript compilation      > │
│  └──────────────────┘  │  > THINKING                                │
│                        │  │ No output means compiled successfully.  │
│  PRIORITY    COLUMN    │                                            │
│  [Medium ▼]  [dev   ]  │  TypeScript compilation passes.            │
│                        │                                            │
│  ┌──────────────────┐  │  Summary: The task is already complete...  │
│  │    ▶ Rerun       │  │                                            │
│  └──────────────────┘  ├────────────────────────────────────────────┤
│                        │  ┌──────────────────────────────────────┐  │
│  SPEC (if planned)     │  │ Connect first...                     │  │
│  ┌──────────────────┐  │  └──────────────────────────────────────┘  │
│  │ Plan: ...        │  │  ○ repo  ○ OpenCode  ○ Default model       │
│  │ Criteria: ...    │  │            Build | Plan                    │
│  │ Files: ...       │  │                                            │
│  └──────────────────┘  │                                            │
│                        │                                            │
└────────────────────────┴────────────────────────────────────────────┘
  左侧: 元数据 + 操作          右侧: 实时 Session（步骤流 + 日志）
  (~35% 宽度)                  (~65% 宽度)
```

**左侧面板**（元数据 + 操作）：
- Title（可编辑，open/planned 状态下）
- Objective / Description（可编辑）
- Priority 下拉 + Column 标签（只读，由状态决定）
- 操作按钮：Rerun / Cancel / Complete 等（按状态显示）
- Spec 卡片（当 Issue 有 spec 时展示：计划、验收标准、文件列表）
- 分支名、PR 链接、创建/更新时间
- Failure reason（waiting_human 时显示）
- Retry 输入框（waiting_human 时显示）

**右侧面板**（实时 Session）：
- 执行步骤流（复用现有 StepList 组件）：bash 命令、文件读写、THINKING 展示
- 执行历史（复用 ExecutionTimeline）
- 日志（复用 LogViewer）
- 三者通过 Tabs 切换，默认显示实时步骤（running 时）或执行历史（非 running 时）

**核心约束**：
- 仍使用 OpenCode 作为唯一执行后端（不做多 agent/多模型）
- Kanban 列名带角色标签（Refiner, Orchestrator, Crafter, Guard, Reporter）是 UI 装饰，不是独立的 agent 后端
- Spec 阶段作为 Backlog → Todo 过渡的功能基础
- ROADMAP2 遗留的 Issue 编辑/删除一并完成

---

## 状态机设计

### 新状态机

```
  Backlog(open)  Todo(planned)   Dev(running)   Review(review)   Done(done)
      │              │               │               │               │
   ┌──────┐      ┌────────┐     ┌─────────┐     ┌────────┐      ┌──────┐
   │ open │─opt─▶│planning│auto▶│ planned │─run▶│running │─PR──▶│review│──▶│done│
   └──────┘      └────────┘     └─────────┘     └────────┘      └──────┘   └────┘
      │                             │  ▲           │
      │  skip spec                  │  │           ▼
      └─────────────────────────────┘  └──── waiting_human ──retry──▶ running

  cancelled ←── 任何 running 状态（running, planning）
```

### 状态枚举变更

**当前**（6 个）：
```python
open, running, done, failed, waiting_human, cancelled
```

**新增**（8 个）：
```python
open, planning, planned, running, review, done, waiting_human, cancelled
```

| 变更 | 说明 |
|------|------|
| 新增 `planning` | AI 正在生成 Spec（Backlog 列，活跃状态） |
| 新增 `planned` | Spec 已生成待确认（Todo 列） |
| 新增 `review` | PR 已创建，等待 code review（Review 列） |
| 删除 `failed` | 合并入 `waiting_human`——所有失败都需人类介入 |

### Kanban 列映射

| Kanban 列 | 状态 | Agent 角色 | 说明 |
|-----------|------|-----------|------|
| **Backlog** | `open` | Refiner | 新 Issue，可选生成 Spec |
| **Todo** | `planning`, `planned` | Orchestrator | Spec 生成中或已就绪 |
| **Dev** | `running` | Crafter | AI 通过 OpenCode 编码 |
| **Review** | `review` | Guard | PR 已创建，等待审查 |
| **Done** | `done` | Reporter | 已完成 |
| *（叠加态）* | `waiting_human` | — | 卡片留在失败时所在列，叠加 ⚠ 徽章 |
| *（叠加态）* | `cancelled` | — | 卡片留在取消时所在列，叠加 ⊘ 徽章 |

### 状态转换规则

```
open          → planning        POST /plan（可选）
open          → running         POST /run（跳过 Spec）
planning      → planned         自动（Spec 生成成功）
planning      → waiting_human   自动（Spec 生成失败）
planned       → running         POST /run（用户确认 Spec）
planned       → open            POST /reject-spec（退回 Backlog）
running       → review          自动（PR 创建成功）
running       → waiting_human   自动（执行失败）
running       → cancelled       POST /cancel
review        → done            POST /complete（用户标记完成）
waiting_human → running         POST /retry
waiting_human → open            POST /reset（退回 Backlog）
cancelled     → open/running    POST /run（重新开始）
```

### `waiting_human` 列归属推断

`waiting_human` 是错误叠加态，不独占列。卡片留在失败前所在的列，通过已有字段推断：

```typescript
function getColumnForIssue(issue: Issue): string {
  if (issue.status === 'waiting_human' || issue.status === 'cancelled') {
    if (issue.pr_url) return 'review';       // 有 PR → Review 列失败
    if (issue.branch_name) return 'dev';     // 有分支 → Dev 列失败
    if (issue.spec) return 'todo';           // 有 Spec → Todo 列失败
    return 'backlog';                        // 否则 → Backlog
  }
  // 正常状态直接映射
  return statusToColumn[issue.status];
}
```

### 向后兼容

- DB migration：`UPDATE issues SET status = 'waiting_human' WHERE status = 'failed'`
- 代码：所有 `IssueStatus.failed` 引用 → `IssueStatus.waiting_human`
- 前端：移除 `failed` 筛选标签，`waiting_human` 吸收其语义
- `failure_reason` 字段保留，提供失败上下文

---

## 第一步：状态机 + DB 基础（后端）

> 扩展状态枚举和 DB schema，新增 API。前端暂不动，现有 API 保持兼容。

### DB Migration: `006_kanban_statuses.sql`

> **重要**：`001_init.sql` 中 `issues` 表有 `CHECK(status IN ('open','running','done','failed','waiting_human','cancelled'))` 约束。SQLite 不支持 `ALTER TABLE ... DROP CONSTRAINT`，必须通过**重建表**移除旧 CHECK，否则写入 `planning`/`planned`/`review` 会被 SQLite 直接拒绝。

```sql
-- ============================================================
-- Migration 006: Kanban 状态扩展
-- 核心问题：001_init.sql 的 CHECK 约束限制了 status 可选值，
-- SQLite 不支持修改 CHECK，必须重建表。
-- ============================================================

-- 1. 重建 issues 表（移除旧 CHECK 约束，状态校验改由应用层枚举负责）
CREATE TABLE issues_new (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'open',
  branch_name TEXT,
  human_instruction TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now')),
  workspace TEXT,
  pr_url TEXT,
  failure_reason TEXT,
  priority TEXT DEFAULT 'medium',
  spec TEXT
);

-- 2. 迁移数据，同时将 failed → waiting_human
INSERT INTO issues_new (id, title, description, status, branch_name, human_instruction,
                        created_at, updated_at, workspace, pr_url, failure_reason)
SELECT id, title, description,
       CASE WHEN status = 'failed' THEN 'waiting_human' ELSE status END,
       branch_name, human_instruction,
       created_at, updated_at, workspace, pr_url, failure_reason
FROM issues;

-- 3. 替换旧表
DROP TABLE issues;
ALTER TABLE issues_new RENAME TO issues;

-- 4. 重建索引
CREATE INDEX idx_issues_status ON issues(status);
```

> **为什么移除 CHECK 而非替换为新 CHECK**：状态枚举会随版本演进，将校验责任移到应用层 Python `IssueStatus` 枚举，避免每次加状态都要重建表。所有状态更新走 `IssueRepo.update_status()`，不直接写 SQL。

### 模型变更: `models.py`

```python
class IssueStatus(str, Enum):
    open = "open"
    planning = "planning"       # 新增
    planned = "planned"         # 新增
    running = "running"
    review = "review"           # 新增
    done = "done"
    waiting_human = "waiting_human"
    cancelled = "cancelled"
    # 删除: failed

class IssuePriority(str, Enum):  # 新增
    high = "high"
    medium = "medium"
    low = "low"

class Issue(BaseModel):
    # ... 现有字段 ...
    priority: IssuePriority = IssuePriority.medium   # 新增
    spec: str | None = None                           # 新增（JSON 字符串）
```

### 仓库变更: `repos.py`

- 字段白名单新增 `priority`, `spec`
- `IssueRepo.create()` 包含 `priority`
- `IssueRepo.list_all()` 新增可选 `priority` 筛选

### Runtime 变更: `runtime.py`

- PR 创建成功后：`done` → `review`
- 清除所有 `IssueStatus.failed` 引用 → `waiting_human`

### 路由变更: `routes.py`

- `POST /run`：允许状态新增 `planned`
- 新增 `POST /api/issues/{id}/complete`：`review` → `done`
- 新增 `PATCH /api/issues/{id}`：编辑 title/description/priority（仅 `open`/`planned`）
- 新增 `DELETE /api/issues/{id}`：删除（仅 `open`/`done`/`waiting_human`/`cancelled`）

### 涉及文件

| 文件 | 变更类型 |
|------|---------|
| `src/mango/db/migrations/006_kanban_statuses.sql` | **新增** |
| `src/mango/models.py` | 修改 |
| `src/mango/db/repos.py` | 修改 |
| `src/mango/agent/runtime.py` | 修改 |
| `src/mango/server/routes.py` | 修改 |

### 验收标准

- [x] 现有测试通过（`failed` → `waiting_human` 适配后）
- [x] Migration 006 在已有 DB 上干净执行
- [x] `GET /api/issues` 返回新状态值
- [x] `POST /api/issues/{id}/complete` 正确转换 `review` → `done`
- [x] Issue 创建含 priority 字段
- [x] 编辑/删除端点按状态守卫正常工作

---

## 第二步：PlanSkill + Spec 流程（后端）

> 实现 Backlog → Todo 的 Spec 生成/审阅/拒绝流程。

### 新增 Skill: `src/mango/skills/plan.py`

```python
class PlanSkill(BaseSkill):
    """分析代码库，生成结构化执行计划（Spec），不修改代码。"""

    def _build_plan_prompt(self, ctx: TurnContext) -> str:
        return f"""## Task: Generate Execution Plan

**Issue**: {ctx.issue.title}
**Description**: {ctx.issue.description}

## Instructions
分析代码库并生成结构化执行计划。不要修改任何文件。

输出必须为 JSON：
{{
  "plan": "方案描述...",
  "acceptance_criteria": ["标准1", "标准2"],
  "files_to_modify": ["path/to/file.py"],
  "estimated_complexity": "low | medium | high"
}}
"""
```

### JSON 提取鲁棒处理

LLM 输出格式不确定，常见问题：markdown 代码块包裹、多余解释文本、字段名大小写不一致。需要鲁棒的 JSON 提取策略：

```python
import re
import json

def extract_spec_json(raw_output: str) -> dict | None:
    """从 LLM 输出中鲁棒提取 Spec JSON。

    处理策略（按优先级）：
    1. 尝试直接 json.loads（理想情况）
    2. 提取 ```json ... ``` 代码块内容
    3. 正则匹配第一个 { ... } 块（贪婪，处理嵌套）
    4. 全部失败 → 返回 None
    """
    # 策略 1：直接解析
    try:
        return json.loads(raw_output.strip())
    except json.JSONDecodeError:
        pass

    # 策略 2：提取 markdown 代码块
    code_block = re.search(r'```(?:json)?\s*\n(.*?)\n```', raw_output, re.DOTALL)
    if code_block:
        try:
            return json.loads(code_block.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 策略 3：匹配最外层 { ... }（处理嵌套大括号）
    brace_match = re.search(r'\{', raw_output)
    if brace_match:
        start = brace_match.start()
        depth = 0
        for i in range(start, len(raw_output)):
            if raw_output[i] == '{': depth += 1
            elif raw_output[i] == '}': depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw_output[start:i+1])
                except json.JSONDecodeError:
                    break

    return None


def validate_spec(data: dict) -> dict:
    """校验并规范化 Spec 字段，宽松接受。"""
    return {
        "plan": data.get("plan", data.get("Plan", "")),
        "acceptance_criteria": data.get("acceptance_criteria",
                                        data.get("acceptanceCriteria", [])),
        "files_to_modify": data.get("files_to_modify",
                                    data.get("filesToModify", [])),
        "estimated_complexity": data.get("estimated_complexity",
                                         data.get("complexity", "medium")),
    }
```

### Runtime: Plan 流程

新增 `start_plan()` 方法：

```python
async def start_plan(self, issue_id: str) -> None:
    """生成 Spec（open → planning → planned）"""
    # 1. 校验状态必须是 open
    # 2. 状态转为 planning
    # 3. 单轮调用 PlanSkill（不创建 git 分支）
    # 4. extract_spec_json() 提取 JSON
    # 5. validate_spec() 规范化字段
    # 6. 成功 → planned；JSON 提取失败 → 重试 1 次（重新措辞 prompt 强调 JSON-only 输出）
    # 7. 重试仍失败 → waiting_human（failure_reason 记录原始输出供人类排查）
```

> **重试策略**：第一次失败后，用更严格的 prompt 重试 1 次（追加 "IMPORTANT: Output ONLY valid JSON, no markdown, no explanation."）。超过 1 次重试 → waiting_human，避免无限循环浪费 token。

### GenericSkill 改造

执行有 Spec 的 Issue 时，注入 Spec 到 prompt：

```python
# GenericSkill._build_prompt():
if ctx.spec:
    sections.append(f"## Execution Plan (Spec)\n{ctx.spec}")
```

### 新增 API 端点

```
POST /api/issues/{id}/plan          触发 Spec 生成（open → planning）
PUT  /api/issues/{id}/spec          用户编辑 Spec（planned 状态下）
POST /api/issues/{id}/reject-spec   拒绝 Spec（planned → open）
```

### 涉及文件

| 文件 | 变更类型 |
|------|---------|
| `src/mango/skills/plan.py` | **新增**（含 `extract_spec_json` + `validate_spec`） |
| `src/mango/agent/runtime.py` | 修改 |
| `src/mango/agent/context.py` | 修改 |
| `src/mango/server/routes.py` | 修改 |

### 验收标准

- [x] `POST /plan` 触发 Spec 生成，状态 `open` → `planning` → `planned`
- [x] Issue 的 `spec` 字段包含有效 JSON（plan + acceptance_criteria + files）
- [x] `extract_spec_json()` 能处理：裸 JSON、markdown 代码块包裹、前后有解释文本 三种情况
- [x] JSON 提取失败时自动重试 1 次（stricter prompt），仍失败 → `waiting_human`
- [x] `validate_spec()` 宽松接受字段名大小写差异（snake_case / camelCase）
- [x] `PUT /spec` 允许用户编辑 Spec
- [x] `POST /reject-spec` 将 Issue 退回 `open`
- [x] `POST /run` 在 `planned` Issue 上执行时，prompt 包含 Spec 内容
- [x] `POST /run` 在 `open` Issue 上仍正常工作（跳过 Spec）
- [x] SSE 发送 `plan_start`、`plan_end` 事件

---

## 第三步：Kanban Board UI（前端）

> 拆分为两个子步骤。3a 搭看板骨架 + 卡片（直接替换旧列表），3b 加 Card Detail Modal。

### 布局架构

看板主体 + Card Detail Modal 两层：

```
┌─────────────────────────────────────────────────────────┐
│  🥭 Mango    [+ 新建]  Running: 0  Queued: 0            │  ← TopBar
├───────────┬──────────┬──────────┬──────────┬────────────┤
│  BACKLOG  │   TODO   │   DEV    │  REVIEW  │    DONE    │
│  Refiner  │ Orchestr │ Crafter  │  Guard   │  Reporter  │  ← KanbanBoard
│ ┌───────┐ │┌───────┐ │┌───────┐ │┌───────┐ │┌─────────┐ │     5 × KanbanColumn
│ │ card  │ ││ card  │ ││ card🔄│ ││ card🔗│ ││ card ✓  │ │       n × IssueCard
│ └───────┘ │└───────┘ │└───────┘ │└───────┘ │└─────────┘ │
└───────────┴──────────┴──────────┴──────────┴────────────┘

卡片点击 → 弹出 CardDetailModal:

┌─────────────────────────────────────────────────────────┐
│  Card Detail                                      Close │
├──────────────────────┬──────────────────────────────────┤
│  左侧 (~35%)         │  右侧 (~65%)                     │
│  Title (可编辑)      │  实时 Session 步骤流              │
│  Objective           │  bash / read / edit / THINKING   │
│  Priority / Column   │  执行历史 / 日志 (Tabs)          │
│  [Rerun] 按钮        │                                  │
│  Spec 卡片           │  Summary                         │
│  分支 / PR 链接      │                                  │
└──────────────────────┴──────────────────────────────────┘
```

**设计决策**：
- **客户端分组**：复用 `GET /api/issues` 返回全部，前端按 status 分桶到 5 列，不加新端点
- **Modal 替代 Drawer**：卡片点击弹出全屏级 Modal（Ant Design `<Modal>` width="90vw"），左右分栏，参考 Routa Card Detail 设计
- **左侧**：元数据 + 操作按钮 + Spec 卡片（~35% 宽度）
- **右侧**：实时 Session 步骤流 + 执行历史 + 日志，通过 Tabs 切换（~65% 宽度）
- **优先级排序**：列内按 high → medium → low → 更新时间排序

### Kanban 列定义常量: `kanban.ts`

```typescript
export const KANBAN_COLUMNS = [
  { key: 'backlog',  title: 'Backlog',  agentRole: 'Refiner',      statuses: ['open'],                color: '#1677ff' },
  { key: 'todo',     title: 'Todo',     agentRole: 'Orchestrator', statuses: ['planning', 'planned'], color: '#722ed1' },
  { key: 'dev',      title: 'Dev',      agentRole: 'Crafter',      statuses: ['running'],             color: '#fa8c16' },
  { key: 'review',   title: 'Review',   agentRole: 'Guard',        statuses: ['review'],              color: '#13c2c2' },
  { key: 'done',     title: 'Done',     agentRole: 'Reporter',     statuses: ['done'],                color: '#52c41a' },
];
```

---

### 第 3a 步：Kanban 骨架 + 卡片

> 搭建五列看板骨架和卡片组件，直接替换旧 `<Sider>` 列表布局。卡片点击暂复用现有 `IssueDetail` 组件，3b 步再替换为 Modal。

#### 新增文件

| 文件 | 说明 |
|------|------|
| `web/src/components/KanbanBoard.tsx` | 主看板容器：接收 issues，按 status 分组到 5 列渲染 |
| `web/src/components/KanbanColumn.tsx` | 单列：标题 + Agent 角色标签 + Issue 数量 + 卡片列表（可滚动） |
| `web/src/components/IssueCard.tsx` | 卡片：标题（截断）、优先级徽章、状态 Tag、描述摘要 |
| `web/src/components/TopBar.tsx` | 顶栏：Mango Logo + [新建 Issue] 按钮 + Running Badge + Queued Badge |
| `web/src/utils/kanban.ts` | 列定义常量 + `getColumnForIssue()` 映射函数 |

#### 修改文件

| 文件 | 改动 |
|------|------|
| `web/src/App.tsx` | 移除 `<Sider>` 布局 → `<TopBar>` + `<KanbanBoard>`，卡片点击暂打开 `IssueDetail` |
| `web/src/types/index.ts` | 新增 `planning`/`planned`/`review` 状态；新增 `IssuePriority`；Issue 加 `priority`/`spec` |
| `web/src/utils/status.ts` | 加 `planning`/`planned`/`review` 颜色标签；删 `failed` |
| `web/src/api/client.ts` | 新增 `planIssue`、`updateSpec`、`rejectSpec`、`completeIssue`、`editIssue`、`deleteIssue` |
| `web/src/hooks/useIssues.ts` | 移除 `statusFilter`（看板展示全部状态） |
| `web/src/components/IssueForm.tsx` | 新增优先级选择器（`<Select>` high/medium/low） |
| `web/src/components/StatusTag.tsx` | 新增 `planning`/`planned`/`review` 的颜色定义 |

#### 验收标准

- [x] 五列看板正确渲染，每列显示标题 + Agent 角色 + Issue 数量
- [x] Issue 按状态归入对应列
- [x] `waiting_human` Issue 在失败时所在列显示，带 ⚠ 徽章
- [x] 卡片显示标题、优先级、状态 Tag
- [x] 列内卡片按优先级排序
- [x] 卡片点击打开 `IssueDetail`（复用现有组件，3b 步再替换为 Modal）

---

### 第 3b 步：Card Detail Modal + SpecCard

> 在 3a 骨架基础上，为卡片点击增加全屏 Card Detail Modal（左右分栏），替代旧 IssueDetail 面板。

#### 新增文件

| 文件 | 说明 |
|------|------|
| `web/src/components/CardDetailModal.tsx` | 大弹窗：左右分栏，左侧元数据+操作+Spec，右侧实时步骤/历史/日志 Tabs |
| `web/src/components/SpecCard.tsx` | Spec 展示/编辑：计划描述、验收标准清单、待修改文件列表、[确认执行]/[重新生成]/[拒绝] 按钮 |

#### 修改文件

| 文件 | 改动 |
|------|------|
| `web/src/App.tsx` | Kanban 分支中：卡片点击从打开 IssueDetail → 打开 CardDetailModal |
| `web/src/components/KanbanBoard.tsx` | 增加 `selectedIssue` 状态 + Modal 挂载 |

#### 验收标准

- [x] 卡片点击弹出 Card Detail Modal，左侧元数据、右侧实时步骤
- [x] Modal 中 SpecCard 展示 Spec 内容（当 Issue 有 spec 时）
- [x] SSE 实时更新在 Modal 右侧面板仍正常工作
- [x] Modal 关闭后回到看板，状态保持一致

---

## 第四步：看板交互 + 打磨

> 列级操作按钮、编辑/删除、计数器、CSS 动效。

### 列级操作按钮

| 列 | 卡片上的操作 |
|----|-------------|
| Backlog | [▶ Refine] [▶▶ Run] [✏ Edit] [🗑 Delete] |
| Todo | [▶ Run] [✏ Edit Spec] [↩ Reject] |
| Dev | [■ Cancel]，点击查看实时步骤 |
| Review | [✓ Complete]，PR 链接 |
| Done | PR 链接，查看执行历史 |

> 不做拖拽排序（复杂度高、收益低）。用明确的操作按钮替代，每个按钮 = 一个 API 调用。拖拽排序推迟到 ROADMAP 4。

### ActionButtons 全状态矩阵

```typescript
const actions: Record<IssueStatus, ActionDef[]> = {
  open:          [{ label: 'Refine', action: 'plan' }, { label: 'Run', action: 'run' }],
  planning:      [{ label: 'Cancel', action: 'cancel' }],
  planned:       [{ label: 'Run', action: 'run' }, { label: 'Reject', action: 'reject' }],
  running:       [{ label: 'Cancel', action: 'cancel' }],
  review:        [{ label: 'Complete', action: 'complete' }],
  done:          [],
  waiting_human: [{ label: 'Retry', action: 'retry' }],
  cancelled:     [{ label: 'Restart', action: 'run' }],
};
```

### CSS / 样式

- Kanban 列：flex 等宽布局，纵向滚动溢出
- 卡片：圆角、微阴影、hover 效果
- 优先级：卡片左边框颜色（red/orange/gray）
- Running 动画：Dev 列卡片微脉冲
- 列头：彩色顶边框匹配 Agent 角色

### 涉及文件

| 文件 | 改动 |
|------|------|
| `web/src/components/ActionButtons.tsx` | 全状态 action 矩阵 |
| `web/src/components/IssueCard.tsx` | hover 快捷操作按钮 |
| `web/src/components/TopBar.tsx` | Running/Queued Badge 计数 |
| `web/src/App.css` | Kanban 列 flex 布局、卡片样式、优先级色、动画 |

### 验收标准

- [x] 所有列的操作按钮正确触发对应 API
- [x] Issue 编辑/删除按状态守卫正常工作
- [x] Running/Queued 计数准确
- [x] 卡片 hover 显示快捷操作
- [x] UI 美观、可滚动、多 Issue 时不溢出

---

## 第五步：测试 + 集成验证

### 后端测试

| 文件 | 覆盖内容 |
|------|---------|
| `tests/test_api.py` | 新端点 `/plan`、`/spec`、`/reject-spec`、`/complete`、`PATCH`、`DELETE`；更新后的状态转换规则 |
| `tests/test_runtime.py` | Plan 流程（open→planning→planned）；spec 注入执行上下文；`review` 状态；`failed`→`waiting_human` 适配 |
| `tests/test_db.py` | Migration 006 执行；新字段 priority/spec |
| `tests/test_plan_skill.py` | **新增**：PlanSkill prompt 构建、JSON 解析、错误处理 |

### 端到端验证流程

- [x] **完整 Spec 流程**：创建 Issue → Refine（Backlog→Todo）→ 审阅 Spec → Run（Todo→Dev）→ PR（Dev→Review）→ Complete（Review→Done）
- [x] **跳过 Spec 流程**：创建 Issue → Run（Backlog→Dev）→ PR（Dev→Review）→ Done
- [x] **失败重试流程**：创建 → Run → waiting_human（⚠ 在 Dev 列）→ Retry → 成功 → Review → Done
- [x] **取消重启流程**：创建 → Run → Cancel → 重新 Run
- [x] **优先级排序**：HIGH 卡片在列内排在最上方
- [x] **编辑/删除**：open 状态可编辑标题/描述/优先级；done 状态可删除

---

## 文件清单汇总

### 新增文件（10 个）

| # | 文件 | 所属阶段 |
|---|------|---------|
| 1 | `src/mango/db/migrations/006_kanban_statuses.sql` | 第一步 |
| 2 | `src/mango/skills/plan.py` | 第二步 |
| 3 | `web/src/components/KanbanBoard.tsx` | 第 3a 步 |
| 4 | `web/src/components/KanbanColumn.tsx` | 第 3a 步 |
| 5 | `web/src/components/IssueCard.tsx` | 第 3a 步 |
| 6 | `web/src/components/TopBar.tsx` | 第 3a 步 |
| 7 | `web/src/utils/kanban.ts` | 第 3a 步 |
| 8 | `web/src/components/CardDetailModal.tsx` | 第 3b 步 |
| 9 | `web/src/components/SpecCard.tsx` | 第 3b 步 |
| 10 | `tests/test_plan_skill.py` | 第五步 |

### 修改文件（17 个）

| # | 文件 | 涉及阶段 |
|---|------|---------|
| 1 | `src/mango/models.py` | 第一步、第二步 |
| 2 | `src/mango/db/repos.py` | 第一步 |
| 3 | `src/mango/agent/runtime.py` | 第一步、第二步 |
| 4 | `src/mango/agent/context.py` | 第二步 |
| 5 | `src/mango/server/routes.py` | 第一步、第二步 |
| 6 | `web/src/App.tsx` | 第 3a 步、第 3b 步 |
| 7 | `web/src/App.css` | 第 3a 步、第四步 |
| 8 | `web/src/types/index.ts` | 第 3a 步 |
| 9 | `web/src/utils/status.ts` | 第 3a 步 |
| 10 | `web/src/api/client.ts` | 第 3a 步 |
| 11 | `web/src/hooks/useIssues.ts` | 第 3a 步 |
| 12 | `web/src/components/IssueForm.tsx` | 第 3a 步 |
| 13 | `web/src/components/ActionButtons.tsx` | 第四步 |
| 14 | `web/src/components/StatusTag.tsx` | 第 3a 步 |
| 15 | `tests/test_api.py` | 第五步 |
| 16 | `tests/test_runtime.py` | 第五步 |
| 17 | `tests/test_db.py` | 第五步 |

### 废弃文件（1 个）

| # | 文件 | 说明 |
|---|------|------|
| 1 | `web/src/components/IssueList.tsx` | 被 KanbanBoard 替代（第 3a 步） |

---

## 工期预估

| 阶段 | 范围 | 工期 |
|------|------|------|
| 第一步 | 状态机 + DB（含表重建） + 后端路由 | ~2.5 天 |
| 第二步 | PlanSkill + JSON 鲁棒提取 + Spec 流程 | ~3 天 |
| 第 3a 步 | Kanban 骨架 + 卡片 | ~2 天 |
| 第 3b 步 | Card Detail Modal + SpecCard | ~2 天 |
| 第四步 | 交互 + 打磨 | ~2 天 |
| 第五步 | 测试 + 集成验证 | ~1.5 天 |
| **总计** | | **~13 天** |

---

## 关键设计决策

| # | 决策 | 理由 |
|---|------|------|
| 1 | `failed` 合并入 `waiting_human` | 简化状态机。每次失败都需要人类介入，两者语义一致。`failure_reason` 字段提供失败上下文 |
| 2 | `review` 作为显式状态 | 分离"AI 完成编码"和"PR 完成审查"。PR 创建后自然停在 Review 列，移到 Done 是人类决策 |
| 3 | 客户端分组而非服务端 | 无需新增 API，前端从 `GET /api/issues` 按 status 分桶。简单，减少后端改动 |
| 4 | `waiting_human` 列推断 | 不在 DB 加"前一列"字段，而是从 `pr_url`/`branch_name`/`spec` 推断。这些字段沿流水线单调递增，逻辑可靠 |
| 5 | Modal 大弹窗而非 Drawer/独立页面 | 卡片点击弹出全屏级 Modal（左右分栏：左侧元数据+操作，右侧实时 Session），参考 Routa Card Detail 设计 |
| 6 | 操作按钮而非拖拽 | 实现成本低，语义清晰（每个按钮 = 一个 API + 明确前置条件）。拖拽推迟到 ROADMAP 4 |

---

## 推迟到 ROADMAP 4

| 方向 | 前提条件 |
|------|---------|
| 多 Agent / 多模型后端 | Kanban 稳定，有明确的 Agent 特化需求 |
| Docker 沙箱隔离 | 生产环境安全问题突显 |
| Memory 系统（跨任务知识） | 核心循环完全可靠 |
| 拖拽排序 | 用户对操作按钮体验不满意 |
| CI Webhook 集成（Review → Done 自动化） | Webhook 基础设施就绪 |
| workspace 路径白名单 | P2 carry-over |

---

## 设计参考

本规划受 Routa 平台启发，核心借鉴：
- **五列 Kanban Board**：Backlog / Todo / Dev / Review / Done 列映射 Issue 全生命周期
- **Agent 角色标签**：每列标注 Agent 角色（Refiner → Reporter），为未来多 Agent 后端预留概念
- **卡片式 Issue**：优先级、状态、描述摘要，信息密度高
- **Spec 审阅**：Issue → Spec → 执行的分层（Mango 简化为可选的 plan 阶段）
