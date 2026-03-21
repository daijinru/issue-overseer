# Mango ROADMAP — AI 驱动的代码生成平台

> **Issue 进来，代码出去。**
> 极简 Agent Runtime + OpenCode 执行层，先跑通一条最窄的链路。

---

## 一、核心链路

```
Issue 面板 (Web UI)
   ↓  用户创建 Issue，点击 "AI 执行"
Agent Runtime (Python, 自研)
   ↓  runTask → runTurn → runAttempt 循环
   ↓  每轮携带 TurnContext（Issue + last_result + git_diff + history）
Skill (构造 prompt，调用 OpenCode)
   ↓  命令白名单约束（prompt 注入 + 审计）
Execution (OpenCode serve HTTP API)
   ↓  OpenCode 读代码、改代码、执行命令
   ↓  超时控制：Attempt 300s / Task 1800s / 用户随时 cancel
Result
   ├── 完成 → git commit 到分支
   ├── 失败 → 重试（最多 3 次）
   └── 仍失败 → waiting_human（用户可附加指令重试）
```

---

## 二、架构

```
┌─────────────────────────────────┐
│        Web UI (Issue 面板)       │
│  创建 Issue · 查看状态           │
└──────────────┬──────────────────┘
               │ REST API
               ▼
┌─────────────────────────────────┐
│     FastAPI Server (Python)      │
│  Issue CRUD · Task 状态 · 触发   │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│      Agent Runtime (核心)        │
│                                  │
│  runTask                         │
│   ├── 加载 Issue 上下文          │
│   ├── git checkout -b 创建分支   │
│   ├── 进入 Turn 循环:            │
│   │   runTurn                    │
│   │    ├── 选择 Skill            │
│   │    ├── Skill 构造 prompt     │
│   │    ├── runAttempt            │
│   │    │    └── 调用 OpenCode    │
│   │    └── 完成? → 退出循环      │
│   │       失败? → 下一 Turn      │
│   ├── 成功 → git commit 到分支    │
│   └── 更新 Issue 状态            │
└──────────────┬──────────────────┘
               │ HTTP API
               ▼
┌─────────────────────────────────┐
│   OpenCode (serve 模式, 常驻)    │
│   POST /session → /message       │
│   AI 编码能力: 读/写/搜索/命令   │
└─────────────────────────────────┘
               │
        ┌──────┴───────┐
        │   SQLite DB   │
        │  issues       │
        │  executions   │
        └──────────────┘
```

### 为什么用 OpenCode 做执行层

RE_ROADMAP 里要自己写 12 个 Tool（file_read、file_write、shell_exec、git_ops...），每个都要实现、测试、维护。

OpenCode 已经是一个完整的 AI 编码代理，内置了所有这些能力。通过 `opencode serve` 暴露 HTTP API，Agent Runtime 只需要：

```python
# 创建会话
session = httpx.post(f"{OPENCODE_URL}/session").json()

# 发送任务
response = httpx.post(
    f"{OPENCODE_URL}/session/{session['id']}/message",
    json={
        "parts": [{"type": "text", "text": prompt}],
    },
    timeout=300,
)
```

**Runtime 是大脑（决策 + 循环控制），OpenCode 是手（代码修改 + 命令执行）。**

---

## 三、Agent Runtime 设计

保留三层循环结构，但职责更聚焦：

```
runTask(issue)                         ← 任务级（总超时 1800s）
│
│  1. 从 DB 加载 Issue（含 human_instruction，如有）
│  2. git checkout -b agent/{issue_id}
│  3. 创建 Execution 记录
│  4. 注册 cancel token（响应用户取消）
│  5. 进入 Turn 循环
│  6. 结束后更新状态
│
├─▶ runTurn(context) × max_turns (默认 3)    ← 对话轮级
│   │
│   │  1. 构建 TurnContext（见下方）
│   │  2. Skill 基于 TurnContext 构造 prompt
│   │  3. 调用 runAttempt（检查 cancel token）
│   │  4. 判断结果：完成 → 退出循环，失败 → 继续下一 Turn
│   │  5. 记录 execution log
│   │
│   └─▶ runAttempt(prompt)                   ← 执行级（超时 300s）
│       │
│       │  1. 调用 OpenCode HTTP API
│       │  2. 等待执行完成（可被 cancel 中断）
│       │  3. 返回结果（成功/失败 + 输出）
│       │
│       └── 返回 AttemptResult
```

### TurnContext — 每轮上下文

每轮 Turn 携带完整上下文，避免"瞎重试"：

```python
@dataclass
class TurnContext:
    issue: Issue                    # 原始 Issue（title + description）
    turn_number: int               # 当前第几轮（从 1 开始）
    max_turns: int                 # 最大轮数
    last_result: Optional[str]     # 上轮 OpenCode 返回内容
    last_error: Optional[str]      # 上轮错误信息
    git_diff: Optional[str]        # 当前分支 vs default_branch 的 diff
    execution_history: list[dict]  # 历史轮次摘要 [{turn, status, summary}]
    human_instruction: Optional[str]  # 用户附加指令（retry with instruction）
```

> **截断策略**：`git_diff` 超过 2000 行时只保留前 2000 行 + 提示 `[truncated]`。
> `last_result` 超过 5000 字符时摘要处理。

### 超时与取消机制

三层超时，逐层控制：

| 层级 | 超时 | 触发行为 |
|------|------|---------|
| Attempt（单次调用） | 300s | abort 当前 OpenCode HTTP 请求 |
| Task（整个任务） | 1800s | 终止所有 Turn，Task 标记 failed |
| 用户 cancel | 随时 | cancel token 传播，abort 正在进行的调用 |

实现要点：
- **cancel token**：`asyncio.Event`，贯穿 runTask → runTurn → runAttempt
- **HTTP abort**：OpenCode 调用使用 httpx，cancel 时调用 `response.aclose()`
- **cancel API**：`POST /api/issues/{id}/cancel` 设置 cancel token，正在执行的 Attempt 在下一个 await 点检测并退出
- **进程级 kill**：如果 OpenCode 进程无响应（超时后仍未返回），记录异常并标记 Task failed

### 状态机

```
Issue:    open → running → done
                        → failed → waiting_human → running → ...
                                        ↑ 用户 POST /retry with instruction
Task:     queued → executing → completed / failed / cancelled
                      ↑            │
                      └── retry ───┘ (retry_count < 3)
```

### 退出条件

| 条件 | 结果 |
|------|------|
| OpenCode 完成任务 | → git commit 到分支，Task completed |
| 达到 max_turns（3 次） | → Task failed → Issue waiting_human |
| Attempt 超时（300s） | → 当前 Turn failed，尝试下一 Turn |
| Task 总超时（1800s） | → Task failed → Issue waiting_human |
| 用户 cancel | → Task cancelled，保留已有进度 |
| 用户 retry with instruction | → 重新进入 running，携带新指令 |

---

## 四、数据模型

两张表 + 一张日志表：

```sql
CREATE TABLE issues (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'open'
    CHECK(status IN ('open', 'running', 'done', 'failed', 'waiting_human', 'cancelled')),
  branch_name TEXT,
  human_instruction TEXT,              -- 用户附加指令（retry with instruction）
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE executions (
  id TEXT PRIMARY KEY,
  issue_id TEXT NOT NULL REFERENCES issues(id),
  turn_number INTEGER NOT NULL,        -- 第几轮 Turn
  attempt_number INTEGER NOT NULL,     -- 第几次 Attempt
  status TEXT NOT NULL DEFAULT 'running'
    CHECK(status IN ('running', 'completed', 'failed', 'cancelled', 'timeout')),
  prompt TEXT,                         -- 发给 OpenCode 的完整 prompt
  result TEXT,                         -- OpenCode 返回的结果
  error_message TEXT,
  context_snapshot TEXT,               -- JSON: 本轮 TurnContext 快照
  git_diff_snapshot TEXT,              -- 执行前的 git diff
  duration_ms INTEGER,                 -- 执行耗时（毫秒）
  started_at TEXT DEFAULT (datetime('now')),
  finished_at TEXT
);

CREATE TABLE execution_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  execution_id TEXT NOT NULL REFERENCES executions(id),
  level TEXT NOT NULL DEFAULT 'info'
    CHECK(level IN ('info', 'warn', 'error')),
  message TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_issues_status ON issues(status);
CREATE INDEX idx_exec_issue ON executions(issue_id);
CREATE INDEX idx_logs_exec ON execution_logs(execution_id);
```

> **设计说明**：
> - `execution_logs` 独立成表，避免 `executions.result` 字段膨胀，也方便按时间查询
> - `context_snapshot` 存 JSON，完整记录每轮输入，用于调试和回放
> - `duration_ms` 用于超时统计和性能分析
> - Issue 新增 `waiting_human` 和 `cancelled` 状态

---

## 五、Skill

Skill 是 Agent 完成任务的能力单元。每个 Skill 负责：将 Issue 转化为 prompt → 调用 OpenCode 执行。

MVP 先不限定具体 Skill 类型，Agent Runtime 将 Issue 描述直接构造为 prompt 交给 OpenCode。

```python
class Skill:
    """Skill 基类"""

    async def run(self, issue: Issue, cwd: str) -> SkillResult:
        # 1. 将 Issue 转化为 prompt
        prompt = self.build_prompt(issue)

        # 2. 调用 OpenCode 执行
        result = await self.call_opencode(prompt, cwd)

        return SkillResult(
            success=result.ok,
            message=result.output,
        )
```

> 后续按需扩展具体 Skill（fix_test_failure、write_feature、code_review 等），
> 每个 Skill 的差异在于 `build_prompt` 的策略不同。
> 测试验证（pytest）也可以作为 Skill 的一个可选步骤加回来。

---

## 五·一、安全约束

Agent 通过 OpenCode 执行 shell 命令，需要安全边界。

### 命令白名单策略

分三层防护，逐步加固：

**第一层：Prompt 约束（Phase 1 必做）**

在每次发给 OpenCode 的 prompt 中注入安全规则：

```
## 安全规则
你只能使用以下命令：
- git (所有子命令)
- python / pytest / pip / uv
- cat / ls / find / grep / head / tail
- mkdir / cp / mv（仅限项目目录内）
- echo / printf

严格禁止：
- rm -rf /、rm -rf ~、rm -rf .
- curl | bash、wget | sh（禁止远程执行）
- chmod 777、chown
- 任何 sudo 命令
- 任何访问 /etc、/usr、/var 的操作
- 任何网络请求（除非 Issue 明确要求）
```

**第二层：执行审计（Phase 1 必做）**

- 每次 Attempt 完成后，从 OpenCode 返回的结果中提取执行过的命令
- 记录到 `execution_logs` 表
- 检测是否有违规命令，如果有则标记警告

**第三层：系统级沙箱（Phase 3）**

- Docker 容器隔离
- 文件系统只读挂载（除工作目录外）
- 网络限制

### 配置

```toml
# overseer.toml
[security]
allowed_commands = ["git", "python", "pytest", "pip", "uv", "cat", "ls", "find", "grep", "head", "tail", "mkdir", "cp", "mv", "echo"]
blocked_patterns = ["rm -rf /", "rm -rf ~", "sudo", "curl | bash", "wget | sh", "chmod 777"]
```

> **务实原则**：Prompt 约束是"软防护"，LLM 可能不完全遵守。
> 但配合 git 分支隔离 + 审计日志，MVP 阶段足够安全。
> 真正高风险场景等 Phase 3 上 Docker。

---

## 六、Web UI

基于现有 React + Ant Design 改造，或新起一个极简页面。只需要：

### 一个页面，三个区域

```
┌─────────────────────────────────────────────┐
│  Mango · AI Issue Board                      │
├──────────────────┬──────────────────────────┤
│                  │                           │
│  Issue 列表       │  Issue 详情               │
│                  │                           │
│  ● [open]  #1    │  标题: 修复登录测试失败    │
│  ● [running] #2  │  描述: test_login.py ...  │
│  ● [done] #3     │                           │
│  ○ [waiting] #4  │  状态: waiting_human       │
│  ● [failed] #5   │  分支: agent/issue-4       │
│                  │                           │
│  [+ 新建 Issue]  │  执行日志:                 │
│                  │  > Turn 1: 失败 - timeout  │
│                  │  > Turn 2: 失败 - test err │
│                  │  > Turn 3: 失败 - same err │
│                  │                           │
│                  │  ⚠ AI 执行失败，等待指令    │
│                  │  ┌─────────────────────┐  │
│                  │  │ 试试 pytest -x 只跑  │  │
│                  │  │ 失败的那个测试       │  │
│                  │  └─────────────────────┘  │
│                  │  [▶ 重试(附加指令)]        │
│                  │  [▶ AI 执行]  [取消]       │
│                  │                           │
└──────────────────┴──────────────────────────┘
```

### API

```
POST   /api/issues              创建 Issue
GET    /api/issues              列出 Issue (?status=open&status=waiting_human)
GET    /api/issues/{id}         获取 Issue 详情（含 Execution 历史 + logs）
POST   /api/issues/{id}/run     触发 AI 执行
POST   /api/issues/{id}/cancel  取消执行（实际 abort 正在进行的调用）
POST   /api/issues/{id}/retry   附加指令重试 Body: {"instruction": "..."}
GET    /api/issues/{id}/logs    获取执行日志（分页）
GET    /api/health              健康检查
```

---

## 七、技术栈

| 组件 | 选型 | 理由 |
|------|------|------|
| 语言 | Python 3.12+ | AI 生态、subprocess 友好 |
| HTTP 框架 | FastAPI | 异步、自动 OpenAPI |
| 数据库 | SQLite (aiosqlite) | 零运维、单文件 |
| AI 执行层 | OpenCode (serve 模式) | 不造轮子，直接用成熟的 AI 编码代理 |
| 前端 | React + Ant Design | 复用现有 console/client 基础 |
| 包管理 | uv | 快 |

### 环境变量

| 变量 | 用途 |
|------|------|
| `OPENAI_API_KEY` 或对应 LLM Key | OpenCode 使用的 LLM API |
| `OPENCODE_URL` | OpenCode serve 地址（默认 `http://localhost:4096`） |

---

## 八、目录结构

```
mango/
├── pyproject.toml
├── overseer.toml                  # 配置（含 security、context）
├── README.md
│
├── src/mango/
│   ├── __init__.py
│   ├── main.py                    # uvicorn 启动
│   │
│   ├── server/
│   │   ├── app.py                 # FastAPI 实例
│   │   └── routes.py              # 所有 API（一个文件够了）
│   │
│   ├── agent/
│   │   ├── runtime.py             # runTask → runTurn → runAttempt
│   │   ├── context.py             # TurnContext 构建 + 截断
│   │   ├── safety.py              # Prompt 安全约束 + 执行审计
│   │   └── opencode_client.py     # OpenCode HTTP 客户端（含超时 + cancel）
│   │
│   ├── skills/
│   │   └── base.py                # Skill 基类（MVP 直接用基类）
│   │
│   ├── db/
│   │   ├── connection.py          # SQLite 连接
│   │   ├── migrations/
│   │   │   └── 001_init.sql
│   │   └── repos.py               # issue_repo + execution_repo + log_repo
│   │
│   └── models.py                  # Pydantic 模型（含 TurnContext）
│
├── tests/
│   ├── test_runtime.py
│   ├── test_context.py            # TurnContext 构建 + 截断测试
│   ├── test_safety.py             # 安全约束测试
│   └── test_api.py
│
└── web/                           # 前端（后续独立或复用 console/client）
    └── ...
```

**对比 RE_ROADMAP 的目录结构**：从 30+ 个 Python 文件缩减到 ~13 个。

---

## 九、配置

```toml
# overseer.toml

[server]
port = 18800

[agent]
max_turns = 3                       # 每个 Issue 最多重试 3 次
task_timeout = 1800                 # 单个 Task 总超时（秒）

[opencode]
url = "http://localhost:4096"       # OpenCode serve 地址
timeout = 300                       # 单次 Attempt 调用超时（秒）

[project]
repo_path = "."                     # 目标仓库本地路径
default_branch = "main"

[database]
path = "./data/mango.db"

[security]
allowed_commands = ["git", "python", "pytest", "pip", "uv", "cat", "ls", "find", "grep", "head", "tail", "mkdir", "cp", "mv", "echo"]
blocked_patterns = ["rm -rf /", "rm -rf ~", "sudo", "curl | bash", "wget | sh", "chmod 777"]

[context]
max_git_diff_lines = 2000          # git diff 截断行数
max_result_chars = 5000            # last_result 截断字符数
```

---

## 十、ROADMAP

### Phase 0 — 基础骨架 (1 天)

- [x] pyproject.toml + uv 初始化
- [x] FastAPI 骨架 + `/api/health`
- [x] SQLite 建表（3 张表：issues, executions, execution_logs）
- [x] Pydantic 模型（含 TurnContext）
- [x] overseer.toml 配置加载（含 security、context 配置）
- [x] 验收：`uv run python -m mango` 启动，`/api/health` 返回 200

### Phase 1 — Agent Runtime + 核心机制 (2-3 天)

- [ ] OpenCode HTTP 客户端封装（创建会话 + 发送 prompt + 获取结果）
- [ ] Agent Runtime: runTask → runTurn → runAttempt
- [ ] TurnContext 构建（Issue + last_result + last_error + git_diff + history）
- [ ] git_diff 截断策略（超 2000 行截断 + [truncated] 提示）
- [ ] Skill 基类（基于 TurnContext 构造 prompt → OpenCode）
- [ ] 超时机制：Attempt 300s + Task 1800s
- [ ] cancel 机制：asyncio.Event cancel token + HTTP abort
- [ ] Prompt 安全约束注入（命令白名单规则）
- [ ] 执行审计：从结果中提取命令记录到 execution_logs
- [ ] git 分支管理（checkout -b / commit）
- [ ] Issue CRUD API
- [ ] `/api/issues/{id}/run` 触发执行
- [ ] `/api/issues/{id}/cancel` 取消执行（实际 abort）
- [ ] `/api/issues/{id}/retry` 附加指令重试（waiting_human → running）
- [ ] execution_logs 写入 + 查询 API
- [ ] 验收：创建 Issue → AI 执行 → 失败 → retry with instruction → 完成 → 代码提交到分支

### Phase 2 — Web UI (2-3 天)

- [ ] Issue 列表页（状态筛选，含 waiting_human 状态）
- [ ] Issue 详情页（执行日志 + TurnContext 快照查看）
- [ ] 创建 Issue 表单
- [ ] "AI 执行" 按钮 + 状态轮询
- [ ] "取消" 按钮（调用 cancel API）
- [ ] 失败后 "附加指令重试" 交互（文本框 + 重试按钮）
- [ ] 验收：用户在浏览器上完成 创建 → AI 执行 → 失败 → 附加指令重试 → 查看结果 全流程

### Phase 3 — 安全加固 + 打磨 (后续)

- [ ] Docker 沙箱隔离（文件系统只读 + 网络限制）
- [ ] Memory 系统（跨任务积累项目知识）
- [ ] 执行日志实时推送（SSE）
- [ ] 多模型支持
- [ ] 命令审计仪表盘（统计危险命令触发频率）

**目标代码量**：< 800 行 Python + 1 个前端页面。

**目标交付时间**：Phase 0 + Phase 1 = 4-5 天跑通核心链路。
