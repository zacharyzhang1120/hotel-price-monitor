#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR/backend"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

python3 scripts/seed_hotels.py
python3 -m uvicorn app.main:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8080}"
