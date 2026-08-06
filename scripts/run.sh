#!/usr/bin/env bash
# 最简启动脚本：uvicorn 起服务，供私有化机器直接跑或 systemd ExecStart 套壳。
# 配置全部走 .env（pydantic-settings 自动读仓库根目录 .env，见 wiki_memory/config.py）。
# 端口默认 8020，可用环境变量覆盖：PORT=9020 scripts/run.sh
set -euo pipefail

cd "$(dirname "$0")/.."

PORT="${PORT:-8020}"
HOST="${HOST:-0.0.0.0}"

# 优先用仓内虚拟环境；没有则用当前 PATH 里的 python
if [ -x .venv/bin/python ]; then
    PYTHON=.venv/bin/python
else
    PYTHON=python3
fi

exec "$PYTHON" -m uvicorn wiki_memory.main:app --host "$HOST" --port "$PORT"
