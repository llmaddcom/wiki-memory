#!/usr/bin/env bash
# 最简启动脚本：uvicorn 起服务，供私有化机器直接跑或 systemd ExecStart 套壳。
# 连接/密钥/本机项走 .env（pydantic-settings 自动读仓库根目录 .env，见 wiki_memory/config.py）；
# 系统调优在 config/system.yaml（进 git）。
# 监听地址/端口取 .env 的 WIKIMEM_HOST / WIKIMEM_PORT（默认 0.0.0.0 / 8020），
# 仍可用环境变量临时覆盖：PORT=9020 scripts/run.sh
set -euo pipefail

cd "$(dirname "$0")/.."

# 从 .env 取整行 KEY=VALUE（最后一次出现为准，剥掉两侧引号）；缺失返回空。
dotenv_value() {
    grep -E "^$1=" .env 2>/dev/null | tail -n1 | cut -d= -f2- | sed -e 's/^["'"'"']//' -e 's/["'"'"']$//' || true
}

PORT="${PORT:-$(dotenv_value WIKIMEM_PORT)}"
PORT="${PORT:-8020}"
HOST="${HOST:-$(dotenv_value WIKIMEM_HOST)}"
HOST="${HOST:-0.0.0.0}"

# 优先用仓内虚拟环境；没有则用当前 PATH 里的 python
if [ -x .venv/bin/python ]; then
    PYTHON=.venv/bin/python
else
    PYTHON=python3
fi

exec "$PYTHON" -m uvicorn wiki_memory.main:app --host "$HOST" --port "$PORT"
