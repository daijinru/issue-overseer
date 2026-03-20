# Mango — 设计原则

## 核心理念

**Issue 进来，代码出去。** 不做多余的事。

## 设计原则

### 1. Runtime 是大脑，OpenCode 是手

Agent Runtime 负责决策和循环控制（做什么、重试几次、什么时候停）。
OpenCode 负责实际的代码修改和命令执行（读代码、改代码、跑命令）。

Runtime 不自己实现 file_read / file_write / shell_exec 等原子操作，
这些全部交给 OpenCode（通过 `opencode serve` HTTP API 调用）。

### 2. Skill 是 Agent 的能力单元

Skill 负责将 Issue + TurnContext 转化为 prompt 交给 OpenCode 执行。
MVP 用通用 Skill（基于 TurnContext 构造 prompt，根据上下文自适应）。
后续按需扩展具体 Skill（fix_test_failure、write_feature、code_review）。

测试验证本身也是工具，不内嵌到核心链路中，后续作为 Skill 的可选步骤加回来。

### 3. Agent 管一切

没有可插拔后端，没有 Runner 抽象。只有一个 Agent Runtime。
Agent Runtime 管理整个任务生命周期：分支创建 → 上下文构建 → Skill 调用 → 代码提交。

### 4. 每轮都有上下文

每轮 Turn 携带完整 TurnContext（Issue、last_result、last_error、git_diff、execution_history、human_instruction），避免"瞎重试"。上下文有截断策略防止 token 溢出。

### 5. 安全边界

Agent 通过 OpenCode 执行命令，需要安全约束：
- Phase 1：Prompt 注入命令白名单 + 执行审计（记录到 execution_logs）
- Phase 3：Docker 沙箱隔离

### 6. 失败后人类可介入

AI 重试全部失败后，Issue 进入 `waiting_human` 状态，用户可附加指令重试（retry with instruction）。用户的指令注入 TurnContext，Agent 带着历史经验 + 新指令继续工作。

### 7. MVP 极简

能推迟的推迟，能不做的不做。每加一个功能，先问：
- 这个不做，核心链路能跑通吗？
- 这个能用现有工具替代吗？（OpenCode 替代自研 Tool 层）

### 8. 1:1 映射

- 1 Issue = 1 次 Agent 执行（不做拆分）
- 串行执行，不并发
- 1 个 Agent Runtime 实例

## 技术栈

| 组件 | 选型 | 说明 |
|------|------|------|
| 语言 | Python 3.12+ | AI 生态、subprocess 友好 |
| HTTP 框架 | FastAPI | 异步、自动 OpenAPI |
| 数据库 | SQLite (aiosqlite) | 零运维、单文件 |
| AI 执行层 | OpenCode (serve 模式) | 不造轮子，直接用成熟的 AI 编码代理 |
| 前端 | React + Ant Design | 复用现有基础 |
| 包管理 | uv | 快 |
| 配置 | pydantic-settings + TOML | 类型安全 |

## 架构

```
Web UI (Issue 面板)
   ↓ REST API
FastAPI Server
   ↓
Agent Runtime (核心)
   ├── runTask → runTurn → runAttempt 三层循环
   ├── TurnContext 上下文（每轮携带 Issue + last_result + git_diff + history）
   ├── 超时控制（Attempt 300s / Task 1800s / 用户随时 cancel）
   ├── Skill 调用（基于 TurnContext 构造 prompt + 安全约束注入）
   └── git 分支 + commit
   ↓ HTTP API
OpenCode (serve 模式, 常驻)
   ↓
SQLite (issues + executions + execution_logs, 3 张表)
```

## 数据模型

三张表：

- **issues** — 用户创建的任务（title、description、status、branch_name、human_instruction）
- **executions** — 每次执行记录（issue_id、turn_number、attempt_number、prompt、result、context_snapshot、git_diff_snapshot、duration_ms）
- **execution_logs** — 执行日志（execution_id、level、message）

状态机：
```
Issue:  open → running → done
                      → failed → waiting_human → running → ...
                                      ↑ 用户 POST /retry with instruction
```

## 参考文档

- 精简版 Roadmap（当前方案）：[ROADMAP.md](./ROADMAP.md)
