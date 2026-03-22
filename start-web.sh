#!/usr/bin/env bash
# 启动前端 Vite 开发服务器 (端口 5173)
set -e
cd "$(dirname "$0")/web"
npm run dev
