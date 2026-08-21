#!/bin/zsh
set -e
cd "$(dirname "$0")"

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

PORT="${CLASH_CHECKER_PORT:-8080}"
LAN_IP="${CLASH_CHECKER_LAN_IP:-}"

./scripts/project_center_service stop
./scripts/project_center_service prepare

if [ -z "$LAN_IP" ]; then
  DEFAULT_IFACE="$(route get default 2>/dev/null | awk '/interface:/{print $2}' || true)"
  if [ -n "$DEFAULT_IFACE" ]; then
    LAN_IP="$(ipconfig getifaddr "$DEFAULT_IFACE" 2>/dev/null || true)"
  fi
fi

if [ -z "$LAN_IP" ]; then
  for IFACE in en0 en1; do
    LAN_IP="$(ipconfig getifaddr "$IFACE" 2>/dev/null || true)"
    if [ -n "$LAN_IP" ]; then
      break
    fi
  done
fi

export CLASH_CHECKER_HOST="${CLASH_CHECKER_HOST:-0.0.0.0}"
export CLASH_CHECKER_PORT="$PORT"

if [ -n "$LAN_IP" ] && [ -z "$CLASH_CHECKER_PUBLIC_BASE_URL" ]; then
  export CLASH_CHECKER_PUBLIC_BASE_URL="http://$LAN_IP:$PORT"
fi

echo "Local URL: http://127.0.0.1:$PORT"
if [ -n "$CLASH_CHECKER_PUBLIC_BASE_URL" ]; then
  echo "LAN URL:   $CLASH_CHECKER_PUBLIC_BASE_URL"
else
  echo "LAN IP was not detected. Set CLASH_CHECKER_PUBLIC_BASE_URL manually if needed."
fi
echo "If macOS Firewall asks, allow incoming connections for Python."

open_when_ready "http://127.0.0.1:$PORT/"
exec "$VENV_PYTHON" web.py
