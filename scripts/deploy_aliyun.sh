#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_HOST="${DEPLOY_HOST:-${1:-}}"
DEPLOY_USER="${DEPLOY_USER:-root}"
DEPLOY_PATH="${DEPLOY_PATH:-/opt/hotel-price-monitor}"
DEPLOY_KEY="${DEPLOY_KEY:-}"

if [[ -z "$DEPLOY_HOST" ]]; then
  echo "Usage: DEPLOY_HOST=server_ip_or_domain [DEPLOY_USER=root] [DEPLOY_PATH=/opt/hotel-price-monitor] $0"
  exit 2
fi

REMOTE="$DEPLOY_USER@$DEPLOY_HOST"
SSH_OPTS=()
if [[ -n "$DEPLOY_KEY" ]]; then
  SSH_OPTS=(-i "$DEPLOY_KEY")
fi

echo "Deploying to $REMOTE:$DEPLOY_PATH"

ssh "${SSH_OPTS[@]}" "$REMOTE" "mkdir -p '$DEPLOY_PATH'"

ssh "${SSH_OPTS[@]}" "$REMOTE" "bash -s" <<'EOF'
set -euo pipefail
if ! command -v rsync >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update
    apt-get install -y rsync curl python3 python3-venv python3-pip
  elif command -v dnf >/dev/null 2>&1; then
    dnf install -y rsync curl python3 python3-pip
  elif command -v yum >/dev/null 2>&1; then
    yum install -y rsync curl python3 python3-pip
  else
    echo "No supported package manager found. Please install rsync, curl and python3 manually."
    exit 1
  fi
fi

if command -v yum >/dev/null 2>&1 && ! command -v python3.8 >/dev/null 2>&1; then
  yum module enable -y python38 || true
  yum install -y python38 python38-pip
fi

if command -v yum >/dev/null 2>&1 && ! command -v python3.11 >/dev/null 2>&1; then
  yum install -y python3.11 python3.11-pip
fi
EOF

rsync -az --delete \
  -e "ssh ${SSH_OPTS[*]}" \
  --exclude '.git/' \
  --exclude 'extension/node_modules/' \
  --exclude 'extension/.output/' \
  --exclude 'extension-chrome-mv3/' \
  --exclude 'diagnostics/' \
  --exclude 'backend/data/diag/' \
  --exclude 'data/backups/' \
  "$ROOT_DIR/" "$REMOTE:$DEPLOY_PATH/"

ssh "${SSH_OPTS[@]}" "$REMOTE" "bash -s" <<EOF
set -euo pipefail
cd "$DEPLOY_PATH/backend"

PYTHON_BIN="python3"
if command -v python3.12 >/dev/null 2>&1; then
  PYTHON_BIN="python3.12"
elif command -v python3.11 >/dev/null 2>&1; then
  PYTHON_BIN="python3.11"
elif command -v python3.10 >/dev/null 2>&1; then
  PYTHON_BIN="python3.10"
elif command -v python3.9 >/dev/null 2>&1; then
  PYTHON_BIN="python3.9"
elif command -v python3.8 >/dev/null 2>&1; then
  PYTHON_BIN="python3.8"
fi

if ! command -v python3 >/dev/null 2>&1; then
  apt-get update
  apt-get install -y python3 python3-venv python3-pip curl rsync
fi

rm -rf .venv
"\$PYTHON_BIN" -m venv .venv
.venv/bin/python -m pip install --upgrade "pip<25"
.venv/bin/python -m pip install -r requirements.txt
if command -v apt-get >/dev/null 2>&1; then
  .venv/bin/python -m playwright install --with-deps chromium
else
  if command -v yum >/dev/null 2>&1; then
    yum install -y \
      alsa-lib atk at-spi2-atk at-spi2-core cairo cups-libs dbus-glib \
      gtk3 libX11 libXcomposite libXdamage libXext libXfixes libXrandr \
      libXScrnSaver libXtst libdrm libxcb libxkbcommon libxshmfence \
      mesa-libgbm nspr nss pango xorg-x11-fonts-Type1 xorg-x11-fonts-misc || true
  fi
  .venv/bin/python -m playwright install chromium
fi

if [[ ! -f .env ]]; then
  cp "$DEPLOY_PATH/deploy/backend.env.example" .env
fi

.venv/bin/python scripts/seed_hotels.py

cp "$DEPLOY_PATH/deploy/hotel-price-monitor.service" /etc/systemd/system/hotel-price-monitor.service
systemctl daemon-reload
systemctl enable hotel-price-monitor
systemctl restart hotel-price-monitor
systemctl --no-pager --full status hotel-price-monitor || true
EOF

echo "Deployment command finished."
echo "Health check:"
echo "curl http://$DEPLOY_HOST:8080/health"
