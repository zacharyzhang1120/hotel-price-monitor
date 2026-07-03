#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Installing backend dependencies..."
cd "$ROOT_DIR/backend"
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
python3 scripts/seed_hotels.py

echo "Installing extension dependencies..."
cd "$ROOT_DIR/extension"
npm install
npm run build

echo "Copying visible extension build..."
rm -rf "$ROOT_DIR/extension-chrome-mv3"
cp -R "$ROOT_DIR/extension/.output/chrome-mv3" "$ROOT_DIR/extension-chrome-mv3"

echo "MVP is prepared."
echo "Load this Chrome extension folder:"
echo "$ROOT_DIR/extension-chrome-mv3"
