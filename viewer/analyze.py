"""Compute PageRank and communities over a code-graph-rag export.

Reads the graph.json produced by `cgr export`, builds a call graph over
Function/Method nodes, and writes analysis.json for server.py to serve.
Does not touch code-graph-rag's own source; this is a standalone consumer
of its JSON export format.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import networkx as nx

FUNCTION_LABELS = {"Function", "Method"}
CALLS_TYPE = "CALLS"
HEURISTIC = "heuristic"

DEFAULT_TEST_PATTERNS = ["tests/", "web/e2e/", ".test.ts", ".test.tsx", ".test.js"]


def is_test_path(path: str, patterns: list[str]) -> bool:
    if any(p in path for p in patterns):
        return True
    name = path.rsplit("/", 1)[-1]
    return name.startswith("test_") or name.endswith("_test.py")


@dataclass
class Node:
    node_id: str
    labels: list[str]
    props: dict[str, Any]

    @property
    def qualified_name(self) -> str:
        return str(self.props.get("qualified_name") or "")

    @property
    def path(self) -> str:
        return str(self.props.get("path") or "")

    @property
    def start_line(self) -> int:
        v = self.props.get("start_line")
        return int(v) if isinstance(v, (int, float)) else 0

    @property
    def end_line(self) -> int:
        v = self.props.get("end_line")
        return int(v) if isinstance(v, (int, float)) else self.start_line


@dataclass
class GraphData:
    nodes: dict[str, Node] = field(default_factory=dict)
    relationships: list[dict[str, Any]] = field(default_factory=list)


def load_graph(path: Path) -> GraphData:
    raw = json.loads(path.read_text(encoding="utf-8"))
    nodes = {
        str(n["node_id"]): Node(
            node_id=str(n["node_id"]),
            labels=list(n.get("labels", [])),
            props=dict(n.get("properties", {})),
        )
        for n in raw.get("nodes", [])
    }
    return GraphData(nodes=nodes, relationships=list(raw.get("relationships", [])))


def load_json_list(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def build_call_graph(
    graph: GraphData, test_patterns: list[str], include_tests: bool
) -> tuple[nx.DiGraph, dict[str, int], dict[str, int]]:
    included: dict[str, Node] = {}
    for node_id, node in graph.nodes.items():
        if not (set(node.labels) & FUNCTION_LABELS):
            continue
        if not include_tests and is_test_path(node.path, test_patterns):
            continue
        included[node_id] = node

    g = nx.DiGraph()
    for node_id in included:
        g.add_node(node_id)

    edge_counts = Counter()
    for rel in graph.relationships:
        if rel.get("type") != CALLS_TYPE:
            continue
        from_id, to_id = str(rel.get("from_id")), str(rel.get("to_id"))
        resolution = str((rel.get("properties") or {}).get("resolution") or "exact")
        callee = graph.nodes.get(to_id)
        if (
            resolution == HEURISTIC
            and callee is not None
            and is_test_path(callee.path, test_patterns)
        ):
            edge_counts["dropped_heuristic_into_test"] += 1
            continue
        if from_id not in included or to_id not in included:
            continue
        g.add_edge(from_id, to_id, resolution=resolution)
        edge_counts[resolution] += 1

    return g, included, edge_counts


def compute_communities(
    undirected: nx.Graph, resolution: float
) -> tuple[dict[str, int], list[set[str]]]:
    try:
        from graspologic.partition import leiden  # type: ignore[import-not-found]

        partition = leiden(undirected, resolution=resolution, random_seed=0)
        communities_by_id: dict[int, set[str]] = defaultdict(set)
        for node_id, community_id in partition.items():
            communities_by_id[community_id].add(node_id)
        communities = list(communities_by_id.values())
    except ImportError:
        communities = list(
            nx.algorithms.community.louvain_communities(
                undirected, resolution=resolution, seed=0
            )
        )

    assignment: dict[str, int] = {}
    for cid, members in enumerate(communities):
        for node_id in members:
            assignment[node_id] = cid
    return assignment, communities


def community_stats(
    communities: list[set[str]], included: dict[str, Node]
) -> dict[str, dict[str, Any]]:
    stats = {}
    for cid, members in enumerate(communities):
        folders = Counter(
            included[m].path.rsplit("/", 1)[0] if "/" in included[m].path else "."
            for m in members
        )
        top_folder, top_count = folders.most_common(1)[0] if folders else ("", 0)
        stats[str(cid)] = {
            "size": len(members),
            "top_folder": top_folder,
            "folder_match_pct": round(100 * top_count / len(members), 1)
            if members
            else 0.0,
        }
    return stats


def attach_dead_code(
    dead_code: list[dict[str, Any]], qn_to_id: dict[str, str]
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for entry in dead_code:
        node_id = qn_to_id.get(str(entry.get("qualified_name") or ""))
        if node_id:
            out[node_id] = {"label": entry.get("label", "dead")}
    return out


def attach_duplicates(
    duplicates: list[dict[str, Any]], qn_to_id: dict[str, str]
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for group_index, group in enumerate(duplicates):
        for member in group.get("members", []):
            node_id = qn_to_id.get(str(member.get("qualified_name") or ""))
            if node_id:
                out[node_id] = {
                    "group": group_index,
                    "kind": group.get("kind", "similar"),
                }
    return out


def attach_findings(
    graph: GraphData, included: dict[str, Node]
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Join SecurityIssue/CodeSmell nodes to the function/method that encloses them.

    Both attach to the owning Module via HAS_VULNERABILITY/HAS_SMELL, carrying
    only a line number, so the enclosing function is found by path + range.
    """
    by_path: dict[str, list[Node]] = defaultdict(list)
    for node in included.values():
        by_path[node.path].append(node)
    for nodes in by_path.values():
        nodes.sort(key=lambda n: n.end_line - n.start_line)

    out: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: {"security_issues": [], "code_smells": []}
    )
    rel_kind = {"HAS_VULNERABILITY": "security_issues", "HAS_SMELL": "code_smells"}
    for rel in graph.relationships:
        kind = rel_kind.get(str(rel.get("type")))
        if kind is None:
            continue
        source = graph.nodes.get(str(rel.get("from_id")))
        issue = graph.nodes.get(str(rel.get("to_id")))
        if source is None or issue is None:
            continue
        line = issue.start_line
        for candidate in by_path.get(source.path, []):
            if candidate.start_line <= line <= candidate.end_line:
                out[candidate.node_id][kind].append(
                    {
                        "name": issue.props.get("name"),
                        "message": issue.props.get("message"),
                        "start_line": line,
                    }
                )
                break
    return dict(out)


def main() -> None:
    here = Path(__file__).parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, default=here / "data" / "graph.json")
    parser.add_argument("--dead-code", type=Path, default=here / "data" / "dead-code.json")
    parser.add_argument("--duplicates", type=Path, default=here / "data" / "duplicates.json")
    parser.add_argument("--out", type=Path, default=here / "data" / "analysis.json")
    parser.add_argument("--resolution", type=float, default=1.0)
    parser.add_argument("--include-tests", action="store_true")
    parser.add_argument(
        "--test-pattern",
        action="append",
        dest="test_patterns",
        help="substring marking a path as test code; repeatable",
    )
    args = parser.parse_args()

    if not args.graph.exists():
        raise SystemExit(
            f"{args.graph} not found. Run `cgr export -o {args.graph}` against "
            "your prototypeRAG checkout first (see viewer/README.md)."
        )

    test_patterns = args.test_patterns or DEFAULT_TEST_PATTERNS
    graph = load_graph(args.graph)
    call_graph, included, edge_counts = build_call_graph(
        graph, test_patterns, args.include_tests
    )

    pagerank = nx.pagerank(call_graph) if call_graph.number_of_nodes() else {}
    undirected = call_graph.to_undirected()
    assignment, communities = (
        compute_communities(undirected, args.resolution)
        if undirected.number_of_nodes()
        else ({}, [])
    )
    modularity = (
        nx.algorithms.community.quality.modularity(undirected, communities)
        if communities
        else 0.0
    )

    qn_to_id = {n.qualified_name: n.node_id for n in included.values() if n.qualified_name}
    dead_code_by_id = attach_dead_code(load_json_list(args.dead_code), qn_to_id)
    duplicates_by_id = attach_duplicates(load_json_list(args.duplicates), qn_to_id)
    findings_by_id = attach_findings(graph, included)

    nodes_out: dict[str, dict[str, Any]] = {}
    for node_id, node in included.items():
        findings = findings_by_id.get(node_id, {"security_issues": [], "code_smells": []})
        nodes_out[node_id] = {
            "pagerank": pagerank.get(node_id, 0.0),
            "community": assignment.get(node_id),
            "dead_code": dead_code_by_id.get(node_id),
            "duplicate": duplicates_by_id.get(node_id),
            "security_issues": findings["security_issues"],
            "code_smells": findings["code_smells"],
        }

    out = {
        "generated_at": datetime.now(UTC).isoformat(),
        "params": {
            "resolution": args.resolution,
            "include_tests": args.include_tests,
            "test_patterns": test_patterns,
        },
        "stats": {
            "functions": len(included),
            "call_edges": call_graph.number_of_edges(),
            "exact_edges": edge_counts.get("exact", 0),
            "heuristic_edges": edge_counts.get(HEURISTIC, 0),
            "overload_edges": edge_counts.get("overload", 0),
            "heuristic_edges_dropped_into_tests": edge_counts.get(
                "dropped_heuristic_into_test", 0
            ),
            "communities": len(communities),
            "modularity": round(modularity, 3),
        },
        "communities": community_stats(communities, included),
        "nodes": nodes_out,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out), encoding="utf-8")
    print(
        f"wrote {args.out}: {len(included)} functions, "
        f"{call_graph.number_of_edges()} call edges, "
        f"{len(communities)} communities (modularity {round(modularity, 3)})"
    )


if __name__ == "__main__":
    main()
