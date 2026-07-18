# cc-connect Bridge PoC 设计

## 目标

在不修改 `cc-connect` 的前提下，让 `issue-overseer/gateway` 能作为 cc-connect Bridge adapter 投递一条任务消息、接收最终回复并持久化会话消息。原有 `agent/` 运行时不参与这个新链路。

## 范围

- 新增一个只负责 Bridge WebSocket 协议的客户端；连接、注册、投递和按 `reply_ctx` 等待回复。
- Gateway 新增最小任务端点，创建或复用本地会话，保存 user/assistant 两条消息。
- 仅保留 `queued`、`completed`、`failed` 三种结果语义；不迁移原 Issue FSM、步骤日志、PR 字段或 SSE 代理。

## 非目标

- 不改动 `cc-connect`、WisCode CLI 或其配置格式。
- 不在本步骤删除现有 Runtime API；它仅保留为旧接口，待 PoC 验收后再移除。
- 不实现任务取消、工具级日志和断线后的自动恢复。

## 数据流

`POST /api/gateway/cc-connect/messages` 创建本地 session 并保存用户消息。Bridge 客户端用 `issue-overseer:{session-id}` 作为 session key、唯一 reply context 发送 `message` 帧。cc-connect 将该消息转给配置为 `wiscode` 的 Agent；收到同 reply context 的 `reply` 后，Gateway 保存 assistant 消息并返回结果。超时和连接错误返回明确失败。

## 接口边界

- `CCConnectBridgeClient.send(session_key, content, timeout)`：对 Gateway 提供单次请求/响应接口。
- 客户端内部独占 WebSocket 协议和 pending reply 路由；Gateway 不依赖 cc-connect 的帧格式。
- 配置使用 `[cc_connect]`：`url`、`token`、`platform`、`project`、`timeout`。

## 验收

1. 客户端测试证明 register 帧、message 帧、reply 匹配和超时语义正确。
2. Gateway 测试证明请求会持久化 user/assistant 消息，并把 Bridge 结果返回给 API。
3. 现有 Gateway 测试仍可通过；cc-connect 工作区零改动。
