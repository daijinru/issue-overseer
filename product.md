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


## 四个里程碑

每个里程碑的口号都在变，变化本身就是进展的记录：

- 里程碑 1：Issue 进来，代码出去。
- 里程碑 2：Issue 进来，PR 出去。
- 里程碑 3：看板驱动，流程可见。
- 里程碑 4：项目隔离，经验沉淀。

### 里程碑 1：跑通

三个 Phase，目标是 `open → running → done` 能走完。

Phase 0（1 天）搭骨架。FastAPI、SQLite 三张表、配置加载。验收：`/api/health` 返回 200。

Phase 1（2-3 天）写核心。三层循环 runTask → runTurn → runAttempt、TurnContext、OpenCode 客户端、超时和 cancel。验收：Issue 创建 → AI 执行 → 失败 → 附加指令重试 → 完成 → 代码提交到分支。

Phase 2（2-3 天）做前端。Issue 列表、详情、执行/取消/重试按钮。验收：浏览器里走完全流程。

交付时后端 600 行 Python，前端 800 行 TypeScript，11 个测试文件。

这个版本有个明显的问题：commit 到本地分支就完了，没有 push，没有 PR。不过我当时就是想先证明三层循环能转起来，闭环的事后面再说。

### 里程碑 2：闭环

"代码"变成"PR"，背后改了不少东西。四步。

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

### 里程碑 3：看板

里程碑 2 结束时 Spec 阶段和 Issue 编辑删除还没做完，carry over 到这一轮。但里程碑 3 的主题是把前端从列表视图升级成五列 Kanban Board。

这轮做了五件事：

**状态机扩展。** 从 6 个状态扩到 8 个——加了 `planning`、`planned`、`review`，删了 `failed`（合入 `waiting_human`，所有失败都需要人介入，两个状态语义重复）。SQLite 的 CHECK 约束不支持 ALTER，只能重建表，把状态校验移到了应用层的 Python 枚举。以后加状态不用再重建表。

**PlanSkill + Spec 流程。** 给 Backlog → Todo 的过渡补上了实际逻辑。PlanSkill 让 AI 分析代码库生成结构化 Spec（plan + acceptance_criteria + files_to_modify），输出 JSON。LLM 的 JSON 输出格式不稳定——有时候包在 markdown 代码块里，有时候前后带解释文本——所以写了个 `extract_spec_json()` 做鲁棒提取：先试直接 parse，再试提取代码块，最后正则匹配最外层花括号。提取失败就换 strict prompt 重试一次，还不行就 `waiting_human`。

**五列看板 UI。** 分两步。3a 搭骨架——KanbanBoard、KanbanColumn、IssueCard、TopBar，客户端从 `GET /api/issues` 拿全部数据按 status 分桶到五列，不加新端点。`waiting_human` 和 `cancelled` 是叠加态，卡片留在失败前的列，从 `pr_url` / `branch_name` / `spec` 推断归属。3b 加 Card Detail Modal——卡片点击弹出全屏级大弹窗，左右分栏，左侧元数据和操作，右侧实时步骤流。参考了 Routa 平台的设计。

**交互打磨。** 每个状态对应的操作按钮矩阵（open 可以 Refine 或 Run，running 可以 Cancel，review 可以 Complete），卡片优先级排序，列头彩色边框。没做拖拽排序，操作按钮就够了，拖拽推迟。

**测试。** PlanSkill 的 JSON 提取、状态转换规则、新端点，端到端验证了完整 Spec 流程和跳过 Spec 的流程。

里程碑 3 交付时：后端 ~900 行 Python，前端 ~1500 行 TypeScript。

### 里程碑 4：项目和记忆（规划中）

这是当前在规划的里程碑，还没动手。要解决两个问题。

**第一个问题：没有 Project 概念。** 现在 `workspace` 只是 Issue 上的一个路径字符串，git 配置（default_branch、remote、pr_base）是全局共享的。多仓库场景下 Issue 混在一起，无法按项目过滤，git 配置会冲突。

计划是把 Project 做成一等实体存 DB，每个 Project 绑一个 git 仓库和独立的 git 配置。Issue 挂在 Project 下面。Runtime 从 Project 读配置，不再依赖全局 TOML。迁移时创建一个 default Project，现有 Issue 自动归入。

**第二个问题：没有记忆。** 每个 Issue 从零开始执行，AI 不知道项目的编码风格、测试惯例、上次踩过什么坑。同一类错误反复犯。

计划做两层 Memory：

Issue Memory——Issue 进入 review 后，SummarizeSkill 自动生成一份结构化总结（做了什么、根因是什么、改了哪些文件、学到了什么）。这个是自动的，失败不阻塞主流程。

Project Memory——用户手动触发 DistillSkill，从多条 Issue Memory 里归纳项目级知识（编码约定、常见陷阱、代码结构）。输出 Markdown 文本，注入到 GenericSkill 和 PlanSkill 的 prompt 最前面，让 AI 先了解项目背景再看具体任务。

手动触发归纳是有意为之。自动归纳的时机不好控制，token 消耗也不可预测。先手动跑通，看看效果和成本，再决定要不要自动化。

Memory 带版本号，每次归纳不覆盖旧的，保留历史。Project Memory 注入有 token 预算（默认 3000 字符），超了就截断，不挤占任务描述和 git diff 的空间。

### 回头看四个里程碑

| 里程碑 | 口号 | 做了什么 | 当时的判断 |
|---|---|---|---|
| 1 | 代码出去 | 三层循环 + 本地 commit | 先证明 Agent 能转起来 |
| 2 | PR 出去 | push + PR + SSE + 可靠性修复 | 先闭环，再打磨 |
| 3 | 看板驱动 | 五列 Kanban + Spec + 状态机扩展 | 先让流程可见，再加智能 |
| 4 | 经验沉淀 | Project 隔离 + Memory 系统 | 先单次正确，再跨次积累 |

每个里程碑都在前一个的基础上补一层。不跳步。


## 后面的事

里程碑 4 的推迟事项已经在看里程碑 5 了。里程碑 5 有两条主线：

**主线一：Memory 与集成。** 从里程碑 4 顺延下来的能力补全：

```
Memory 自动归纳        → 手动归纳验证效果和 token 成本之后
Memory 语义检索 / RAG  → Issue Memory 积累够多、简单注入不够用时
多 Agent / 多模型后端  → Project + Memory 稳定之后
CI Webhook 集成        → Webhook 基础设施就绪后
```

**主线二：Harness Engineering——Dev 执行环境打造。** 现在 Crafter 直接在宿主机上跑 OpenCode，代码修改、测试执行、依赖安装都在本地环境里裸奔。里程碑 5 的另一个重点是给 Dev 列建一套隔离的执行环境（harness）——在虚拟化环境中运行 Agent 的编码和测试流程，而不是继续依赖宿主机。这不只是安全问题（Docker 沙箱隔离），更是执行可靠性问题：环境一致、依赖可控、失败可复现、副作用可回收。Harness 做好了，才敢放手让 Agent 跑更激进的操作（装依赖、改配置、跑集成测试），也才有基础做并发执行。

```
虚拟化执行环境          → Crafter 在隔离环境中运行，不污染宿主机
环境快照与复用          → 同一 Project 的多次执行共享基础环境，减少冷启动
执行副作用回收          → 任务失败时环境可丢弃，不留残留状态
并发执行基础            → 每个 Issue 独立环境，不再受串行约束
```

两条主线的先后关系不是固定的。Memory 偏软件层面的积累，Harness 偏基础设施层面的建设，哪个先动手取决于当时最痛的问题是什么。

对应到看板，各列的成长方向：

- Backlog (Refiner) → 任务拆分做好了，Refiner 才有活干
- Todo (Orchestrator) → Spec 稳了才能拆子任务
- Dev (Crafter) → 已经在干活，Memory 注入让它越来越懂项目；Harness 让它的执行环境从裸奔变成可控
- Review (Guard) → CI 回调接入后开始自动化
- Done (Reporter) → Memory 系统就是 Reporter 的雏形


## 最后

我想要的工作流是这样的：需求来了，我写成 Issue，Mango 去干活，我去看 PR。

现在离这个状态还有距离。Mango 处理简单 Issue 基本能跑通，复杂的还经常翻车。翻车了就进 `waiting_human`，我看看日志，补一条指令让它重试。

所以我花时间的地方不是业务代码，是 Mango 本身。让它的上下文传递更准确，让它的失败恢复更靠谱，让它的执行过程对我可见。打磨 Agent 就是打磨我的工作方式。

五列看板现在只有两列在转。但骨架在那里，每个空壳列都知道自己什么时候该长出肌肉来。我不着急。
