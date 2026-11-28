#!/usr/bin/env bash
# Stop the PMCursor verification server this run started, and remove scratch state.
# Never kills by process name — only the PIDs recorded by up.sh, plus any orphan
# still holding the recorded port whose command is our `pmcursor serve`.
# Usage: ./down.sh   — run from the repo root. Evidence in .pmcursor-verify/evidence/ is untouched.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
RUN_DIR="$REPO_ROOT/.pmcursor-verify/run"
PID_FILE="$RUN_DIR/server.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "nothing to stop"
  exit 0
fi

PIDS="$(cat "$PID_FILE") $(cat "$RUN_DIR/server.listener.pid" 2>/dev/null || true)"
PORT="$(cat "$RUN_DIR/server.port" 2>/dev/null || true)"

# The console script may re-exec and strand a listener that is not the recorded
# PID. Adopt it only if its command is provably this repo's `pmcursor serve`.
if [[ -n "$PORT" ]]; then
  for LPID in $(lsof -nP -t -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true); do
    CMD="$(ps -p "$LPID" -o command= 2>/dev/null || true)"
    if [[ "$CMD" == *"pmcursor serve"*"$PORT"* ]] || [[ "$CMD" == *"pmcursor"*"serve"* && "$CMD" == *"$PORT"* ]]; then
      PIDS="$PIDS $LPID"
    fi
  done
fi

PIDS="$(echo "$PIDS" | tr ' ' '\n' | sort -un | tr '\n' ' ')"

for PID in $PIDS; do
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null || true
  fi
done
for _ in $(seq 1 10); do
  ALIVE=0
  for PID in $PIDS; do
    kill -0 "$PID" 2>/dev/null && ALIVE=1
  done
  [[ "$ALIVE" == "0" ]] && break
  sleep 1
done
for PID in $PIDS; do
  kill -0 "$PID" 2>/dev/null && kill -9 "$PID" 2>/dev/null || true
done

if [[ -n "$PORT" ]] && curl -sf "http://127.0.0.1:$PORT/health" > /dev/null 2>&1; then
  echo "WARN: port $PORT still answers after teardown — foreign instance left alone." >&2
fi

rm -rf "$RUN_DIR"
echo "stopped pids:$(echo "$PIDS" | tr ' ' ',')"
