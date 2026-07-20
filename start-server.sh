#!/usr/bin/env bash
# 启动后端 FastAPI 服务（端口 18800）
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
python_bin="$script_dir/.venv/bin/python"

if [[ ! -x "$python_bin" ]]; then
  echo "未找到 Python 虚拟环境：$python_bin" >&2
  echo "请先在 $script_dir 创建并安装 .venv。" >&2
  exit 1
fi

cd "$script_dir"
exec "$python_bin" -m agent
