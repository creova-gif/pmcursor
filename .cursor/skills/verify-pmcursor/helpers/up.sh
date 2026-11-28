#!/usr/bin/env bash
# Start a PMCursor verification server on a port this run owns.
# Usage: ./up.sh [port]   (default 8123)   — run from the repo root.
set -euo pipefail

PORT="${1:-8123}"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
RUN_DIR="$REPO_ROOT/.pmcursor-verify/run"
PMCURSOR="$REPO_ROOT/.venv/bin/pmcursor"

if [[ -f "$RUN_DIR/server.pid" ]] && kill -0 "$(cat "$RUN_DIR/server.pid")" 2>/dev/null; then
  echo "FAIL: a run is already recorded at $RUN_DIR (pid $(cat "$RUN_DIR/server.pid")). Run down.sh first." >&2
  exit 1
fi

# The console script re-execs, so the listener PID differs from the launched
# PID. Refuse to start on an occupied port — a foreign instance must never be
# adopted (or killed) by a verification run.
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN > /dev/null 2>&1; then
  echo "FAIL: port $PORT already has a listener:" >&2
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >&2
  echo "Pick another port (./up.sh <port>) — do not adopt a foreign instance." >&2
  exit 1
fi

if [[ ! -x "$PMCURSOR" ]]; then
  echo "FAIL: $PMCURSOR not found. Install with: VIRTUAL_ENV=.venv uv pip install -e '.[server]'" >&2
  exit 1
fi

mkdir -p "$RUN_DIR"
cd "$REPO_ROOT"
nohup "$PMCURSOR" serve --host 127.0.0.1 --port "$PORT" > "$RUN_DIR/server.log" 2>&1 &
PID=$!
echo "$PID" > "$RUN_DIR/server.pid"
echo "$PORT" > "$RUN_DIR/server.port"

for _ in $(seq 1 30); do
  if ! kill -0 "$PID" 2>/dev/null && ! lsof -nP -iTCP:"$PORT" -sTCP:LISTEN > /dev/null 2>&1; then
    echo "FAIL: server died during startup. Log:" >&2
    tail -20 "$RUN_DIR/server.log" >&2
    exit 1
  fi
  if curl -sf "http://127.0.0.1:$PORT/readyz" > /dev/null 2>&1; then
    LISTENER_PID="$(lsof -nP -t -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -1)"
    echo "$LISTENER_PID" > "$RUN_DIR/server.listener.pid"
    echo "READY pid=$PID listener_pid=$LISTENER_PID port=$PORT"
    exit 0
  fi
  sleep 1
done

echo "FAIL: server did not become ready in 30s. Log:" >&2
tail -20 "$RUN_DIR/server.log" >&2
kill "$PID" 2>/dev/null || true
exit 1
