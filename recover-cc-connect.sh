#!/usr/bin/env bash
# Restore the local cc-connect Bridge when a stale process holds its lock.
set -euo pipefail

bridge_port=9810
management_port=9820
lock_file="$HOME/.cc-connect/.config.toml.lock"
wait_seconds=15

usage() {
  cat <<'EOF'
用法：./recover-cc-connect.sh

恢复本机 cc-connect Bridge：检查 9810/9820，清理占用配置锁但未监听
Bridge 的残留 cc-connect 进程，然后启动 cc-connect 守护服务。
EOF
}

is_listening() {
  local port="$1"
  lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
}

is_healthy() {
  is_listening "$bridge_port" && is_listening "$management_port"
}

find_cc_connect() {
  if [[ -n "${CC_CONNECT_BIN:-}" && -x "$CC_CONNECT_BIN" ]]; then
    printf '%s\n' "$CC_CONNECT_BIN"
    return
  fi
  if command -v cc-connect >/dev/null 2>&1; then
    command -v cc-connect
    return
  fi
  if [[ -x "$HOME/.local/bin/cc-connect" ]]; then
    printf '%s\n' "$HOME/.local/bin/cc-connect"
    return
  fi
  return 1
}

stop_stale_lock_holder() {
  [[ -f "$lock_file" ]] || return

  local pid command_line attempt
  pid="$(awk 'NR == 1 && /^[0-9]+$/ { print; exit }' "$lock_file")"
  [[ -n "$pid" ]] || return
  kill -0 "$pid" 2>/dev/null || return

  command_line="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  if [[ "$command_line" != *cc-connect* ]]; then
    echo "拒绝结束锁文件中的 PID $pid：它不是 cc-connect 进程。" >&2
    exit 1
  fi

  echo "停止未监听 Bridge 的残留 cc-connect 进程（PID $pid）..."
  kill -TERM "$pid"
  for attempt in 1 2 3 4 5; do
    kill -0 "$pid" 2>/dev/null || return
    sleep 1
  done

  echo "PID $pid 未响应 SIGTERM，强制结束..." >&2
  kill -KILL "$pid"
}

wait_for_ports() {
  local attempt
  for ((attempt = 0; attempt < wait_seconds; attempt++)); do
    if is_healthy; then
      return
    fi
    sleep 1
  done
  return 1
}

main() {
  if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    return
  fi
  if [[ $# -gt 0 ]]; then
    usage >&2
    return 2
  fi
  if ! command -v lsof >/dev/null 2>&1; then
    echo "未找到 lsof，无法检查端口状态。" >&2
    return 1
  fi

  local cc_connect
  if ! cc_connect="$(find_cc_connect)"; then
    echo "未找到 cc-connect；请设置 CC_CONNECT_BIN 或将它加入 PATH。" >&2
    return 1
  fi

  if is_healthy; then
    echo "cc-connect Bridge 已健康：9810 和 9820 正在监听。"
    return
  fi

  stop_stale_lock_holder
  echo "启动 cc-connect 守护服务..."
  "$cc_connect" daemon start || true
  if wait_for_ports; then
    echo "cc-connect Bridge 已恢复：9810 和 9820 正在监听。"
    return
  fi

  echo "守护服务未在 ${wait_seconds} 秒内恢复，尝试重启..." >&2
  "$cc_connect" daemon restart --force || true
  if wait_for_ports; then
    echo "cc-connect Bridge 已恢复：9810 和 9820 正在监听。"
    return
  fi

  echo "cc-connect Bridge 未恢复。当前守护服务状态：" >&2
  "$cc_connect" daemon status >&2 || true
  return 1
}

main "$@"
