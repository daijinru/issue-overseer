# cc-connect Bridge PoC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 issue-overseer Gateway 通过 cc-connect Bridge 向 WisCode 投递最小任务并接收最终文本回复。

**Architecture:** 在 Gateway 内新增一个隔离的 WebSocket Bridge client。它负责 cc-connect 的 register/message/reply 协议和请求关联；Gateway 只调用 `send`，持久化结果，不再调用旧 Agent Runtime。

**Tech Stack:** Python 3.12、FastAPI、httpx、websockets、pytest。

## Global Constraints

- 不修改 `cc-connect` 任何文件。
- 保留现有 Runtime 路由，新增接口独立验证后再删除旧链路。
- 不迁移 Issue FSM、执行步骤、PR 和 SSE 功能。

---

### Task 1: Bridge 协议客户端

**Files:**
- Create: `gateway/src/mango_gateway/service/cc_connect_client.py`
- Create: `gateway/tests/test_cc_connect_client.py`
- Modify: `gateway/pyproject.toml`

- [x] **Step 1: Write the failing protocol tests**

测试模拟 WebSocket，断言连接后先发送 `register`，`send` 发送带唯一 `reply_ctx` 的 `message`，且只接受同一 reply context 的 `reply`。

- [x] **Step 2: Run the test to verify it fails**

Run: `UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest gateway/tests/test_cc_connect_client.py -v`

- [x] **Step 3: Write the minimal client**

实现 `CCConnectBridgeClient(url, token, platform, project, timeout)` 和 `async send(session_key, content, timeout=None) -> str`；仅支持文本消息，超时/错误抛出 `CCConnectBridgeError`。

- [x] **Step 4: Run the client tests**

Run: `UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest gateway/tests/test_cc_connect_client.py -v`

### Task 2: Gateway 最小任务接口

**Files:**
- Modify: `gateway/src/mango_gateway/config.py`
- Modify: `gateway/src/mango_gateway/models.py`
- Modify: `gateway/src/mango_gateway/service/gateway.py`
- Modify: `gateway/src/mango_gateway/server/routes.py`
- Modify: `gateway/tests/test_gateway_service.py`

- [x] **Step 1: Write failing Gateway tests**

测试 `send_cc_connect_message` 创建本地 session、保存 user/assistant 消息，并在 Bridge 出错时不伪造成功。

- [x] **Step 2: Run the focused test to verify it fails**

Run: `UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest gateway/tests/test_gateway_service.py -k cc_connect -v`

- [x] **Step 3: Implement the minimal Gateway method and route**

新增 `POST /api/gateway/cc-connect/messages`。输入复用 `GatewayMessageSend` 的 content/session/source 字段；响应仅含 session id、message id 和 result。

- [x] **Step 4: Run focused and regression tests**

Run: `UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest gateway/tests -v`
