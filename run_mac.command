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

./scripts/project_center_service stop
./scripts/project_center_service prepare
export CLASH_CHECKER_PORT="$PORT"
open_when_ready "http://127.0.0.1:$PORT/"
exec "$VENV_PYTHON" web.py
