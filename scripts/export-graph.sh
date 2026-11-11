#!/usr/bin/env bash
# Pull latest main, sync deps, export a repo's graph as an interactive
# Orb HTML page, and open it.
# Usage: ./scripts/export-graph.sh <repo-path> [output.html]
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_PATH="${1:?usage: export-graph.sh <repo-path> [output.html]}"
OUTPUT="${2:-graph.html}"

cd "$REPO_DIR"
git pull origin main
uv sync

uv run cgr export -o "$OUTPUT" --repo-path "$REPO_PATH"
open "$OUTPUT"
