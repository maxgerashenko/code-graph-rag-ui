#!/usr/bin/env bash
# Run or rerun the code graph viewer against prototypeRAG.
# Usage: ./run.sh [port]   (default port 8010)
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

if lsof -i ":$PORT" >/dev/null 2>&1; then
  echo "port $PORT busy; pass a free one: ./run.sh <port>" >&2
  exit 1
fi

echo "== serving on http://localhost:$PORT =="
exec .venv/bin/uvicorn server:app --reload --port "$PORT"
