#!/usr/bin/env bash
# Pull latest main, stop any viewer already on the target port, and
# re-run/re-serve the viewer (run.sh does the indexing, export and serving).
# Usage: ./reload.sh [port]   (default port 8010)
set -euo pipefail

VIEWER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$VIEWER_DIR")"
PORT="${1:-8010}"

echo "== pulling main =="
git -C "$REPO_DIR" pull origin main

PIDS="$(lsof -ti ":$PORT" 2>/dev/null || true)"
if [ -n "$PIDS" ]; then
  echo "== stopping existing viewer on :$PORT (pid $PIDS) =="
  kill $PIDS
  for _ in $(seq 1 20); do
    lsof -i ":$PORT" >/dev/null 2>&1 || break
    sleep 0.5
  done
fi

exec "$VIEWER_DIR/run.sh" "$PORT"
