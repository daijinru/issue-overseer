# Claude Overseer — 设计原则

## 核心理念

**Issue 进来，代码出去。** 不做多余的事。

## 设计原则

### 1. 一切皆工具

所有外部能力都是工具箱里的工具，由 Agent 自主决定何时调用。
Runtime 不硬编码任何业务逻辑到执行管线中。

- worktree 创建/清理是工具
- git push / PR 创建是工具
- claude_code 子任务委托是工具
- memory_read / memory_extract 是工具

**判断标准**：如果一个能力是"Agent 在执行任务时可能用到的"，它就应该是工具，而不是 Runtime 的内部方法。

### 2. Agent 管一切

没有 AgentBackend 接口，没有可插拔后端。只有一个 Agent Runtime。
Agent 自己管理 LLM 对话、工具调用、工作区创建、代码编写、推送、PR 创建。
决策权在 Agent，不在 Runner，不在 Scheduler。

### 3. Runner 超薄

Runner 只做两件事：
1. 调用 `agent.run()`
2. 更新数据库状态

不介入 Agent 的执行过程，不做环境准备，不做后处理。

### 4. MVP 极简

能推迟的推迟，能不做的不做。每加一个功能，先问：
- 这个不做，核心链路能跑通吗？
- 这个能用最简单的方式替代吗？（如 WebSocket → 轮询，Auth → 不做）

### 5. 1:1 映射

MVP 阶段保持简单映射关系：
- 1 Issue = 1 AgentTask（不做拆分）
- 1 AgentTask = 1 Agent 执行（串行，不并发）
- 1 Agent Runtime 实例（单例）

## 技术栈

- 语言：TypeScript
- HTTP 框架：Hono / Fastify（单进程）
- 数据库：SQLite（better-sqlite3）
- LLM：Anthropic API（MVP 只配一个模型）
- 包管理器：待定

## 架构分层

```
LAYER 1: Issue Service     — Issue CRUD + 状态流转 + Issue→Task 转换
LAYER 2: Agent Runtime     — Task Queue + Scheduler + Runner + AgentRuntime
底层:     SQLite            — 4 张表: issues, agent_tasks, executions, memory
```

## Memory 设计

任务级经验记忆，用于跨任务积累项目知识：

- `memory_read`：Agent 在任务中读取已有项目知识
- `memory_extract`：Agent 在任务收尾时调用，工具内部通过独立 LLM 调用 + 固定提取规则，从对话摘要中结构化提取可复用知识并写入
- 存储：SQLite KV 表，`UNIQUE(category, key)` 保证同一知识只保留最新值
