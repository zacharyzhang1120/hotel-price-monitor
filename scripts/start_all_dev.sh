#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cleanup() {
  if [[ -n "${BACKEND_PID:-}" ]]; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [[ -n "${EXTENSION_PID:-}" ]]; then
    kill "$EXTENSION_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

cd "$ROOT_DIR/backend"
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
python3 scripts/seed_hotels.py
python3 -m uvicorn app.main:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8080}" &
BACKEND_PID=$!

cd "$ROOT_DIR/extension"
npm run dev &
EXTENSION_PID=$!

echo "后端：http://${HOST:-127.0.0.1}:${PORT:-8080}"
echo "插件开发目录：$ROOT_DIR/extension/.output/chrome-mv3-dev"
echo "按 Ctrl+C 停止所有服务"

wait -n "$BACKEND_PID" "$EXTENSION_PID"
