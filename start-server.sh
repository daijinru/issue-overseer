#!/usr/bin/env bash
# 启动后端 FastAPI 服务 (端口 18800)
set -e
cd "$(dirname "$0")"
exec uv run python -m mango
