#!/usr/bin/env bash
# 启动后端 FastAPI 服务（端口 18800）
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
python_bin="$script_dir/.venv/bin/python"
cc_config_file="$HOME/.cc-connect/config.toml"

if [[ ! -x "$python_bin" ]]; then
  echo "未找到 Python 虚拟环境：$python_bin" >&2
  echo "请先在 $script_dir 创建并安装 .venv。" >&2
  exit 1
fi

if [[ -z "${CC_CONNECT_BRIDGE_TOKEN:-}" && -f "$cc_config_file" ]]; then
  bridge_token="$(awk '
    /^\[bridge\]$/ { in_bridge = 1; next }
    /^\[/ { in_bridge = 0 }
    in_bridge && /^[[:space:]]*token[[:space:]]*=/ {
      sub(/^[^=]*=[[:space:]]*/, "")
      gsub(/^[[:space:]]*"|"[[:space:]]*$/, "")
      print
      exit
    }
  ' "$cc_config_file")"
  if [[ -n "$bridge_token" ]]; then
    export CC_CONNECT_BRIDGE_TOKEN="$bridge_token"
  fi
fi

if [[ -z "${CC_CONNECT_BRIDGE_TOKEN:-}" ]]; then
  echo "未配置 cc-connect Bridge token。" >&2
  echo "请设置 CC_CONNECT_BRIDGE_TOKEN，或在 $cc_config_file 的 [bridge] 段配置 token。" >&2
  exit 1
fi

cd "$script_dir"
exec "$python_bin" -m agent
