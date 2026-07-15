#!/bin/zsh
set -e
cd "$(dirname "$0")"

PORT="${CLASH_CHECKER_PORT:-8080}"
VENV_PYTHON=".venv/bin/python"

open_when_ready() {
  local url="$1"
  (
    for _ in {1..40}; do
      if curl -fsS "$url" >/dev/null 2>&1; then
        open "$url" >/dev/null 2>&1 || true
        exit 0
      fi
      sleep 0.5
    done
  ) &
}

echo "Stopping old Clash checker service on port $PORT if present..."
OLD_PIDS="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
if [ -n "$OLD_PIDS" ]; then
  echo "$OLD_PIDS" | xargs kill 2>/dev/null || true
  sleep 1
  OLD_PIDS="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
  if [ -n "$OLD_PIDS" ]; then
    echo "$OLD_PIDS" | xargs kill -9 2>/dev/null || true
  fi
fi

if [ ! -x "$VENV_PYTHON" ]; then
  python3 -m venv .venv
fi

"$VENV_PYTHON" -m pip install -r requirements.txt
export CLASH_CHECKER_PORT="$PORT"
open_when_ready "http://127.0.0.1:$PORT/"
"$VENV_PYTHON" web.py
