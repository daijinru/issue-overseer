# Mango 可控智能系统架构方案（v3）

## 当前状态

```
┌──────────┐         ┌──────────┐
│ web      │ :5173   │ gateway  │ :18900
│ (kanban) │         │ (会话+路由)│
└────┬─────┘         └────┬─────┘
     │ 直连 /api          │ HTTP /api
     └────────┬───────────┘
              ▼
       ┌─────────────┐
       │   agent     │ :18800
       │ (状态管理 +  │
       │  执行引擎 +  │
       │  git 操作)   │
       └─────────────┘
```

问题：
- web 直连 agent，绕过了一切管控
- gateway 自称 "bridge, not a brain"，只做 3 路消息分发
- agent 身兼数职：Issue 状态机 + 执行编排 + git 操作 + 日志
- 没有控制平面，没有策略审批，没有决策记录

---

## 目标架构

你的分层意图：

| 层 | 职责 | 模块 |
|----|------|------|
| **Business Service** | 面向用户的业务逻辑，各自独立 | **kanban**（看板管理）、**webim**（IM 对话驱动） |
| **Gateway** | 消息交换、访问控制、会话管理 | **gateway**（纯网关，不含业务决策） |
| **Control Plane** | 状态机、Policy、决策记录 | **提供接口，由 Business Service 实现** |
| **Agent Runtime** | 纯执行 + 反馈 | **agent**（只做被要求做的事，汇报结果） |

关键设计：**控制平面是接口，不是服务**。它定义"游戏规则"（状态机、Policy 协议、决策记录格式），各 Business Service 按自己的业务需要实现这些接口。

```
┌─────────────────┐     ┌─────────────────┐
│ kanban (BS)      │     │ webim (BS)       │
│                  │     │                  │
│ KanbanPlane      │     │ WebimPlane       │
│ (实现 ControlPlane│     │ (实现 ControlPlane│
│  接口，看板特有的 │     │  接口，对话特有的 │
│  策略和编排逻辑)  │     │  策略和编排逻辑)  │
└───────┬──────────┘     └───────┬──────────┘
        │                        │
        └──────────┬─────────────┘
                   ▼
          ┌────────────────┐
          │ gateway        │
          │ (消息交换       │
          │  访问控制       │
          │  会话管理)      │
          └───────┬────────┘
                  ▼
          ┌────────────────┐
          │ agent          │
          │ (纯执行引擎     │
          │  + 反馈)        │
          └────────────────┘
```

---

## 控制平面：接口定义

控制平面不是一个独立服务，而是一组**接口和基础设施**，供各 Business Service 实现。

### 核心接口

**新建**: `shared/control_plane/`（共享包，被各 BS 依赖）

```
shared/
└── control_plane/
    ├── __init__.py
    ├── interfaces.py       # 核心抽象接口
    ├── state_machine.py    # 声明式 FSM 引擎（通用）
    ├── issue_fsm.py        # Issue 状态转移声明（领域规则）
    ├── policies.py         # Policy ABC + 内置通用 Policy
    ├── decision.py         # DecisionRecord 数据结构
    └── proposal.py         # AgentProposal 数据结构（Phase 2）
```

#### interfaces.py

```python
class ControlPlaneBase(ABC):
    """控制平面接口 — 各 Business Service 实现此接口。

    每个 BS 有自己的 ControlPlane 实现，因为：
    - kanban 需要 plan → review 的完整生命周期管理
    - webim 需要对话驱动的简化流程（跳过 plan，直接 run）
    - 未来的 CI bot 可能需要完全自动化的策略

    但它们共享同一套：
    - 状态机定义（Issue 的合法状态转移是领域规则，不随 BS 变化）
    - Policy 协议（评估接口统一，具体 Policy 可不同）
    - 决策记录格式（审计链格式统一）
    """

    @abstractmethod
    async def request_transition(
        self, issue_id: str, event: str, context: dict
    ) -> DecisionRecord:
        """请求状态转移 — 唯一的状态变更入口。"""
        ...

    @abstractmethod
    async def evaluate_policies(
        self, event: str, issue: dict, context: dict
    ) -> list[PolicyResult]:
        """评估所有 Policy。"""
        ...

    @abstractmethod
    async def record_decision(self, record: DecisionRecord) -> None:
        """持久化决策记录。"""
        ...
```

#### state_machine.py

```python
@dataclass(frozen=True)
class Transition:
    source: str
    target: str
    event: str
    description: str = ""

class StateMachine:
    """声明式有限状态机。纯逻辑，无 IO，无副作用。"""

    def __init__(self, transitions: list[Transition]):
        self._index: dict[tuple[str, str], Transition] = {
            (t.source, t.event): t for t in transitions
        }

    def get_transition(self, source: str, event: str) -> Transition | None:
        return self._index.get((source, event))

    def can_transition(self, source: str, event: str) -> bool:
        return (source, event) in self._index

    def available_events(self, source: str) -> list[str]:
        return [e for (s, e) in self._index if s == source]

    def all_states(self) -> set[str]:
        states = set()
        for t in self._index.values():
            states.add(t.source)
            states.add(t.target)
        return states
```

#### issue_fsm.py

```python
"""Issue 状态转移声明 — 领域规则，所有 Business Service 共享。"""

ISSUE_TRANSITIONS = [
    # Plan flow
    Transition("open",     "planning",      "plan_start",       "开始生成 Spec"),
    Transition("planning", "planned",       "plan_succeed",     "Spec 生成成功"),
    Transition("planning", "waiting_human", "plan_fail",        "Spec 生成失败"),
    Transition("planning", "cancelled",     "cancel",           "取消规划"),
    Transition("planned",  "open",          "reject_spec",      "驳回 Spec"),

    # Execution flow
    Transition("open",           "running", "exec_start",       "开始执行"),
    Transition("planned",        "running", "exec_start",       "按计划执行"),
    Transition("waiting_human",  "running", "exec_start",       "人工指导后重试"),
    Transition("cancelled",      "running", "exec_start",       "重新启动"),

    # Execution outcomes
    Transition("running", "review",        "exec_succeed",      "执行成功，待审查"),
    Transition("running", "done",          "exec_succeed_no_pr","执行成功，无需 PR"),
    Transition("running", "waiting_human", "exec_fail",         "执行失败，需人工介入"),
    Transition("running", "cancelled",     "cancel",            "取消执行"),

    # Review
    Transition("review", "done",           "complete",          "审查通过"),

    # Recovery
    Transition("running",  "waiting_human", "recover",          "服务恢复"),
    Transition("planning", "waiting_human", "recover",          "服务恢复"),
]

ISSUE_FSM = StateMachine(ISSUE_TRANSITIONS)
```

#### policies.py

```python
class Policy(ABC):
    """策略接口 — 回答"这个动作是否被允许"。"""
    name: str

    @abstractmethod
    async def evaluate(
        self, event: str, issue: dict, context: dict
    ) -> PolicyResult:
        ...

@dataclass
class PolicyResult:
    policy_name: str
    allowed: bool
    reason: str

# ── 通用 Policy（各 BS 可选用）──

class RetryLimitPolicy(Policy):
    """限制重试次数。"""
    name = "retry_limit"

    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries

    async def evaluate(self, event, issue, context) -> PolicyResult:
        if event != "exec_start":
            return PolicyResult(self.name, True, "不适用")
        retry_count = context.get("retry_count", 0)
        if retry_count >= self.max_retries:
            return PolicyResult(self.name, False,
                f"已重试 {retry_count} 次，超过上限 {self.max_retries}")
        return PolicyResult(self.name, True, "在重试限制内")


class ConcurrencyPolicy(Policy):
    """限制并发执行数量。"""
    name = "concurrency"

    def __init__(self, max_concurrent: int = 1):
        self.max_concurrent = max_concurrent

    async def evaluate(self, event, issue, context) -> PolicyResult:
        if event not in ("exec_start", "plan_start"):
            return PolicyResult(self.name, True, "不适用")
        running_count = context.get("running_count", 0)
        if running_count >= self.max_concurrent:
            return PolicyResult(self.name, False,
                f"当前已有 {running_count} 个任务运行中")
        return PolicyResult(self.name, True, "并发数在限制内")
```

#### decision.py

```python
@dataclass
class DecisionRecord:
    id: str
    issue_id: str
    event: str
    from_state: str
    to_state: str | None       # rejected 时为 None
    decision: str              # "approved" | "rejected"
    reason: str
    policy_results: list[dict]
    source: str                # "kanban" | "webim" | "cli" ...
    created_at: str
```

---

## 各层改造

### Agent 层：回归纯执行引擎

Agent 剥离状态管理职责，只做三件事：
1. **接收指令，执行任务**（run / plan / cancel）
2. **汇报结构化结果**（通过 SSE 事件）
3. **维护执行数据**（executions / logs / steps）

**关键改造**：agent 的 routes.py 中的状态守卫（409 检查）**保留**作为安全兜底，但它们不再是业务决策——业务决策在 Business Service 的 ControlPlane 实现中完成。

Agent **不改大结构**。Phase 1 不动 agent，Phase 2 新增结构化反馈事件。

### Gateway 层：纯网关

Gateway 保持其定位：
- **消息交换**：在 Business Service 和 Agent 之间转发 HTTP / SSE
- **访问控制**：认证、鉴权、限流（未来）
- **会话管理**：session 生命周期

Gateway 的 `_route_message()` 中的 3 路分发逻辑**上移**到 webim Business Service。Gateway 变成更纯粹的转发层。

**改造**：
- `GatewayService` 精简为：会话管理 + 消息持久化 + 请求转发
- 去掉 `_route_message()` 中的业务决策（状态判断、创建 Issue、触发 run）
- 新增通用的 `forward_to_agent()` 方法
- 新增访问控制钩子（预留）

### Business Service 层：kanban + webim

两个独立的 Business Service，各自实现 `ControlPlaneBase`。

#### kanban（看板服务）

**新建模块**: `kanban/`

kanban 是现有 web 前端的后端服务。当前 web 直连 agent，改为 web → kanban service → gateway → agent。

```
kanban/
├── pyproject.toml
├── src/mango_kanban/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── server/
│   │   ├── app.py
│   │   └── routes.py          # 对 web 前端暴露的 API
│   ├── plane/
│   │   ├── __init__.py
│   │   └── kanban_plane.py    # 实现 ControlPlaneBase
│   ├── service/
│   │   ├── gateway_client.py  # 通过 gateway 访问 agent
│   │   └── kanban_service.py  # kanban 特有的业务逻辑
│   └── db/
│       ├── connection.py
│       ├── repos.py           # DecisionRecordRepo
│       └── migrations/
│           └── 001_init.sql   # decision_records 表
```

**KanbanPlane** 的特点：
- 支持完整的 plan → review 生命周期
- 允许人工编辑 Spec、驳回 Spec
- Policy：并发限制、重试限制、超时预算
- 决策记录持久化到自己的 DB

```python
class KanbanPlane(ControlPlaneBase):
    """Kanban 的控制平面实现。

    特点：完整生命周期管理，人工可介入每个环节。
    """
    def __init__(self, fsm, policies, gateway_client, decision_repo):
        self.fsm = fsm              # 共享的 ISSUE_FSM
        self.policies = policies    # kanban 选用的 Policy 集合
        self.gateway = gateway_client
        self.decisions = decision_repo

    async def request_transition(self, issue_id, event, context):
        # 1. FSM 校验
        issue = await self.gateway.get_issue(issue_id)
        transition = self.fsm.get_transition(issue["status"], event)
        if not transition:
            return self._rejected(issue_id, event, issue["status"],
                f"不允许从 {issue['status']} 执行 {event}")

        # 2. Policy 审批
        results = await self.evaluate_policies(event, issue, context)
        rejected = [r for r in results if not r.allowed]
        if rejected:
            return self._rejected(issue_id, event, issue["status"],
                "; ".join(r.reason for r in rejected))

        # 3. 通过 gateway 委派给 agent
        await self._dispatch(issue_id, event, context)

        # 4. 记录决策
        record = DecisionRecord(
            id=uuid4(), issue_id=issue_id, event=event,
            from_state=issue["status"], to_state=transition.target,
            decision="approved", reason="",
            policy_results=[asdict(r) for r in results],
            source="kanban", ...
        )
        await self.decisions.save(record)
        return record

    async def _dispatch(self, issue_id, event, context):
        match event:
            case "exec_start":
                instruction = context.get("human_instruction")
                if instruction:
                    await self.gateway.retry_issue(issue_id, instruction)
                else:
                    await self.gateway.run_issue(issue_id)
            case "plan_start":
                await self.gateway.plan_issue(issue_id)
            case "cancel":
                await self.gateway.cancel_issue(issue_id)
            case "reject_spec":
                await self.gateway.reject_spec(issue_id)
            case "complete":
                await self.gateway.complete_issue(issue_id)
```

**kanban routes.py** — 对 web 前端暴露的 API，替代当前 web 直连 agent：

```python
@router.post("/issues/{issue_id}/run")
async def run_issue(issue_id: str, request: Request):
    plane = request.app.state.plane  # KanbanPlane
    decision = await plane.request_transition(issue_id, "exec_start", {})
    if decision.decision == "rejected":
        raise HTTPException(409, detail=decision.reason)
    return {"message": "Task started", "issue_id": issue_id, "decision_id": decision.id}
```

#### webim（IM 对话服务）

**新建模块**: `webim/`

webim 是对话驱动的 Business Service，取代 gateway 中现有的 `_route_message()` 业务逻辑。

```
webim/
├── pyproject.toml
├── src/mango_webim/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── server/
│   │   ├── app.py
│   │   └── routes.py          # IM 消息接口
│   ├── plane/
│   │   └── webim_plane.py     # 实现 ControlPlaneBase
│   ├── service/
│   │   ├── gateway_client.py
│   │   └── conversation.py    # 对话→Issue 的转换逻辑
│   └── db/
│       ├── connection.py
│       ├── repos.py
│       └── migrations/
│           └── 001_init.sql
```

**WebimPlane** 的特点：
- 简化流程：跳过 plan，用户消息直接触发 run
- 对话上下文管理：多轮对话映射到同一 Issue
- Policy：可能更宽松（用户在对话中隐式授权重试）

```python
class WebimPlane(ControlPlaneBase):
    """Webim 的控制平面实现。

    特点：对话驱动，简化流程，自动决策。
    """
    async def request_transition(self, issue_id, event, context):
        # 同样的 FSM + Policy 流程，但：
        # - 使用 webim 专属的 Policy 集合（更宽松）
        # - 决策 source 标记为 "webim"
        ...
```

**conversation.py** — 从 gateway 的 `_route_message()` 提取出来的逻辑：

```python
class ConversationService:
    """对话服务 — 将用户消息转换为 Issue 操作。

    这就是当前 GatewayService._route_message() 的业务逻辑，
    上移到 webim Business Service 中。
    """
    async def handle_message(self, session_id, content, context):
        # 获取当前 session 绑定的 issue
        issue = await self._get_current_issue(session_id)

        if issue is None:
            # 无 Issue → 创建 + 执行
            issue = await self.gateway.create_issue(title=content[:100], ...)
            decision = await self.plane.request_transition(
                issue["id"], "exec_start", {}
            )
            return decision

        match issue["status"]:
            case "waiting_human":
                decision = await self.plane.request_transition(
                    issue["id"], "exec_start",
                    {"human_instruction": content}
                )
                return decision
            case "running" | "planning":
                raise ConflictError("当前任务正在执行中")
            case _:
                # done/review/cancelled → 新建 Issue
                issue = await self.gateway.create_issue(...)
                decision = await self.plane.request_transition(
                    issue["id"], "exec_start", {}
                )
                return decision
```

---

## 数据流全景

```
用户操作 Kanban                    用户发送 IM 消息
      │                                │
      ▼                                ▼
┌──────────────┐              ┌──────────────┐
│ kanban :18810│              │ webim  :18820│
│              │              │              │
│ KanbanPlane  │              │ WebimPlane   │
│ ┌──────────┐ │              │ ┌──────────┐ │
│ │FSM 校验  │ │              │ │FSM 校验  │ │  ← 同一份 ISSUE_FSM
│ │Policy审批│ │              │ │Policy审批│ │  ← 各自的 Policy 集合
│ │决策记录  │ │              │ │决策记录  │ │  ← 各自的 DB
│ └──────────┘ │              │ └──────────┘ │
└──────┬───────┘              └──────┬───────┘
       │                             │
       └───────────┬─────────────────┘
                   ▼
          ┌────────────────┐
          │ gateway :18900 │
          │                │
          │ 访问控制        │
          │ 会话管理        │
          │ 消息交换        │
          │ (无业务决策)     │
          └───────┬────────┘
                  ▼
          ┌────────────────┐
          │ agent  :18800  │
          │                │
          │ 执行引擎        │
          │ (run/plan/     │
          │  cancel)       │
          │                │
          │ 状态守卫(兜底)  │
          │ SSE 事件流      │
          │ 执行数据        │
          └────────────────┘
```

---

## 分阶段实施

### Phase 1: 基础设施

**目标**：建立 shared 控制平面接口 + 声明式 FSM + Policy 框架

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建 | `shared/control_plane/__init__.py` | 共享包 |
| 新建 | `shared/control_plane/interfaces.py` | ControlPlaneBase ABC |
| 新建 | `shared/control_plane/state_machine.py` | 声明式 FSM 引擎 |
| 新建 | `shared/control_plane/issue_fsm.py` | Issue 状态转移声明 |
| 新建 | `shared/control_plane/policies.py` | Policy ABC + 通用策略 |
| 新建 | `shared/control_plane/decision.py` | DecisionRecord |
| 新建 | `shared/pyproject.toml` | 共享包的包描述 |

**验证**：纯单元测试，不涉及 HTTP。测试 FSM 全部合法/非法转移、Policy 逻辑。

### Phase 2: kanban Business Service

**目标**：新建 kanban 服务，web 前端改为连接 kanban 而非直连 agent

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建 | `kanban/` 整个模块 | kanban Business Service |
| 新建 | `kanban/src/mango_kanban/plane/kanban_plane.py` | KanbanPlane 实现 |
| 新建 | `kanban/src/mango_kanban/service/gateway_client.py` | 通过 gateway 访问 agent |
| 新建 | `kanban/src/mango_kanban/server/routes.py` | 对 web 暴露的 API |
| 新建 | `kanban/src/mango_kanban/db/migrations/001_init.sql` | decision_records 表 |
| 修改 | `web/vite.config.ts` | proxy 从 agent:18800 改为 kanban:18810 |
| 修改 | `gateway/src/mango_gateway/service/runtime_client.py` | 补全缺失的端点方法 |

**验证**：web → kanban → gateway → agent 全链路跑通。看板全部操作正常。decision_records 表有审计记录。

### Phase 3: gateway 精简 + webim 服务

**目标**：把 gateway 中的业务逻辑提取到 webim，gateway 回归纯网关

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建 | `webim/` 整个模块 | webim Business Service |
| 新建 | `webim/src/mango_webim/plane/webim_plane.py` | WebimPlane 实现 |
| 新建 | `webim/src/mango_webim/service/conversation.py` | 对话 → Issue 转换 |
| 修改 | `gateway/src/mango_gateway/service/gateway.py` | 剥离 `_route_message` 业务逻辑 |

**验证**：IM 消息 → webim → gateway → agent 全链路。gateway 不再包含 Issue 状态判断。

### Phase 4: Agent 执行反馈增强 + 策略建议

**目标**：agent 新增结构化反馈，BS 层新增策略分析

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建 | `shared/control_plane/proposal.py` | AgentProposal 数据结构 |
| 新建 | `agent/agent/classifier.py` | 错误类型分类 |
| 修改 | `agent/agent/runtime.py` | 新增 turn_report SSE 事件 |
| 新增 | `shared/control_plane/strategy.py` | StrategyAdvisor 基类 |
| 修改 | `kanban/src/mango_kanban/plane/kanban_plane.py` | 处理 Proposal |
| 修改 | `webim/src/mango_webim/plane/webim_plane.py` | 处理 Proposal |

### Phase 5: 自我评估 + 推理闭环

**目标**：agent 新增自我评估能力，BS 层新增评估结果驱动的决策

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建 | `agent/agent/assessment.py` | SelfAssessment |
| 新建 | `agent/skills/assess.py` | AssessmentSkill |
| 修改 | `agent/agent/runtime.py` | turn 成功后自我评估 |
| 修改 | 各 BS 的 Plane 实现 | 处理 self_assessment 事件 |

---

## 对现有代码的影响

### 不动的
- `agent/agent/runtime.py` — Phase 1-3 不改，Phase 4 新增事件
- `agent/server/routes.py` — 保持所有端点，状态守卫作为安全兜底
- `agent/skills/` — 保持现有 GenericSkill、PlanSkill
- `agent/db/` — 保持现有表结构
- `web/src/` — Phase 2 仅改 vite proxy 目标地址，API 路径不变

### 精简的
- `gateway/src/mango_gateway/service/gateway.py` — Phase 3 剥离业务逻辑

### 新建的
- `shared/control_plane/` — 控制平面接口和基础设施
- `kanban/` — 看板 Business Service
- `webim/` — IM Business Service
