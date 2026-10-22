#!/usr/bin/env sh
# 局域网提词器 一键启动(macOS / Linux)
cd "$(dirname "$0")"
exec python3 server.py "$@"
