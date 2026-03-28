# Gateway Service 设计方案（Roadmap 1）

## Context

**问题**：当前 Mango 是 Issue-centric 的系统，只有 Web UI 通过 REST API 创建 Issue 并触发执行。缺少一个面向外部系统的会话式接入层——外部消息源（如 IM 机器人、CLI 工具、第三方平台 Webhook）无法以对话形式与 Agent Runtime 交互。

**目标**：实现一个**独立的 Gateway Service**，提供：
1. **会话管理** — 创建/管理来自外部的会话，会话绑定到 Agent Runtime 的 Issue
2. **消息收发** — 外部系统发消息 → Gateway 路由到 Agent Runtime → 等待结果 → 返回回复
3. **网关入口** — 统一的外部接入点，屏蔽内部 Issue/Runtime 细节

**关键约束**：
- Gateway Service 是**独立进程**，有自己的目录、数据库、配置、启动脚本
- Agent Runtime 可以是**分布式部署**的多个实例
- Gateway 通过 **HTTP REST API** 与 Agent Runtime 通信（调用 Runtime 现有的 `/api/*` 接口）

---

## 架构概览

```
外部消息源 (IM Bot / CLI / Webhook / 第三方平台)
   ↓ POST /api/gateway/messages
┌──────────────────────────────────────────────────┐
│  Gateway Service（独立进程，端口 18900）             │
│  ┌──────────────┐                                │
│  │ FastAPI App   │                               │
│  │ ├── routes    │                               │
│  │ └── SSE proxy │                               │
│  └──────┬───────┘                                │
│         │                                        │
│  ┌──────┴────────────────────────────────────┐   │
│  │ GatewayService                             │   │
│  │ ├── SessionManager (会话生命周期)            │   │
│  │ ├── MessageRouter  (消息 → Issue 路由)      │   │
│  │ └── RuntimeClient  (HTTP 调用 Runtime API)  │   │
│  └──────┬────────────────────────────────────┘   │
│         │                                        │
│  ┌──────┴───────┐                                │
│  │ SQLite (独立)  │  sessions + messages          │
│  └──────────────┘                                │
└─────────┬────────────────────────────────────────┘
          │ HTTP REST API
          │ (POST /api/issues, POST /api/issues/{id}/run, ...)
          │ (GET /api/issues/{id}/stream — SSE 转发)
          ↓
┌──────────────────────────────────────────────────┐
│  Agent Runtime（可分布式，端口 18800）               │
│  现有系统，不改动                                   │
└──────────────────────────────────────────────────┘
```

### 关键设计决策

| # | 决策 | 理由 |
|---|------|------|
| 1 | Gateway 是独立服务，独立目录 `gateway/` | Agent Runtime 可分布式部署，不能耦合到同一进程 |
| 2 | 通过 HTTP REST API 调用 Runtime | 复用 Runtime 现有的 18 个 REST 端点，零改动 |
| 3 | 同步等待 = SSE 代理消费 Runtime 的 `/stream` | 订阅 Runtime 的 SSE 流等待终态事件 |
| 4 | 独立 SQLite 存 sessions + messages | Gateway 只管会话，不管 Issue 执行细节 |
| 5 | Session ↔ Issue 是 N:1 时序关系 | 一个 Session 可依次关联多个 Issue，任意时刻最多一个活跃 |
| 6 | 同步和异步两种模式 | `wait=true` 阻塞等待；`wait=false` 立即返回 + SSE |
| 7 | Python + FastAPI 技术栈 | 与 Runtime 一致，降低维护成本 |

---

## 项目结构

```
issue-overseer/
├── src/mango/           # 现有 Agent Runtime（不改动）
├── gateway/             # ★ 新增：Gateway Service 独立目录
│   ├── pyproject.toml   # 独立的 Python 包定义
│   ├── gateway.toml     # Gateway 专用配置
│   ├── start-gateway.sh # 启动脚本
│   └── src/
│       └── mango_gateway/
│           ├── __init__.py
│           ├── __main__.py          # 入口：uvicorn 启动
│           ├── main.py              # uvicorn runner
│           ├── config.py            # pydantic-settings 配置
│           ├── models.py            # Session/Message 等 Pydantic 模型
│           ├── server/
│           │   ├── __init__.py
│           │   ├── app.py           # FastAPI 工厂 + lifespan
│           │   └── routes.py        # Gateway API 端点
│           ├── service/
│           │   ├── __init__.py
│           │   ├── gateway.py       # GatewayService 核心逻辑
│           │   └── runtime_client.py # HTTP 客户端调用 Runtime API
│           └── db/
│               ├── __init__.py
│               ├── connection.py    # aiosqlite 连接管理
│               ├── repos.py         # SessionRepo + MessageRepo
│               └── migrations/
│                   └── 001_init.sql # sessions + messages 表
├── web/                 # 现有前端（不改动）
├── tests/               # 现有 Runtime 测试
└── gateway/tests/       # Gateway 测试
    ├── conftest.py
    ├── test_gateway_service.py
    ├── test_runtime_client.py
    └── test_api.py
```

---

## 数据模型

### Gateway 自有 DB（`gateway/data/gateway.db`）

#### `sessions` 表
```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL DEFAULT 'api',
    source_id TEXT,
    current_issue_id TEXT,              -- Runtime 侧的 Issue ID（无 FK，跨服务引用）
    status TEXT NOT NULL DEFAULT 'active',
    runtime_url TEXT NOT NULL,          -- 关联的 Runtime 地址
    metadata TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    closed_at TEXT
);
CREATE INDEX idx_sessions_source ON sessions(source, source_id);
CREATE INDEX idx_sessions_status ON sessions(status);
```

#### `messages` 表
```sql
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,                  -- user / assistant / system
    content TEXT NOT NULL,
    issue_id TEXT,                       -- Runtime 侧的 Issue ID
    metadata TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_messages_session ON messages(session_id);
```

### Pydantic Models（`gateway/src/mango_gateway/models.py`）

```python
from enum import Enum
from pydantic import BaseModel


class SessionStatus(str, Enum):
    active = "active"
    closed = "closed"
    expired = "expired"


class MessageRole(str, Enum):
    user = "user"
    assistant = "assistant"
    system = "system"


class Session(BaseModel):
    id: str
    source: str = "api"
    source_id: str | None = None
    current_issue_id: str | None = None
    status: SessionStatus = SessionStatus.active
    runtime_url: str = ""
    metadata: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    closed_at: str | None = None


class Message(BaseModel):
    id: int
    session_id: str
    role: MessageRole
    content: str
    issue_id: str | None = None
    metadata: str | None = None
    created_at: str | None = None


# ── API 请求模型 ──

class SessionCreate(BaseModel):
    source: str = "api"
    source_id: str | None = None
    metadata: dict | None = None


class GatewayMessageSend(BaseModel):
    content: str                        # 消息内容
    session_id: str | None = None       # 可选，不传则自动创建 Session
    source: str = "api"
    source_id: str | None = None
    wait: bool = False                  # true=同步等待结果, false=立即返回
    timeout: int = 1800                 # wait=true 时的超时（秒）
    workspace: str | None = None        # Issue 的工作目录
    priority: str = "medium"


class GatewayReply(BaseModel):
    session_id: str
    message_id: int
    issue_id: str
    issue_status: str
    result: str | None = None
    pr_url: str | None = None
    failure_reason: str | None = None
```

---

## 配置

### `gateway/gateway.toml`

```toml
[server]
port = 18900                            # Gateway 端口（与 Runtime 18800 区分）
host = "0.0.0.0"

[runtime]
url = "http://localhost:18800"          # Agent Runtime 地址
timeout = 30                            # HTTP 请求超时（秒）
# 未来分布式场景可扩展为列表：
# urls = ["http://runtime-1:18800", "http://runtime-2:18800"]

[session]
timeout_hours = 24                      # 会话过期时间
cleanup_interval_minutes = 60           # 过期清理间隔

[gateway]
max_wait_timeout = 1800                 # 同步等待最大超时（秒）

[database]
path = "./data/gateway.db"
```

### `gateway/src/mango_gateway/config.py`

```python
from pydantic import BaseModel
from pydantic_settings import BaseSettings, TomlConfigSettingsSource


class ServerConfig(BaseModel):
    port: int = 18900
    host: str = "0.0.0.0"


class RuntimeConfig(BaseModel):
    url: str = "http://localhost:18800"
    timeout: int = 30


class SessionConfig(BaseModel):
    timeout_hours: int = 24
    cleanup_interval_minutes: int = 60


class GatewayConfig(BaseModel):
    max_wait_timeout: int = 1800


class DatabaseConfig(BaseModel):
    path: str = "./data/gateway.db"


class Settings(BaseSettings):
    server: ServerConfig = ServerConfig()
    runtime: RuntimeConfig = RuntimeConfig()
    session: SessionConfig = SessionConfig()
    gateway: GatewayConfig = GatewayConfig()
    database: DatabaseConfig = DatabaseConfig()

    @classmethod
    def settings_customise_sources(cls, settings_cls, **kwargs):
        return (TomlConfigSettingsSource(settings_cls, toml_file="gateway.toml"),)
```

---

## RuntimeClient — HTTP 客户端

### `gateway/src/mango_gateway/service/runtime_client.py`

Gateway 通过 HTTP 调用 Agent Runtime 的现有 REST API：

```python
import httpx

class RuntimeClient:
    """HTTP 客户端，封装对 Agent Runtime REST API 的调用。"""

    def __init__(self, base_url: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ── Issue 操作（映射 Runtime 现有端点）──

    async def create_issue(self, title: str, description: str = "",
                           workspace: str | None = None,
                           priority: str = "medium") -> dict:
        """POST /api/issues"""
        client = await self._get_client()
        payload = {"title": title, "description": description, "priority": priority}
        if workspace:
            payload["workspace"] = workspace
        resp = await client.post("/api/issues", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def run_issue(self, issue_id: str) -> dict:
        """POST /api/issues/{id}/run"""
        client = await self._get_client()
        resp = await client.post(f"/api/issues/{issue_id}/run")
        resp.raise_for_status()
        return resp.json()

    async def retry_issue(self, issue_id: str, human_instruction: str) -> dict:
        """POST /api/issues/{id}/retry"""
        client = await self._get_client()
        resp = await client.post(
            f"/api/issues/{issue_id}/retry",
            json={"human_instruction": human_instruction},
        )
        resp.raise_for_status()
        return resp.json()

    async def get_issue(self, issue_id: str) -> dict:
        """GET /api/issues/{id}"""
        client = await self._get_client()
        resp = await client.get(f"/api/issues/{issue_id}")
        resp.raise_for_status()
        return resp.json()

    async def cancel_issue(self, issue_id: str) -> dict:
        """POST /api/issues/{id}/cancel"""
        client = await self._get_client()
        resp = await client.post(f"/api/issues/{issue_id}/cancel")
        resp.raise_for_status()
        return resp.json()

    async def stream_issue_events(self, issue_id: str):
        """
        GET /api/issues/{id}/stream — SSE 事件流消费。
        返回异步迭代器，逐个 yield SSE 事件。
        用于 wait=true 模式下等待 task_end 事件。
        """
        client = await self._get_client()
        async with client.stream(
            "GET", f"/api/issues/{issue_id}/stream"
        ) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    yield json.loads(line[6:])
                elif line.startswith("event: "):
                    # 保留 event type 信息
                    pass

    async def get_issue_executions(self, issue_id: str) -> list[dict]:
        """GET /api/issues/{id}/executions"""
        client = await self._get_client()
        resp = await client.get(f"/api/issues/{issue_id}/executions")
        resp.raise_for_status()
        return resp.json()

    async def health_check(self) -> bool:
        """GET /api/health"""
        try:
            client = await self._get_client()
            resp = await client.get("/api/health")
            return resp.status_code == 200
        except Exception:
            return False
```

---

## GatewayService — 核心逻辑

### `gateway/src/mango_gateway/service/gateway.py`

```python
class GatewayService:
    """网关服务：会话管理 + 消息路由 + 结果等待。"""

    def __init__(self, runtime_client: RuntimeClient, settings: Settings):
        self.runtime = runtime_client
        self.settings = settings
        self.session_repo = SessionRepo()
        self.message_repo = MessageRepo()

    async def create_session(self, data: SessionCreate) -> Session:
        """创建新会话。"""
        return await self.session_repo.create(data, self.settings.runtime.url)

    async def get_session(self, session_id: str) -> Session | None:
        """获取会话。"""
        return await self.session_repo.get(session_id)

    async def close_session(self, session_id: str) -> Session:
        """关闭会话。"""
        await self.session_repo.close(session_id)
        return await self.session_repo.get(session_id)

    async def send_message(self, data: GatewayMessageSend) -> GatewayReply:
        """
        核心方法：接收外部消息，路由到 Agent Runtime。

        流程：
        1. 获取或创建 Session
        2. 持久化 user 消息
        3. 判断路由策略（根据 Session 当前 Issue 状态）
        4. 调用 Runtime REST API（创建 Issue / retry / etc.）
        5. 如果 wait=true → 消费 Runtime SSE 流等待终态
        6. 持久化 assistant 回复消息并返回
        """
        # 1. 获取或创建 Session
        session = await self._resolve_session(data)

        # 2. 持久化 user 消息
        user_msg = await self.message_repo.create(
            session_id=session.id,
            role=MessageRole.user,
            content=data.content,
        )

        # 3. 路由决策
        issue_id = await self._route_message(session, data)

        # 4. 更新 session.current_issue_id
        await self.session_repo.update_fields(
            session.id, current_issue_id=issue_id
        )

        # 5. 等待结果（如果 wait=true）
        result_data = None
        if data.wait:
            timeout = min(data.timeout, self.settings.gateway.max_wait_timeout)
            result_data = await self._wait_for_result(issue_id, timeout)

        # 6. 构造回复
        issue = await self.runtime.get_issue(issue_id)
        reply_content = self._format_reply(issue, result_data)

        assistant_msg = await self.message_repo.create(
            session_id=session.id,
            role=MessageRole.assistant,
            content=reply_content,
            issue_id=issue_id,
        )

        return GatewayReply(
            session_id=session.id,
            message_id=assistant_msg.id,
            issue_id=issue_id,
            issue_status=issue.get("status", "unknown"),
            result=result_data.get("result") if result_data else None,
            pr_url=issue.get("pr_url"),
            failure_reason=issue.get("failure_reason"),
        )

    async def _resolve_session(self, data: GatewayMessageSend) -> Session:
        """获取已有 Session 或创建新 Session。"""
        if data.session_id:
            session = await self.session_repo.get(data.session_id)
            if session is None:
                raise ValueError(f"Session {data.session_id} not found")
            if session.status != SessionStatus.active:
                raise ValueError(f"Session {data.session_id} is {session.status}")
            return session
        # 自动创建
        return await self.session_repo.create(
            SessionCreate(source=data.source, source_id=data.source_id),
            self.settings.runtime.url,
        )

    async def _route_message(self, session: Session, data: GatewayMessageSend) -> str:
        """
        路由决策：根据 Session 当前 Issue 状态决定行为。

        返回 issue_id。
        """
        if session.current_issue_id:
            # 查询 Runtime 侧 Issue 的当前状态
            try:
                issue = await self.runtime.get_issue(session.current_issue_id)
                status = issue.get("status")
            except Exception:
                # Issue 不存在或 Runtime 不可达 → 当作无 Issue
                status = None

            if status == "waiting_human":
                # 作为 retry instruction
                await self.runtime.retry_issue(session.current_issue_id, data.content)
                return session.current_issue_id

            elif status in ("running", "planning"):
                raise RuntimeError("当前任务正在执行中，请等待完成后再发送新消息")

            # status in (done, review, cancelled, open, None) → 创建新 Issue

        # 创建新 Issue
        issue = await self.runtime.create_issue(
            title=data.content[:100],           # 取前 100 字符作为标题
            description=data.content,
            workspace=data.workspace,
            priority=data.priority,
        )
        issue_id = issue["id"]

        # 触发执行
        await self.runtime.run_issue(issue_id)
        return issue_id

    async def _wait_for_result(self, issue_id: str, timeout: int) -> dict:
        """
        消费 Runtime 的 SSE 流，等待终态事件（task_end / task_cancelled）。

        这是 Gateway 等待 Runtime 执行结果的核心机制：
        - 连接到 Runtime 的 GET /api/issues/{id}/stream
        - 逐个消费 SSE 事件
        - 收到 task_end 或 task_cancelled 时返回事件数据
        """
        import asyncio
        try:
            async with asyncio.timeout(timeout):
                async for event in self.runtime.stream_issue_events(issue_id):
                    event_type = event.get("type")
                    if event_type in ("task_end", "task_cancelled"):
                        return event.get("data", {})
        except asyncio.TimeoutError:
            return {"success": False, "failure_reason": "Gateway 等待超时"}
        return {"success": False, "failure_reason": "SSE 流意外关闭"}

    def _format_reply(self, issue: dict, result_data: dict | None) -> str:
        """将执行结果格式化为人类可读的回复文本。"""
        status = issue.get("status", "unknown")
        if result_data and result_data.get("success"):
            pr_url = issue.get("pr_url")
            if pr_url:
                return f"任务完成，PR 已创建：{pr_url}"
            return "任务完成。"
        elif result_data:
            reason = result_data.get("failure_reason", "未知原因")
            return f"任务执行失败：{reason}\n你可以发送补充说明来重试。"
        else:
            return f"任务已提交，当前状态：{status}"

    async def get_session_messages(self, session_id: str) -> list[Message]:
        return await self.message_repo.list_by_session(session_id)

    async def cleanup_expired_sessions(self) -> int:
        """清理过期会话。"""
        expired = await self.session_repo.list_expired(
            self.settings.session.timeout_hours
        )
        count = 0
        for session in expired:
            await self.session_repo.update_fields(
                session.id, status="expired"
            )
            count += 1
        return count

    async def run_cleanup_loop(self) -> None:
        """后台清理循环。"""
        import asyncio
        interval = self.settings.session.cleanup_interval_minutes * 60
        while True:
            await asyncio.sleep(interval)
            try:
                count = await self.cleanup_expired_sessions()
                if count > 0:
                    logger.info("Cleaned up %d expired sessions", count)
            except Exception:
                logger.exception("Session cleanup failed")
```

---

## API 端点

### `gateway/src/mango_gateway/server/routes.py`

| Method | Path | 描述 | 返回 |
|--------|------|------|------|
| `GET` | `/api/health` | 健康检查（含 Runtime 连通性检测） | `{status, runtime_ok}` |
| `POST` | `/api/gateway/messages` | **核心**：发送消息，路由到 Runtime | `GatewayReply` |
| `POST` | `/api/gateway/sessions` | 创建会话 | `Session` |
| `GET` | `/api/gateway/sessions/{id}` | 获取会话详情 | `Session` |
| `POST` | `/api/gateway/sessions/{id}/close` | 关闭会话 | `Session` |
| `GET` | `/api/gateway/sessions/{id}/messages` | 获取会话消息历史 | `list[Message]` |
| `GET` | `/api/gateway/sessions/{id}/stream` | SSE 流（代理转发 Runtime 的 Issue SSE） | SSE |

### 核心端点详解：`POST /api/gateway/messages`

```
请求：
{
    "content": "帮我实现一个用户登录功能",
    "session_id": "sess_abc123",          // 可选，不传则自动创建
    "wait": true,                          // 同步等待结果
    "timeout": 600,
    "workspace": "/path/to/repo",
    "priority": "high"
}

响应（wait=true）：
{
    "session_id": "sess_abc123",
    "message_id": 42,
    "issue_id": "issue_xyz",
    "issue_status": "review",
    "result": "已完成用户登录功能的实现...",
    "pr_url": "https://github.com/user/repo/pull/123",
    "failure_reason": null
}

响应（wait=false）：
{
    "session_id": "sess_abc123",
    "message_id": 41,
    "issue_id": "issue_xyz",
    "issue_status": "running",
    "result": null,
    "pr_url": null,
    "failure_reason": null
}
```

### 消息路由逻辑

```
收到消息
  ├── Session 无 current_issue
  │     → POST /api/issues 创建 Issue（title=content[:100], description=content）
  │     → POST /api/issues/{id}/run 触发执行
  │     → 更新 session.current_issue_id
  │
  ├── Session 有 current_issue，Runtime 返回 status = waiting_human
  │     → POST /api/issues/{id}/retry 传 human_instruction=content
  │
  ├── Session 有 current_issue，status ∈ {done, review, cancelled}
  │     → 解绑旧 Issue，创建新 Issue（同上）
  │
  └── Session 有 current_issue，status ∈ {running, planning}
        → 返回 409: "当前任务正在执行中"
```

### SSE 代理端点：`GET /api/gateway/sessions/{id}/stream`

```python
@router.get("/api/gateway/sessions/{session_id}/stream")
async def stream_session(session_id: str, request: Request):
    """SSE 代理：将 Runtime 的 Issue SSE 流转发给 Gateway 客户端。"""
    gateway = _get_gateway(request)
    session = await gateway.get_session(session_id)
    if session is None or session.current_issue_id is None:
        raise HTTPException(404, "No active issue for this session")

    async def proxy_generator():
        async for event in gateway.runtime.stream_issue_events(
            session.current_issue_id
        ):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        proxy_generator(),
        media_type="text/event-stream",
    )
```

---

## 文件清单

### 新增文件（16 个）

| # | 文件 | 说明 |
|---|------|------|
| 1 | `gateway/pyproject.toml` | Python 包定义（依赖：fastapi, uvicorn, aiosqlite, pydantic-settings, httpx） |
| 2 | `gateway/gateway.toml` | 配置文件 |
| 3 | `gateway/start-gateway.sh` | 启动脚本：`exec uv run python -m mango_gateway` |
| 4 | `gateway/src/mango_gateway/__init__.py` | 包初始化 |
| 5 | `gateway/src/mango_gateway/__main__.py` | `python -m mango_gateway` 入口 |
| 6 | `gateway/src/mango_gateway/main.py` | uvicorn runner |
| 7 | `gateway/src/mango_gateway/config.py` | pydantic-settings 配置 |
| 8 | `gateway/src/mango_gateway/models.py` | Pydantic 模型 |
| 9 | `gateway/src/mango_gateway/server/__init__.py` | 包初始化 |
| 10 | `gateway/src/mango_gateway/server/app.py` | FastAPI 工厂 + lifespan |
| 11 | `gateway/src/mango_gateway/server/routes.py` | API 端点 |
| 12 | `gateway/src/mango_gateway/service/__init__.py` | 包初始化 |
| 13 | `gateway/src/mango_gateway/service/gateway.py` | GatewayService 核心 |
| 14 | `gateway/src/mango_gateway/service/runtime_client.py` | HTTP 客户端 |
| 15 | `gateway/src/mango_gateway/db/__init__.py` | 包初始化 |
| 16 | `gateway/src/mango_gateway/db/connection.py` | aiosqlite 连接 |
| 17 | `gateway/src/mango_gateway/db/repos.py` | SessionRepo + MessageRepo |
| 18 | `gateway/src/mango_gateway/db/migrations/001_init.sql` | sessions + messages 表 |

### 改动的文件

**无。** Gateway 是完全独立的服务，不改动 Agent Runtime 的任何文件。

---

## 实施步骤

### 第一步：项目骨架 + 配置 + DB
- 创建 `gateway/` 目录结构
- `pyproject.toml`（依赖：fastapi, uvicorn, aiosqlite, pydantic-settings, httpx）
- `gateway.toml` 配置
- `config.py` 配置加载
- `db/connection.py` + `db/migrations/001_init.sql`
- `models.py` 所有 Pydantic 模型
- `db/repos.py` SessionRepo + MessageRepo

### 第二步：RuntimeClient
- 实现 `service/runtime_client.py`
- 封装对 Runtime 所有 REST API 的 HTTP 调用
- SSE 流消费方法 `stream_issue_events()`

### 第三步：GatewayService
- 实现 `service/gateway.py`
- 核心 `send_message()` 方法 + 路由决策逻辑
- `_wait_for_result()` 通过 SSE 代理等待
- 会话清理 `cleanup_expired_sessions()` + `run_cleanup_loop()`

### 第四步：API 端点 + 应用集成
- `server/routes.py` — 7 个端点
- `server/app.py` — FastAPI 工厂 + lifespan（初始化 RuntimeClient + GatewayService）
- `__main__.py` + `main.py` — 启动入口
- `start-gateway.sh`

### 第五步：测试
- `RuntimeClient` 单元测试（mock HTTP 响应）
- `GatewayService` 单元测试（mock RuntimeClient）
- API 集成测试（httpx TestClient）

---

## 验证方案

### 前置条件
```bash
# 确保 Agent Runtime 运行中
cd issue-overseer && uv run python -m mango
# → http://localhost:18800
```

### 启动 Gateway
```bash
cd issue-overseer/gateway && uv run python -m mango_gateway
# → http://localhost:18900
```

### 端到端测试

```bash
# 1. 健康检查（含 Runtime 连通性）
curl http://localhost:18900/api/health

# 2. 创建会话
curl -X POST http://localhost:18900/api/gateway/sessions \
  -H 'Content-Type: application/json' \
  -d '{"source": "cli"}'

# 3. 发送消息（异步）
curl -X POST http://localhost:18900/api/gateway/messages \
  -H 'Content-Type: application/json' \
  -d '{
    "content": "帮我写一个 hello world 函数",
    "workspace": "/tmp/test-repo"
  }'

# 4. 查看会话消息
curl http://localhost:18900/api/gateway/sessions/{session_id}/messages

# 5. 同步等待模式
curl -X POST http://localhost:18900/api/gateway/messages \
  -H 'Content-Type: application/json' \
  -d '{
    "content": "帮我修复 test 失败",
    "session_id": "...",
    "wait": true,
    "timeout": 300
  }'

# 6. 追加指令（当 Issue 在 waiting_human 状态）
curl -X POST http://localhost:18900/api/gateway/messages \
  -H 'Content-Type: application/json' \
  -d '{
    "content": "请检查 import 路径是否正确",
    "session_id": "..."
  }'
```

### 自动化测试
```bash
cd gateway && uv run pytest tests/ -v
```

---

## 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| Runtime 不可达 | Gateway 无法创建/执行 Issue | `health_check()` 检测 + 友好错误提示 |
| SSE 流断连（wait=true 模式） | 等待永远不会结束 | `asyncio.timeout` 兜底 + 超时返回失败 |
| Session 积累过多 | SQLite 膨胀 | 定期清理 + `session_timeout_hours` 配置 |
| Runtime API 变更 | RuntimeClient 调用失败 | RuntimeClient 集中封装，修改点唯一 |

---

## 推迟到 Roadmap 2

| 方向 | 前提 |
|------|------|
| 多 Runtime 负载均衡 | 需要服务发现机制 |
| 认证 / API Key | Gateway 对外开放时必要 |
| WebSocket 双向通信 | SSE 代理不够时 |
| 消息上下文注入 Runtime | 多轮对话时将历史消息注入 TurnContext |
| 前端 Gateway 管理面板 | Gateway 运维可视化 |
