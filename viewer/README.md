# Code graph viewer

A standalone web UI on top of `cgr`'s graph export. Lives entirely in this
folder — nothing outside `viewer/` is touched, so it stays out of the way of
the forked `code-graph-rag` code.

It shows PageRank ("god nodes"), Leiden/Louvain communities, and dead-code /
duplicate / security overlays for a target repo (e.g. `prototypeRAG`), as an
interactive Sigma.js graph.

## 1. Set up this repo's `cgr`

From the repo root (not `viewer/`):

```bash
uv sync --extra treesitter-full
```

## 2. Point `cgr` at your prototypeRAG checkout and export the graph

```bash
cd viewer
uv run --project .. cgr start --repo-path /path/to/prototypeRAG --update-graph --clean
uv run --project .. cgr export -o data/graph.json --repo-path /path/to/prototypeRAG
# optional, for the dead-code / duplicate overlays:
uv run --project .. cgr dead-code --repo-path /path/to/prototypeRAG --format json > data/dead-code.json
uv run --project .. cgr duplicates --repo-path /path/to/prototypeRAG --format json > data/duplicates.json
```

## 3. Install the viewer's own dependencies

```bash
cd viewer
uv venv .venv
uv pip install -r requirements.txt --python .venv/bin/python
```

## 4. Compute PageRank + communities

```bash
.venv/bin/python analyze.py
```

Writes `data/analysis.json`. Flags: `--include-tests`, `--resolution 0.3`
(smaller = fewer, bigger communities), `--test-pattern` (repeatable).
Heuristic call edges that point into test files are always dropped; the rest
are kept and tagged `resolution: "heuristic"` for the UI's dashed-edge toggle.

## 5. Run the server

```bash
# optional: lets node detail show a source snippet
export PROTOTYPE_RAG_PATH=/path/to/prototypeRAG
.venv/bin/uvicorn server:app --reload --port 8000
```

Open http://localhost:8000.

## Re-running after a fix

```bash
uv run --project .. cgr start --repo-path /path/to/prototypeRAG --update-graph
uv run --project .. cgr export -o data/graph.json --repo-path /path/to/prototypeRAG
.venv/bin/python analyze.py
```

Reload the page (the server re-reads `data/` on the next request after a
restart — restart `uvicorn` too, or hit it hard enough; it caches in memory).

## Notes

- Communities default to networkx's built-in Louvain (BSD, no extra
  dependency). To use true Leiden instead, `uv pip install graspologic`
  (MIT) into `viewer/.venv` — `analyze.py` picks it up automatically if
  importable.
- `data/*.json` is gitignored; only this README, the scripts and `web/` are
  meant to be committed.
