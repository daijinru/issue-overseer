# 从看板五列说起——Mango 的架构克制与工程务实

## 看板定义

```typescript
// kanban.ts
{ key: 'backlog',  title: 'Backlog',  agentRole: 'Refiner',      statuses: ['open'] },
{ key: 'todo',     title: 'Todo',     agentRole: 'Orchestrator', statuses: ['planning', 'planned'] },
{ key: 'dev',      title: 'Dev',      agentRole: 'Crafter',      statuses: ['running'] },
{ key: 'review',   title: 'Review',   agentRole: 'Guard',        statuses: ['review'] },
{ key: 'done',     title: 'Done',     agentRole: 'Reporter',     statuses: ['done'] },
```

五列看板，每列挂了一个 Agent 角色名。表面上是一块看板，背后是 Mango 整个架构选择的缩影。


## 一、理想的骨架，现实的肌肉

Refiner、Orchestrator、Crafter、Guard、Reporter——五个角色名画出了一幅完整的蓝图：AI 在每个阶段都有不同职责。

打开后端代码，实际情况是这样的：

| 看板列 | agentRole | 后端实现 |
|--------|-----------|---------|
| Backlog | Refiner | 空的。Issue 创建就是 `open`，没有精炼逻辑 |
| Todo | Orchestrator | `PlanSkill` 生成 Spec，一个 prompt → OpenCode → 解析 JSON 的流程 |
| Dev | Crafter | `GenericSkill` 执行，真正干活的地方 |
| Review | Guard | 只有一个 `POST /complete` 端点，review → done |
| Done | Reporter | 空的。状态变了就完了 |

五个角色，两个在干活，三个是空壳。

但这正是设计意图。CLAUDE.md 里写得很明确：

> 能推迟的推迟，能不做的不做。每加一个功能，先问：这个不做，核心链路能正确跑通吗？

骨架先搭完，肌肉按需长。空壳不是偷懒——是架构预留的接口，等待真实需求来驱动。


## 二、每一列背后的决策

### Backlog（open）——不做 Issue 拆分

```
Issue 进来就是 open。1 Issue = 1 次执行。
```

很多 AI 编码平台在这一步就想做"大 Issue 自动拆分子任务"。Mango 选了 1:1 映射。ROADMAP 的说法是：

> 这是当前阶段的简化约束，不是永久架构限制。

工程上的考虑：Agent 能力还不稳定时，引入任务拆分只会放大不确定性。先保证一个 Issue 能正确解决。

### Todo（planning → planned）——Spec 可选，不强制

```python
# routes.py
if issue.status not in (IssueStatus.open, IssueStatus.planned, ...):
    raise HTTPException(...)
```

用户可以从 `open` 直接跳到 `running`，绕过 Spec 阶段。修个 typo、加个测试，不需要先出方案。复杂 Issue 才需要 plan 当安全网。

`PlanSkill` 的重试逻辑也很简单——JSON 解析失败就换 strict prompt 重试一次，再不行就 `waiting_human`。不搞无限重试，不搞复杂的 fallback 链。

### Dev（running）——Runtime 和 OpenCode 的分界线

这里代码量最大。但值得看的不是做了什么，是没做什么。

Runtime 自己干的（确定性操作）：
- `_git_create_branch()`：分支存在就 checkout，不存在就 checkout -b
- `_git_commit()`：只 add 实际变更的文件，`--cached --quiet` 检查有没有真的 staged
- `_git_push()` + `_create_pr()`：推代码，建 PR

丢给 OpenCode 的（需要创造力）：
- 读代码、理解代码、改代码、跑测试——全部通过一个 prompt 字符串交出去

刻意没做的：
- 没有自动跑 pytest 验证结果
- 没有分析 OpenCode 输出来判断代码质量
- 没有 Memory 系统

CLAUDE.md 的原话：

> Mango 负责干活和递 PR，不负责当裁判。

不在 Runtime 里判断测试通不通过——这个判断交给 CI。不在 Runtime 里做 code review——这个交给人。这条线画得很清楚。

### Review（review）——一个显式的等待区

```python
await self.issue_repo.update_status(issue_id, IssueStatus.review)
```

PR 创建成功后 Issue 进入 `review`，不是 `done`。但 Mango 自己不做任何 review。

```python
@router.post("/issues/{issue_id}/complete")
async def complete_issue(issue_id: str):
    if issue.status != IssueStatus.review:
        raise HTTPException(...)
    await repo.update_status(issue_id, IssueStatus.done)
```

这个列存在的意义不是让 Mango 做事，是为了不让 Issue 假装已经完成。PR 递出去了，但人还没确认——那就不是 done。

看板角色叫 Guard，当前的 Guard 就是人。以后可能接 CI 回调，可能接自动 review Agent。但现在它只是一盏红灯：PR 还没 merge。

### Done（done）——状态值，仅此而已

人确认了，done。没有自动报告，没有统计分析，没有知识沉淀。Reporter 是空的，但位置留着。


## 三、两个里程碑之间的演进

里程碑 1 到里程碑 2 的修复清单比任何设计文档都更能说明问题：

| 里程碑 1 的状态 | 里程碑 2 的修复 | 背后的判断 |
|---|---|---|
| commit 就结束，没有 push/PR | 加了 `_git_push()` + `_create_pr()` | 先跑通再闭环 |
| `--allow-empty` 空 commit 也算成功 | 检查 `git diff --cached --quiet` | 先"能完成"，再"正确完成" |
| `git checkout -b` 分支存在时静默失败 | 先 `rev-parse --verify` 判断 | 先"能跑"，再"健壮" |
| 服务重启后 running Issue 卡死 | `recover_from_restart()` | 先"能用"，再"可恢复" |
| 3 秒轮询没有实时反馈 | EventBus + SSE + 流式步骤 | 先"能看结果"，再"能看过程" |

每一个里程碑 1 的"不完美"都不是随意的。它精确地落在"核心链路能跑通"的最低标准上。里程碑 1 的目标是 `open → running → done`——哪怕 done 的定义粗糙。里程碑 2 才把 done 细化为 `running → review → done`，加入 PR 闭环。

不在第一版追求完美。但清楚哪些不完美需要修，哪些可以接受。


## 四、推迟事项不是待办列表

ROADMAP2 末尾的推迟事项，每一条都绑了前提条件：

```
Docker 沙箱隔离     → 安全问题在分支隔离 + 审计下不够用时
任务拆分 + 并行执行  → Spec 阶段成熟后
Memory 系统         → 核心链路完全可靠后
多模型切换          → 执行层抽象完成后
```

不是"以后再说"，是"当 X 发生时才做 Y"。

投射到看板上，演进路径大致是：

- Backlog (Refiner) → 任务拆分成熟后开始工作
- Todo (Orchestrator) → Spec 成熟后可拆分子任务
- Dev (Crafter) → 已经在工作，持续优化 Skill
- Review (Guard) → CI 回调接入后开始自动化
- Done (Reporter) → Memory 系统上线后开始沉淀知识


## 小结

五列看板是完整的骨架——对称、角色清晰。但骨架里只长了两块肌肉（PlanSkill 和 GenericSkill），刚好是当前核心链路需要的那两块。其余三个位置标了角色名，留了接口，没写一行多余的代码。

先用最少的代码让 Issue 跑完全程，再在每个阶段按需注入能力。
