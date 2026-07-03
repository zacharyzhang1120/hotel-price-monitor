#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_BASE="${1:-${VITE_API_BASE:-http://localhost:8080/api/v1}}"

cd "$ROOT_DIR/extension"

echo "Building Chrome extension..."
echo "API: $API_BASE"
VITE_API_BASE="$API_BASE" npm run build

rm -rf "$ROOT_DIR/extension-chrome-mv3"
cp -R "$ROOT_DIR/extension/.output/chrome-mv3" "$ROOT_DIR/extension-chrome-mv3"

echo "Extension build is ready:"
echo "$ROOT_DIR/extension-chrome-mv3"
