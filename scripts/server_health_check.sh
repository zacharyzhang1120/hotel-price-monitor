#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8080}"

echo "Checking $BASE_URL"
curl -fsS "$BASE_URL/health"
echo
curl -fsS "$BASE_URL/api/v1/scrape/readiness"
echo
