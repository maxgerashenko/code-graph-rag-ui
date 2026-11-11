"""Serves the code graph (graph.json + analysis.json) to web/index.html.

Standalone FastAPI app; does not import or modify codebase_rag. Point it at
viewer/data (set with VIEWER_DATA_DIR) after running `cgr export` and
analyze.py against your prototypeRAG checkout.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from starlette.types import Receive, Scope, Send


class _NoCacheStaticFiles(StaticFiles):
    """Dev assets change under the same filename on every reindex/reload, so
    the browser's disk cache (which ignores `--reload`) must never serve a
    stale copy on a plain refresh."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_no_cache(message: Any) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        await super().__call__(scope, receive, send_no_cache)

HERE = Path(__file__).parent
DATA_DIR = Path(os.environ.get("VIEWER_DATA_DIR", HERE / "data"))
SOURCE_ROOT = os.environ.get("PROTOTYPE_RAG_PATH")
REPO_DIR = os.environ.get("VIEWER_REPO_DIR")
WATCH_POLL_SECONDS = 5
FUNCTION_LABELS = {"Function", "Method"}

app = FastAPI(title="code graph viewer")

_state: dict[str, Any] = {}
_version = 0
_version_lock = threading.Lock()


def _load() -> dict[str, Any]:
    graph_path = DATA_DIR / "graph.json"
    analysis_path = DATA_DIR / "analysis.json"
    if not graph_path.exists():
        raise RuntimeError(
            f"{graph_path} not found. Run `cgr export -o {graph_path}` against "
            "your prototypeRAG checkout (see viewer/README.md)."
        )
    if not analysis_path.exists():
        raise RuntimeError(
            f"{analysis_path} not found. Run `python analyze.py` first."
        )

    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))

    nodes_by_id = {
        str(n["node_id"]): {"labels": n.get("labels", []), "props": n.get("properties", {})}
        for n in graph.get("nodes", [])
    }
    callers: dict[str, list[dict[str, Any]]] = defaultdict(list)
    callees: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rel in graph.get("relationships", []):
        if rel.get("type") != "CALLS":
            continue
        from_id, to_id = str(rel.get("from_id")), str(rel.get("to_id"))
        resolution = str((rel.get("properties") or {}).get("resolution") or "exact")
        if from_id in analysis["nodes"] and to_id in analysis["nodes"]:
            callees[from_id].append({"id": to_id, "resolution": resolution})
            callers[to_id].append({"id": from_id, "resolution": resolution})

    dead_code = _load_json_list(DATA_DIR / "dead-code.json")
    duplicates = _load_json_list(DATA_DIR / "duplicates.json")

    return {
        "nodes_by_id": nodes_by_id,
        "analysis": analysis,
        "callers": callers,
        "callees": callees,
        "dead_code": dead_code,
        "duplicates": duplicates,
    }


def _load_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def state() -> dict[str, Any]:
    if not _state:
        _state.update(_load())
    return _state


def _node_summary(node_id: str) -> dict[str, Any]:
    s = state()
    raw = s["nodes_by_id"].get(node_id)
    if raw is None:
        raise HTTPException(404, f"no such node: {node_id}")
    info = s["analysis"]["nodes"].get(node_id, {})
    props = raw["props"]
    return {
        "id": node_id,
        "label": next((l for l in raw["labels"] if l in FUNCTION_LABELS), raw["labels"][0] if raw["labels"] else "?"),
        "name": props.get("name"),
        "qualified_name": props.get("qualified_name"),
        "path": props.get("path"),
        "start_line": props.get("start_line"),
        "end_line": props.get("end_line"),
        "pagerank": info.get("pagerank"),
        "community": info.get("community"),
        "dead_code": info.get("dead_code"),
        "duplicate": info.get("duplicate"),
        "security_issues": info.get("security_issues", []),
        "code_smells": info.get("code_smells", []),
    }


@app.get("/api/stats")
def stats() -> dict[str, Any]:
    s = state()
    return {
        **s["analysis"]["stats"],
        "graph_nodes": len(s["nodes_by_id"]),
        "dead_code_entries": len(s["dead_code"]),
        "duplicate_groups": len(s["duplicates"]),
        "generated_at": s["analysis"]["generated_at"],
        "params": s["analysis"]["params"],
    }


@app.get("/api/communities")
def communities() -> list[dict[str, Any]]:
    s = state()
    return [
        {"id": int(cid), **info}
        for cid, info in sorted(
            s["analysis"]["communities"].items(), key=lambda kv: -kv[1]["size"]
        )
    ]


@app.get("/api/graph")
def graph(
    community: int | None = None,
    show_heuristic: bool = False,
    min_pagerank: float = 0.0,
    limit: int = 3000,
) -> dict[str, Any]:
    s = state()
    nodes_info = s["analysis"]["nodes"]

    node_ids = [
        nid
        for nid, info in nodes_info.items()
        if (community is None or info.get("community") == community)
        and info.get("pagerank", 0.0) >= min_pagerank
    ]
    node_ids.sort(key=lambda nid: -nodes_info[nid].get("pagerank", 0.0))
    node_ids = node_ids[:limit]
    node_set = set(node_ids)

    nodes = [_node_summary(nid) for nid in node_ids]
    edges = []
    for nid in node_ids:
        for callee in s["callees"].get(nid, []):
            if callee["id"] not in node_set:
                continue
            if callee["resolution"] == "heuristic" and not show_heuristic:
                continue
            edges.append(
                {"source": nid, "target": callee["id"], "resolution": callee["resolution"]}
            )

    return {"nodes": nodes, "edges": edges}


@app.get("/api/node/{node_id}")
def node_detail(node_id: str) -> dict[str, Any]:
    s = state()
    summary = _node_summary(node_id)
    summary["callers"] = [
        _node_summary(c["id"]) | {"resolution": c["resolution"]} for c in s["callers"].get(node_id, [])
    ]
    summary["callees"] = [
        _node_summary(c["id"]) | {"resolution": c["resolution"]} for c in s["callees"].get(node_id, [])
    ]
    summary["source"] = _read_source(summary["path"], summary["start_line"], summary["end_line"])
    return summary


def _read_source(path: str | None, start: int | None, end: int | None) -> str | None:
    if not SOURCE_ROOT or not path or not start or not end:
        return None
    file_path = Path(SOURCE_ROOT) / path
    if not file_path.is_file():
        return None
    lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    lo, hi = max(0, start - 1), min(len(lines), end)
    return "\n".join(lines[lo:hi])


@app.get("/api/search")
def search(q: str, limit: int = 30) -> list[dict[str, Any]]:
    s = state()
    q_lower = q.lower()
    hits = []
    for nid, raw in s["nodes_by_id"].items():
        if nid not in s["analysis"]["nodes"]:
            continue
        qn = str(raw["props"].get("qualified_name") or "")
        if q_lower in qn.lower():
            hits.append(nid)
        if len(hits) >= limit:
            break
    return [_node_summary(nid) for nid in hits]


@app.get("/api/issues")
def issues() -> dict[str, Any]:
    s = state()
    return {"dead_code": s["dead_code"], "duplicates": s["duplicates"]}


@app.get("/api/version")
def version() -> dict[str, int]:
    with _version_lock:
        return {"version": _version}


def _current_head() -> str | None:
    if not SOURCE_ROOT:
        return None
    try:
        out = subprocess.run(
            ["git", "-C", SOURCE_ROOT, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        return out.stdout.strip()
    except Exception:
        return None


def _reindex() -> None:
    cgr = ["uv", "run", "--project", REPO_DIR, "cgr"]
    subprocess.run(
        [*cgr, "start", "--repo-path", SOURCE_ROOT, "--update-graph", "--clean"],
        check=True,
        cwd=str(HERE),
    )
    subprocess.run(
        [*cgr, "export", "-o", str(DATA_DIR / "graph.json"), "--repo-path", SOURCE_ROOT],
        check=True,
        cwd=str(HERE),
    )
    subprocess.run(
        [*cgr, "export", "-o", str(HERE / "web" / "graph.html"), "--repo-path", SOURCE_ROOT],
        check=True,
        cwd=str(HERE),
    )
    dead = subprocess.run(
        [*cgr, "dead-code", "--repo-path", SOURCE_ROOT, "--format", "json"],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(HERE),
    )
    (DATA_DIR / "dead-code.json").write_text(dead.stdout, encoding="utf-8")
    dup = subprocess.run(
        [*cgr, "duplicates", "--repo-path", SOURCE_ROOT, "--format", "json"],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(HERE),
    )
    (DATA_DIR / "duplicates.json").write_text(dup.stdout, encoding="utf-8")
    subprocess.run([".venv/bin/python", "analyze.py"], check=True, cwd=str(HERE))
    _state.clear()


def _watch_loop() -> None:
    last_head = _current_head()
    while True:
        time.sleep(WATCH_POLL_SECONDS)
        head = _current_head()
        if not head or head == last_head:
            continue
        last_head = head
        try:
            _reindex()
        except Exception as e:
            print(f"reindex after git pull failed: {e}")
            continue
        global _version
        with _version_lock:
            _version += 1


if REPO_DIR and SOURCE_ROOT:
    threading.Thread(target=_watch_loop, daemon=True).start()


app.mount("/", _NoCacheStaticFiles(directory=str(HERE / "web"), html=True), name="web")
