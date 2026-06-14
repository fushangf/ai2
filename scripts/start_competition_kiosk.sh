#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export COMPETITION_KIOSK_MODE=true
export COMPETITION_DEMO_LOCALHOST_ONLY=true
export DATABASE_URL="${DATABASE_URL:-sqlite:///./data/competition.db}"

python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT
sleep 3

BROWSER=""
for candidate in google-chrome chromium chromium-browser microsoft-edge; do
  if command -v "$candidate" >/dev/null 2>&1; then BROWSER="$candidate"; break; fi
done

if [[ -n "$BROWSER" ]]; then
  "$BROWSER" --kiosk --autoplay-policy=no-user-gesture-required --use-fake-ui-for-media-stream http://127.0.0.1:8000/workspace
else
  echo "请在浏览器打开 http://127.0.0.1:8000/workspace"
  wait "$SERVER_PID"
fi
