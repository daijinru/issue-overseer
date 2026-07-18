# cc-connect 项目驱动的 Issue

## 目标

将 issue-overseer 收敛为 cc-connect 的轻量任务入口和结果查看器。cc-connect 项目是唯一的 Agent 定义：它决定工作目录、权限、WisCode 可执行文件、模型供应商和项目内 `.claude` 配置。

issue-overseer 不再启动 OpenCode、不管理 CLI 路径、不维护本地 Git/PR/Spec/多轮重试逻辑。

## 用户界面

### 新建 Issue

表单只保留：

- **任务目标**：必填，多行文本。
- **Agent**：必填，下拉项来自 cc-connect Bridge 的项目列表；界面展示项目名。

移除标题、描述拆分、目录选择、优先级及固定 `wiscode` 选项。任务目标作为发送给 cc-connect 的内容。

### Issue 详情

详情面板只展示：选中的项目、状态、创建/开始/结束时间，以及 cc-connect 返回的结果或错误。结果按 Markdown 渲染；不展示本地执行步骤、Git diff、PR、Spec、轮次和重试记录。

## 状态与数据

Issue 状态仅有：

- `pending`：已创建，尚未启动。
- `running`：Bridge 请求已提交，等待 cc-connect 最终回复。
- `finished`：请求已结束。

`finished` 不区分状态枚举；通过 `outcome` 字段记录 `success` 或 `error`，并保留 `result` 或 `error_message`。历史 Issue 的旧状态在读取时映射到最接近的新状态，迁移不删除旧数据。

## 后端与 cc-connect

新增一个面向 UI 的项目列表接口。它连接配置的 cc-connect Bridge、完成 register，并读取 capabilities snapshot 中的 `projects`；返回项目名数组并短时缓存。

执行接口将选中的项目写入 Bridge `message.project`，并使用稳定的 Issue session key。cc-connect 根据项目定位自己的 Engine，再自行发现和启动 WisCode；issue-overseer 不传 CLI path，也不注入 Anthropic 凭据。

Bridge token 仅是后端到后端的可选认证配置：

- 配置了 token 时，以请求头发送。
- 未配置 token 时允许无 token 建连，由 cc-connect 自己决定是否接受。
- 不在浏览器、Issue 数据库或仓库配置中存储 token。

## 错误与并发

- 项目列表不可用时，表单展示“无法读取 cc-connect 项目”，禁止创建。
- 项目在执行前被删除时，Issue 直接进入 `finished/error` 并显示 Bridge 错误。
- 同一 Issue 只能从 `pending` 启动一次；运行中的 Issue 不允许重复启动。
- WebSocket 断开、超时和 cc-connect error frame 都转为 `finished/error`，详情保留可读错误信息。

## 验证

- 单测：项目列表解析、指定 `message.project`、无 token 连接、Bridge 错误到 `finished/error` 的转换、重复启动拒绝。
- API 测试：新建表单所需项目列表、简化 Issue 创建与执行。
- 前端构建与后端完整测试。
- 手工验收：选择一个 cc-connect 项目，新建并启动任务；确认 cc-connect 使用该项目工作目录并且详情显示最终回复。
