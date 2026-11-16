#!/usr/bin/env bash
# Start the MediaLab backend (127.0.0.1:8000) and the Vite dev server (127.0.0.1:5173).
# If either server stops (e.g. a port is already in use), both are stopped and the script exits.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API_PORT="${MEDIALAB_PORT:-8000}"
UI_PORT=5173

if [[ ! -x "$ROOT/backend/.venv/bin/python" ]]; then
  echo "Backend virtualenv missing. Run: make setup" >&2
  exit 1
fi
if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
  echo "Frontend dependencies missing. Run: make setup" >&2
  exit 1
fi

for port in "$API_PORT" "$UI_PORT"; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "error: port $port is already in use by:" >&2
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >&2 || true
    echo "Stop that process (e.g. an earlier MediaLab run) and try again." >&2
    exit 1
  fi
done

cleanup() { kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

(cd "$ROOT/backend" && exec .venv/bin/python -m app --reload) &
API_PID=$!
(cd "$ROOT/frontend" && exec npm run dev --silent) &
UI_PID=$!

echo "MediaLab: open http://127.0.0.1:$UI_PORT (Ctrl+C to stop)"

# bash 3.2 (macOS) has no `wait -n`, so poll both processes.
while kill -0 "$API_PID" 2>/dev/null && kill -0 "$UI_PID" 2>/dev/null; do
  sleep 1
done
if ! kill -0 "$API_PID" 2>/dev/null; then
  echo "error: the MediaLab backend stopped; shutting down the frontend too." >&2
else
  echo "error: the Vite dev server stopped; shutting down the backend too." >&2
fi
exit 1
