#!/usr/bin/env bash
# 启动前端 Vite 开发服务器（端口 5173）
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
cd "$script_dir/web"
exec npm run dev
