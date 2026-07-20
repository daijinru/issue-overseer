# cc-connect 恢复脚本设计

## 目标

在 Issue Overseer 项目根目录提供 `recover-cc-connect.sh`，用于恢复本机 cc-connect Bridge 因残留进程占用配置锁、但未监听端口而导致的 API 503。

## 范围

- 使用 cc-connect 自带的 `daemon` 命令管理当前用户的 LaunchAgent。
- 检查 Bridge 端口 `9810` 与管理端口 `9820`。
- 仅当 Bridge 未监听时，检查 `~/.cc-connect/.config.toml.lock` 的占用者。
- 仅在该占用者确实是 `cc-connect` 进程且未监听 Bridge 端口时，先发送 `SIGTERM`，短暂等待后再发送 `SIGKILL`。
- 启动或重启 cc-connect 守护服务，并等待两个端口恢复监听。
- 通过明确的成功、失败及人工干预提示返回状态码。

## 非目标

- 不修改 cc-connect 源码、配置文件或 Issue Overseer 配置。
- 不启动、停止或检查 Issue Overseer 后端的 `18800` 端口，避免把后端未启动误认为恢复失败。
- 不打印或写入 Bridge token、管理 token 或其他凭据。

## 实现

脚本将解析自身所在目录以定位项目，但所有 cc-connect 状态均来自用户目录和 `cc-connect` CLI。它优先在 `PATH` 中查找 `cc-connect`，并回退到 `~/.local/bin/cc-connect`。

端口检查通过 `lsof` 执行。若 `9810` 与 `9820` 都已监听，脚本直接成功退出。否则脚本从锁文件读取 PID，并通过 `ps` 验证其命令名包含 `cc-connect`；不匹配时拒绝结束进程并失败退出。验证通过后，脚本只终止这个单独 PID，随后执行 `cc-connect daemon start`，必要时执行 `cc-connect daemon restart`。

脚本最多轮询 15 秒。成功条件是 9810 和 9820 都处于监听状态；失败时打印守护进程状态和下一步建议。

## 验证

- 使用 `bash -n recover-cc-connect.sh` 验证 shell 语法。
- 在服务已健康时运行脚本，确认它不结束进程且返回成功。
- 在停掉 Bridge 的受控测试环境运行，确认脚本能启动守护服务并使两个端口恢复监听。
- 确认脚本文本和输出中不包含 token 值。
