# Mango ROADMAP 2 — 里程碑 2

> Issue 进来，PR 出去。

---

## 里程碑 1 完成情况

Phase 0–2 全部完成。核心链路可跑通：Issue CRUD → Agent Runtime 三层循环 → OpenCode 执行 → git commit → 前端轮询展示。后端 ~600 行 Python，前端 ~800 行 TypeScript，11 个测试文件。

---

## 已知问题

### P0 — 必须修

| # | 问题 | 现状 | 影响 | 状态 |
|---|------|------|------|------|
| 1 | **缺少 PR 环节** | Agent commit 到分支就结束，没有 push，没有 PR | "代码出去"没有出口，用户要手动建 PR，code review 和 CI 无法介入 | ✅ 已修：`runtime.py` 新增 `_git_push()` + `_create_pr()`，Issue 模型加 `pr_url`，配置加 `remote` / `pr_base` |
| 2 | **服务重启状态丢失** | cancel_tokens / running_tasks 存内存 | 重启后 Issue 卡在 `running`，永远无法再触发，只能手动改库 | ✅ 已修：`runtime.py` 新增 `recover_from_restart()`，`app.py` 启动时调用，stuck issue → `waiting_human` + 日志 |
| 3 | **成功判定粗糙** | OpenCode 返回非空即 `success=True` | 错误信息也被当作成功结果，空 commit 也算完成 | ✅ 已修：`_git_commit()` 重写，先检查 `git diff --name-only` + `git diff --cached --quiet`，无改动 → `waiting_human`，去掉 `--allow-empty` |

### P1 — 尽快修

| # | 问题 | 现状 | 状态 |
|---|------|------|------|
| 4 | **git 操作不健壮** | 分支已存在时 `checkout -b` 静默失败；`git add -A` 无过滤；`--allow-empty` 提交空 commit | ✅ 已修：`_git_create_branch()` 先 `rev-parse --verify` 判断分支存在；`git add` 改为只 add `diff --name-only` + `ls-files --others --exclude-standard` 的文件；去掉 `--allow-empty` |
| 5 | **状态机漏洞** | `cancelled` 无法重新 run；retry 的状态转换无事务保护 | ✅ 已修：`cancelled` 可重新 run（`routes.py` + `runtime.py`）；`update_fields` 加字段白名单；`retry_reset()` 原子事务保护 |
| 6 | **DB 连接管理** | 每次操作新建连接，高频写入可能 `database is locked` | ✅ 已修：`connection.py` 改为共享连接模式，`init_db()` 后复用单连接，加 `PRAGMA busy_timeout=5000`，shutdown 时关闭 |

### P2 — 有空修

| # | 问题 | 现状 | 状态 |
|---|------|------|------|
| 7 | **安全约束是软防护** | prompt 注入规则 LLM 可以忽略，审计依赖 markdown 格式，事后补救 | 未修 |
| 8 | **workspace 无校验** | 用户可传任意路径（`/etc`），Agent 就在那执行 | 未修 |
| 9 | **update_fields 字段名拼接** | 字段名直接拼入 SQL，当前调用安全但接口有隐患 | ✅ 已修：`repos.py` 新增 `_ALLOWED_ISSUE_FIELDS` 白名单校验 |
| 10 | **前端无实时反馈** | 3 秒轮询，执行中无日志，API 失败无提示 | ✅ 已修：Phase A（SSE 基础）+ Phase B（OpenCode 流式透传）完成。EventBus + SSE 端点 + 前端 EventSource + StepList 实时步骤组件 |
| 11 | **Issue 不可编辑删除** | 创建后无法修改标题/描述，无法删除 | 未修 |

### P3 — 记录备忘

| # | 问题 | 状态 |
|---|------|------|
| 12 | 测试覆盖不足（Runtime 完整路径、cancel、状态机边界、前端零测试） | ⚡ 部分改善：新增 ~200 行 runtime 测试（PR 流程、空 commit 检测、重启恢复、分支已存在、cancelled 重新 run）+ DB 白名单测试。前端仍零测试 |
| 13 | 无结构化日志（难以关联 Issue 完整执行链路） |

---

## 里程碑 2 规划

### 第一步：PR 闭环 + 可靠性修复 ✅

> 解决 P0 + P1，让核心链路从"能跑"变成"能用"。

**PR 闭环（P0 #1 + #3）**

- [x] `_run_task` 成功后：`git push origin {branch}` → `gh pr create`
- [x] PR 标题基于 Issue title，PR 描述包含 Issue 描述 + 变更文件列表
- [x] Issue 新增 `pr_url` 字段，`done` = PR 已创建
- [x] commit 前检查 `git diff --cached --quiet`，无改动则标记 failed 而非空 commit
- [x] 配置项：`[project] remote = "origin"`、`[project] pr_base = "main"`

涉及文件：`runtime.py`、`models.py`、`repos.py`、`001_init.sql`（加字段）、`overseer.toml`

**状态恢复（P0 #2）**

- [x] 服务启动时扫描 `status = 'running'` 的 Issue，标记为 `waiting_human`
- [x] 附带 execution_log："服务重启，执行中断"

涉及文件：`app.py`（startup event）、`runtime.py`

**git 加固（P1 #4）**

- [x] 分支已存在时 `git checkout` 而非 `git checkout -b`
- [x] 去掉 `--allow-empty`
- [x] `git add` 改为只 add OpenCode 实际改动的文件（从 `git diff --name-only` 获取），或至少确认 `.gitignore` 生效

涉及文件：`runtime.py`

**状态机补全（P1 #5）**

- [x] `run_issue` 允许状态增加 `cancelled`
- [x] `update_fields` 增加字段名白名单：`ALLOWED_FIELDS = {"branch_name", "human_instruction", "pr_url", "workspace"}`
- [x] `retry_reset()` 原子事务保护

涉及文件：`routes.py`、`repos.py`

**验收标准**：创建 Issue → AI 执行 → 代码 push 到远端 → PR 自动创建 → Issue 详情展示 PR 链接。服务重启后无卡死 Issue。

### 第二步：执行过程可见

> 解决 P2 #10，用户不再面对黑盒。

#### Phase A — SSE 基础（替换轮询） ✅

> Turn 级别实时推送，替换 3 秒轮询。独立可交付，风险极低。

**EventBus 内存事件总线**

- [x] 新增 `server/event_bus.py`（或 `agent/event_bus.py`），基于 `asyncio.Queue` 的 per-issue pub/sub
- [x] 数据结构：`dict[str, list[asyncio.Queue]]`（issue_id → subscribers）
- [x] 接口：`subscribe(issue_id)` / `unsubscribe(issue_id, queue)` / `publish(issue_id, event)`
- [x] 订阅者断开时自动清理 Queue，防止内存泄漏

涉及文件：新增 `server/event_bus.py`

**Runtime 事件发射**

- [x] `_run_task` 开始/结束：发 `task_start` / `task_end`
- [x] `_run_turn` 开始/结束：发 `turn_start` / `turn_end`
- [x] `_run_attempt` 开始/结束：发 `attempt_start` / `attempt_end`
- [x] `_git_commit` / `_git_push` / `_create_pr`：发 `git_commit` / `git_push` / `pr_created`
- [x] EventBus 实例通过 `app.state` 挂载，Runtime 构造时注入

涉及文件：修改 `runtime.py`（~8-10 个发射点）、修改 `app.py`（挂载 EventBus）

**SSE 端点**

- [x] 新增 `GET /api/issues/{id}/stream` SSE 端点
- [x] 使用 FastAPI `StreamingResponse`（`media_type="text/event-stream"`），无需额外依赖
- [x] 连接生命周期管理：客户端断开清理、issue 执行完成关闭 stream、支持多客户端同时监听同一 issue

涉及文件：新增 `server/sse.py`、修改 `routes.py`（注册路由）

**前端 EventSource**

- [x] `useIssueDetail.ts`：当 `issue.status === 'running'` 时创建 `EventSource` 连接 `/api/issues/{id}/stream`
- [x] 实时接收事件更新 `logs` / `executions` 状态
- [x] 保留 `usePolling` 作为 fallback（SSE 连接失败时回退到 3 秒轮询）
- [x] 新增 SSE 事件类型定义到 `types/index.ts`

涉及文件：修改 `useIssueDetail.ts`、修改 `types/index.ts`

**Phase A 验收标准**：AI 执行中，前端通过 SSE 实时收到 turn 级别事件（"第 1 轮开始"、"第 1 轮结束"、"代码已提交"、"PR 已创建"），不再依赖轮询。SSE 断开后自动回退到轮询。

---

#### Phase B — OpenCode 流式透传（细粒度步骤） ✅

> 依赖 Phase A 的 EventBus。实现"正在读取 xxx.py"的实时步骤展示。

**opencode_client 流式改造**

- [x] `proc.communicate()` 替换为 `async for line in proc.stdout` 逐行读取 NDJSON
- [x] 每行解析后通过 EventBus 实时转发（事件类型 `opencode_step`，通过 `on_event` 回调桥接）
- [x] 保留 "last wins" 语义用于最终结果提取（`_parse_output` 的最终聚合逻辑不变）
- [x] cancel 机制适配：从 `asyncio.wait({comm_task, cancel_wait})` 改为流式循环中检查 cancel flag + `proc.kill()`

涉及文件：修改 `opencode_client.py`

**tool_use 事件解析**

- [x] 新增 `_classify_event()` 解析 tool_use 事件（grep / read / edit / shell），提取操作类型 + 目标文件路径
- [x] 如果 OpenCode 不输出 tool_use 事件 → 降级为推送 `parts` 级别文本摘要事件（仍优于 Phase A）

涉及文件：修改 `opencode_client.py`

**前端步骤列表**

- [x] 新增 `StepList.tsx`：展示 OpenCode 实时步骤流（"读取 xxx.py"、"修改 yyy.py"、"执行 pytest"）
- [x] `IssueDetail.tsx` 的 Tabs 中新增"实时步骤"tab 挂载 `StepList`
- [x] `useIssueDetail.ts` 新增 `steps` 状态，`opencode_step` 事件直接累积到 state（不触发 REST re-fetch）

涉及文件：新增前端 `StepList.tsx`、修改 `IssueDetail.tsx`、修改 `useIssueDetail.ts`、修改 `types/index.ts`

**Phase B 验收标准**：AI 执行中，用户在浏览器实时看到"读取 xxx.py"、"修改 yyy.py"等步骤流。

---

#### 技术风险与应对

| 风险 | 等级 | 应对策略 |
|------|------|---------|
| OpenCode `tool_use` 事件格式未明确 | 🟡 中 | Phase B 开始前先运行 `opencode run --format json` 抓取实际输出，确认事件结构。若无 tool_use → 降级为 `parts` 级别推送，Phase B 的前端仅展示文本摘要而非文件级步骤 |
| `communicate()` → `readline()` 后 cancel 机制变化 | 🟢 低 | 流式循环中每次 readline 前检查 `cancel_event.is_set()`，为 True 时 `proc.kill()` + break。比原来的 `asyncio.wait` 模式更简单 |
| SSE 连接生命周期（客户端断开、多客户端、执行完成） | 🟢 低 | EventBus unsubscribe 在 `finally` 块中执行；`task_end` 事件触发 stream 关闭；Queue 有 maxsize 防内存膨胀 |
| 背压 / 内存 | 🟢 低 | 单 issue 串行执行，事件量有限（几十到几百条）。Queue 设 `maxsize=1000`，溢出时丢弃旧事件并记日志 |

### 第三步：Spec 阶段（可选流程）

> AI 先出方案，用户确认后再执行。

```
open → planning → planned → running → done (PR created)
         ↑                     ↑
     POST /plan           POST /run
```

- [x] 新增状态 `planning` / `planned`
- [x] `POST /api/issues/{id}/plan`：调用 OpenCode 生成 Spec（PlanSkill）
- [x] Spec 结构：`{plan: string, acceptance_criteria: string[], files: string[]}`
- [x] `PUT /api/issues/{id}/spec`：用户编辑 Spec
- [x] `POST /api/issues/{id}/run`：执行时将 Spec 注入 TurnContext
- [x] 前端 Spec 卡片：展示计划 + 验收标准，"确认执行" / "重新生成" 按钮
- [x] Spec 是可选流程：用户可以从 `open` 直接 `run`，跳过 plan

涉及文件：`models.py`、`routes.py`、`repos.py`、新增 `skills/plan.py`、前端新增 `SpecCard.tsx`、`001_init.sql`（加 spec 字段）

**验收标准**：用户点"生成计划"→ 看到 AI 的执行方案 → 确认或修改 → 点"执行"→ Agent 按计划工作 → PR 创建。

### 第四步：基础体验打磨

- [ ] Issue 编辑（`PUT /api/issues/{id}`，仅 `open` / `planned` 可编辑）
- [ ] Issue 删除（`DELETE /api/issues/{id}`，仅 `open` / `done` / `failed` 可删除）
- [ ] 前端 API 错误提示（Ant Design Message）
- [ ] workspace 路径白名单（`[security] allowed_workspaces`）

---

## 推迟事项

| 方向 | 前提条件 |
|------|---------|
| Docker 沙箱隔离 | 安全问题在分支隔离 + 审计下不够用时 |
| opencode serve Session 复用 | OpenCode serve 模式稳定后 |
| 任务拆分 + 并行执行 | Spec 阶段成熟后 |
| Memory 系统（跨任务知识） | 核心链路完全可靠后 |
| 多模型 / Provider 切换 | 执行层抽象完成后 |

---

## 设计参考

本规划受 Routa 平台启发，核心借鉴：
- **Spec 审阅**：Issue → Spec → 执行的分层（Mango 简化为可选的 plan 阶段）
- **过程可见**：Thinking Chain 实时展示 AI 的 grep/read/edit 步骤
- **结构化进度**：Task Snapshot 看板（Mango 简化为 Turn 卡片视图）
