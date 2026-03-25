# Mango——我的 Agent，我的工作方式

我在做一个 AI 编码 Agent，叫 Mango。

想法很简单：以后项目上有需求，我不直接去改业务代码了。我把需求写成 Issue 丢给 Mango，它读代码、改代码、跑测试、提 PR。我去 review PR，合了就算完事。

我的精力放在打磨 Mango 本身——它的 Runtime 怎么跑、Skill 怎么组织、上下文怎么传递、失败了怎么重试。业务代码让 Agent 去写，我来写 Agent。

这篇文档记录 Mango 当前的架构和演进过程。给自己看的，也留着以后回头看走了多少弯路。


## 看板

前端是一块五列看板：

```typescript
// kanban.ts
{ key: 'backlog',  title: 'Backlog',  agentRole: 'Refiner',      statuses: ['open'] },
{ key: 'todo',     title: 'Todo',     agentRole: 'Orchestrator', statuses: ['planning', 'planned'] },
{ key: 'dev',      title: 'Dev',      agentRole: 'Crafter',      statuses: ['running'] },
{ key: 'review',   title: 'Review',   agentRole: 'Guard',        statuses: ['review'] },
{ key: 'done',     title: 'Done',     agentRole: 'Reporter',     statuses: ['done'] },
```

每列有个 Agent 角色名。以后的理想状态是：Issue 从左往右走，每一列都有对应的 AI 能力在运转。Refiner 细化需求，Orchestrator 拆任务出方案，Crafter 写代码，Guard 做自动审查，Reporter 沉淀知识。

当前只有 Crafter 和 Orchestrator 在干活，其余三个是空壳。不急，先把能用的做好。


## 骨架和肌肉

| 看板列 | agentRole | 当前实现 |
|--------|-----------|---------|
| Backlog | Refiner | 空的。Issue 进来就是 `open` |
| Todo | Orchestrator | `PlanSkill` 生成 Spec，prompt → OpenCode → 解析 JSON |
| Dev | Crafter | `GenericSkill` 执行，真正干活的地方 |
| Review | Guard | 一个 `POST /complete` 端点，人手动确认 |
| Done | Reporter | 空的 |

五个角色只实现了两个。但五列看板已经搭好了，状态枚举写全了，前端组件到位了。接口留着，等我后面往里填。

CLAUDE.md 里给自己定的规矩：

> 能推迟的推迟，能不做的不做。每加一个功能，先问：这个不做，核心链路能正确跑通吗？

这条我尽量在守。说实话有时候手痒，想给 Review 列加个自动 code review，想给 Done 列加个执行报告。但现在 Crafter 这一列都还没打磨到位，别的先放着。


## 每一列怎么想的

**Backlog（open）** Issue 进来就是 open，1 个 Issue 对应 1 次 Agent 执行，不做拆分。Agent 解一道题的能力还不稳，先别给它出一套连环题。

**Todo（planning → planned）** 用户可以让 AI 先出方案再执行，也可以跳过直接 run。改个 typo 不需要方案，重构一个模块才需要。`PlanSkill` 的重试很简单：JSON 解析失败换 strict prompt 再来一次，还不行就 `waiting_human`，让我来看。

**Dev（running）** 这里的关键是 Runtime 和 OpenCode 的分工。确定性的事情 Runtime 自己干：建分支、commit、push、创建 PR。需要创造力的事情交给 OpenCode：读代码、改代码、跑测试。

我故意没让 Runtime 去判断代码写得对不对。测试通没通过是 CI 的事，代码质量好不好是 code review 的事。Mango 负责干活和递 PR，不当裁判。

**Review（review）** PR 创建成功后 Issue 进 `review`，不直接进 `done`。这个列当前就是等我去看 PR。以后可能接 CI 回调，PR merge 了自动进 done。但现在，Guard 就是我自己。

**Done（done）** 我确认了就 done。没有自动报告，没有知识沉淀。以后会加。


## 两个里程碑

口号变了一个字：

- 里程碑 1：Issue 进来，代码出去。
- 里程碑 2：Issue 进来，PR 出去。

"代码"变成"PR"，背后改了不少东西。

### 里程碑 1：跑通

三个 Phase，目标是 `open → running → done` 能走完。

Phase 0（1 天）搭骨架。FastAPI、SQLite 三张表、配置加载。验收：`/api/health` 返回 200。

Phase 1（2-3 天）写核心。三层循环 runTask → runTurn → runAttempt、TurnContext、OpenCode 客户端、超时和 cancel。验收：Issue 创建 → AI 执行 → 失败 → 附加指令重试 → 完成 → 代码提交到分支。

Phase 2（2-3 天）做前端。Issue 列表、详情、执行/取消/重试按钮。验收：浏览器里走完全流程。

交付时后端 600 行 Python，前端 800 行 TypeScript，11 个测试文件。

这个版本有个明显的问题：commit 到本地分支就完了，没有 push，没有 PR。不过我当时就是想先证明三层循环能转起来，闭环的事后面再说。

### 里程碑 2：闭环

四步。

**第一步，PR 闭环 + 可靠性修复。**

| 问题 | 怎么修的 |
|---|---|
| 没有 push/PR | 加了 `_git_push()` + `_create_pr()` |
| 空 commit 算成功 | `git diff --cached --quiet` 检查 |
| 分支已存在 checkout -b 报错 | 先 `rev-parse --verify` 判断 |
| 重启后 Issue 卡在 running | `recover_from_restart()` 启动时扫描 |
| cancelled 没法重新跑 | 状态机补全 |
| DB 高频写入 locked | 共享连接 + `busy_timeout=5000` |

修完之后状态机多了 `review`——PR 建好进 review，我确认后才 done。看板上 Review 列就是这么来的。

`_run_task` 还加了个 lifecycle execution record（turn=0, attempt=0），给任务级操作（建分支、push、创建 PR）一个日志载体。之前只有每轮 Turn 的记录，跨 Turn 的操作没地方写。

**第二步，执行过程可见。**

分两个 Phase。Phase A 做 SSE：EventBus + Runtime 在关键节点发事件 + SSE 端点 + 前端 EventSource。Phase B 做 OpenCode 流式透传：逐行读 NDJSON，前端 StepList 实时展示"读取 xxx.py"、"修改 yyy.py"。

这么拆是因为 Phase A 不依赖 OpenCode 的输出格式，稳得住。Phase B 要解析 tool_use 事件，格式不对就降级成文本摘要。

**第三步，Spec 阶段。** `planning` / `planned` 两个状态，PlanSkill 生成方案，用户可以改、可以拒绝、可以跳过。Todo 列在这一步才真正有了后端逻辑。

**第四步，体验打磨。** Issue 编辑删除、看板视图、优先级排序。

### 回头看

| 里程碑 1 | 里程碑 2 | 当时的判断 |
|---|---|---|
| commit 就结束 | push + PR | 先跑通再闭环 |
| 空 commit 算成功 | diff 检查 | 先能完成，再正确完成 |
| checkout -b 静默失败 | rev-parse 判断 | 先能跑，再健壮 |
| 重启后卡死 | recover_from_restart | 先能用，再可恢复 |
| 3 秒轮询 | SSE + 流式 | 先能看结果，再能看过程 |
| 无任务级日志 | lifecycle record | 先 Turn 内可追踪，再全程可追踪 |

里程碑 1 的每个缺陷都是故意留的。卡在"能跑通"的最低标准上，剩下的交给下一轮。


## 后面要做的

每一条绑了前提条件，不是"以后再说"：

```
Docker 沙箱隔离     → 分支隔离 + 审计不够用的时候
任务拆分 + 并行执行  → Spec 阶段跑稳之后
Memory 系统         → 核心链路完全可靠之后
多模型切换          → 执行层抽象做完之后
```

对应到看板：

- Backlog (Refiner) → 任务拆分做好了，Refiner 才有活干
- Todo (Orchestrator) → Spec 稳了才能拆子任务
- Dev (Crafter) → 已经在干活，持续优化
- Review (Guard) → 等 CI 回调接入
- Done (Reporter) → 等 Memory 系统


## 最后

我想要的工作流是这样的：需求来了，我写成 Issue，Mango 去干活，我去看 PR。

现在离这个状态还有距离。Mango 处理简单 Issue 基本能跑通，复杂的还经常翻车。翻车了就进 `waiting_human`，我看看日志，补一条指令让它重试。

所以我花时间的地方不是业务代码，是 Mango 本身。让它的上下文传递更准确，让它的失败恢复更靠谱，让它的执行过程对我可见。打磨 Agent 就是打磨我的工作方式。

五列看板现在只有两列在转。但骨架在那里，每个空壳列都知道自己什么时候该长出肌肉来。我不着急。
