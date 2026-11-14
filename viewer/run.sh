#!/usr/bin/env bash
# Run or rerun the code graph viewer against prototypeRAG.
# Usage: ./run.sh [port]   (default port 8010)
#        SKIP_INDEX=1 ./run.sh [port]   serve the data already in data/ without reindexing
# The server listens on every interface, so an iPad on the same Wi-Fi can open
# the "local network" URL printed below (and add it to its Home Screen).
set -euo pipefail

VIEWER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$VIEWER_DIR")"
PROTOTYPE_RAG_PATH="/Users/max/Documents/GitHub/prototypeRAG"
PORT="${1:-8010}"

export PROTOTYPE_RAG_PATH
export VIEWER_REPO_DIR="$REPO_DIR"

cd "$VIEWER_DIR"

if [ ! -x .venv/bin/python ]; then
  uv venv .venv
  uv pip install -r requirements.txt --python .venv/bin/python
fi

if [ "${SKIP_INDEX:-}" != "1" ]; then
echo "== indexing prototypeRAG =="
uv run --project "$REPO_DIR" cgr start --repo-path "$PROTOTYPE_RAG_PATH" --update-graph --clean

echo "== exporting graph =="
uv run --project "$REPO_DIR" cgr export -o data/graph.json --repo-path "$PROTOTYPE_RAG_PATH"

echo "== exporting static Orb viewer page =="
uv run --project "$REPO_DIR" cgr export -o web/graph.html --repo-path "$PROTOTYPE_RAG_PATH"

echo "== dead-code / duplicates overlays =="
uv run --project "$REPO_DIR" cgr dead-code --repo-path "$PROTOTYPE_RAG_PATH" --format json \
  > data/dead-code.json
uv run --project "$REPO_DIR" cgr duplicates --repo-path "$PROTOTYPE_RAG_PATH" --format json \
  > data/duplicates.json

echo "== computing PageRank + communities =="
.venv/bin/python analyze.py
fi

if lsof -i ":$PORT" >/dev/null 2>&1; then
  echo "port $PORT busy; pass a free one: ./run.sh <port>" >&2
  exit 1
fi

LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)"
LAN_HOST="$(scutil --get LocalHostName 2>/dev/null || true)"
echo "== serving on http://localhost:$PORT =="
if [ -n "$LAN_IP" ]; then
  echo "== also reachable on your local network at http://$LAN_IP:$PORT =="
fi
if [ -n "$LAN_HOST" ]; then
  echo "== or by name (survives IP changes) at http://$LAN_HOST.local:$PORT =="
fi
exec .venv/bin/uvicorn server:app --reload --host 0.0.0.0 --port "$PORT"
