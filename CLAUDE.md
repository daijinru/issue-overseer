# Mango — 设计原则

## 核心理念

**Issue 进来，代码出去。** 不做多余的事。

> 里程碑 1 之后的补充：代码出去的形态是 PR，不是裸 commit。代码对不对交给 code review 和 CI——Mango 负责干活和递 PR，不负责当裁判。

## 设计原则

### 1. Runtime 是大脑，OpenCode 是手

Agent Runtime 负责决策和循环控制（做什么、重试几次、什么时候停）。
OpenCode 负责实际的代码修改和命令执行（读代码、改代码、跑命令）。

**职责边界**：

| 谁做 | 做什么 | 为什么 |
|------|--------|--------|
| **Runtime** | git branch / commit / push / PR 创建、DB 读写、状态机流转、超时控制 | 流程控制，必须 100% 确定性 |
| **OpenCode** | 读代码、改代码、跑 pytest、搜索文件、生成 Spec | AI 编码能力，允许不确定性 |

分界线：**确定性操作 Runtime 自己干，需要创造力的操作交给 OpenCode（通过 `opencode run` CLI 子进程调用）。**

### 2. Skill 是 Agent 的能力单元

Skill 负责将 Issue + TurnContext 转化为 prompt 交给 OpenCode 执行。
已有 GenericSkill（通用执行），后续按需扩展：

- **PlanSkill** — 生成执行计划和验收标准（Spec 阶段）
- 其他按需：fix_test_failure、write_feature、code_review

### 3. Agent 管一切

没有可插拔后端，没有 Runner 抽象。只有一个 Agent Runtime。
Agent Runtime 管理整个任务生命周期：分支创建 → 上下文构建 → Skill 调用 → 代码提交 → PR 创建。

> 代码质量的验证（code review、CI）不在 Mango 职责范围内。Mango 把 PR 递出去，剩下的交给工程体系。

### 4. 每轮都有上下文

每轮 Turn 携带完整 TurnContext（Issue、last_result、last_error、git_diff、execution_history、human_instruction、spec），避免"瞎重试"。上下文有截断策略防止 token 溢出。

### 5. 安全边界

Agent 通过 OpenCode 执行命令，需要安全约束：
- Prompt 注入命令白名单 + 执行审计（记录到 execution_logs）
- workspace 路径白名单，拒绝敏感系统目录
- DB 操作字段名白名单校验
- 远期：Docker 沙箱隔离

### 6. 人类始终在环（Human-in-the-Loop）

人类介入不只在失败后——执行前也能介入：

- **执行前**：Spec 阶段，AI 先出方案 + 验收标准，用户确认后再执行（可选流程）
- **执行中**：实时日志可见，用户随时 cancel
- **执行后失败**：Issue 进入 `waiting_human`，用户可附加指令重试

### 7. 极简，但不偷工减料

能推迟的推迟，能不做的不做。每加一个功能，先问：
- 这个不做，核心链路能**正确**跑通吗？（跑通 ≠ 正确，没有验证的完成不算完成）
- 这个能用现有工具替代吗？（OpenCode 替代自研 Tool 层）
- 这个是让系统更可靠，还是只是更花哨？（可靠性不能推迟）
- 这个是 Mango 该做的事吗？（代码质量验证是 code review 和 CI 的职责，不是 Mango 的）

### 8. 1:1 映射（当前约束）

- 1 Issue = 1 次 Agent 执行（不做拆分）
- 串行执行，不并发
- 1 个 Agent Runtime 实例

> 这是当前阶段的简化约束，不是永久架构限制。当 Spec 阶段成熟、需要处理复杂 Issue 时，可演进为任务拆分 + 并行执行。

### 9. 过程可见

用户不应面对黑盒。执行过程中至少能看到：
- 当前在第几轮、每轮做了什么
- AI 正在读/写哪些文件、跑什么命令
- 实时日志流，而非事后查看

## 技术栈

| 组件 | 选型 | 说明 |
|------|------|------|
| 语言 | Python 3.12+ | AI 生态、subprocess 友好 |
| HTTP 框架 | FastAPI | 异步、自动 OpenAPI |
| 数据库 | SQLite (aiosqlite) | 零运维、单文件 |
| AI 执行层 | OpenCode (CLI 子进程) | 不造轮子，直接用成熟的 AI 编码代理 |
| 前端 | React + Ant Design | 复用现有基础 |
| 包管理 | uv | 快 |
| 配置 | pydantic-settings + TOML | 类型安全 |

## 架构

```
Web UI (Issue 面板 + Spec 审阅 + 实时日志)
   ↓ REST API + SSE
FastAPI Server
   ↓
Agent Runtime (核心)
   ├── runTask → runTurn → runAttempt 三层循环
   ├── TurnContext 上下文（每轮携带 Issue + last_result + git_diff + history + spec）
   ├── 超时控制（Attempt 300s / Task 1800s / 用户随时 cancel）
   ├── Skill 调用（GenericSkill / PlanSkill）
   ├── 服务重启状态恢复
   └── git 分支 + commit + push + PR 创建
   ↓ subprocess (opencode run)
OpenCode (CLI, 按需调用)
   ↓
SQLite (issues + executions + execution_logs, 3 张表)
```

## 数据模型

三张表：

- **issues** — 用户创建的任务（title、description、status、branch_name、human_instruction、spec、pr_url）
- **executions** — 每次执行记录（issue_id、turn_number、attempt_number、prompt、result、context_snapshot、git_diff_snapshot、duration_ms）
- **execution_logs** — 执行日志（execution_id、level、message）

状态机：
```
Issue:  open → planning → planned → running → done
                                            → failed → waiting_human → running → ...
                                                            ↑ 用户 POST /retry with instruction
        cancelled（任何 running 状态可 cancel，cancelled 可重新 run）
```

> `planning` / `planned` 是可选流程。用户也可以从 `open` 直接 `run`，跳过 Spec 阶段。

## 参考文档

- 里程碑 1 Roadmap：[ROADMAP.md](./ROADMAP.md)
- 里程碑 2 Roadmap（问题修复 + 下一步）：[ROADMAP2.md](./ROADMAP2.md)
