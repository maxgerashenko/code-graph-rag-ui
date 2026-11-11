"""Render an exported graph as one self-contained, interactive HTML page.

`cgr export -o graph.html` writes it: the graph is drawn with Memgraph's Orb
library, with search, per-type filters, a details panel and neighbourhood
focus. The page holds the graph itself, so it opens from disk with no server.
"""

from __future__ import annotations

import html
import inspect
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path

from . import constants as cs
from .types_defs import GraphData, PropertyValue

_TEMPLATE_PATH = Path(__file__).parent / "viewer" / cs.VIEWER_TEMPLATE
# A project derived from a checkout path ends in a digest of that path
# (`shop__1a2b3c4d`); it keeps names unique, but a reader of the page only
# needs `shop`.
_PROJECT_DIGEST = re.compile(
    rf"{re.escape(cs.PROJECT_NAME_DIGEST_MARKER)}[0-9a-f]{{{cs.PROJECT_NAME_DIGEST_LEN}}}$"
)


def is_viewer_output(output_path: Path) -> bool:
    return output_path.suffix.lower() == cs.VIEWER_SUFFIX


def _script_safe_json(payload: object) -> str:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    for char, escape in cs.VIEWER_SCRIPT_ESCAPES.items():
        text = text.replace(char, escape)
    return text


def _text(properties: Mapping[str, PropertyValue], key: str) -> str | None:
    value = properties.get(key)
    return value if isinstance(value, str) and value else None


def _line(properties: Mapping[str, PropertyValue], key: str) -> int | None:
    value = properties.get(key)
    # bool is an int subclass; a line number is never one.
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _properties(node: Mapping[str, object]) -> Mapping[str, PropertyValue]:
    properties = node.get(cs.KEY_PROPERTIES)
    return properties if isinstance(properties, Mapping) else {}


def _label(node: Mapping[str, object]) -> str:
    labels = node.get(cs.KEY_LABELS)
    return str(labels[0]) if isinstance(labels, Sequence) and labels else ""


def _view_node(node: Mapping[str, object]) -> dict[str, object]:
    properties = _properties(node)
    label = _label(node)
    view: dict[str, object] = {
        cs.VIEWER_KEY_ID: node[cs.KEY_NODE_ID],
        cs.VIEWER_KEY_LABEL: label,
    }
    name = _text(properties, cs.KEY_NAME)
    qualified_name = _text(properties, cs.KEY_QUALIFIED_NAME)
    view[cs.VIEWER_KEY_NAME] = name or qualified_name or label
    if label == cs.VIEWER_PROJECT_LABEL and name:
        view[cs.VIEWER_KEY_NAME] = _PROJECT_DIGEST.sub("", name)
    if qualified_name:
        view[cs.VIEWER_KEY_QN] = qualified_name
    if path := _text(properties, cs.KEY_PATH):
        view[cs.VIEWER_KEY_PATH] = path
    if (start := _line(properties, cs.KEY_START_LINE)) is not None:
        view[cs.VIEWER_KEY_START] = start
    if (end := _line(properties, cs.KEY_END_LINE)) is not None:
        view[cs.VIEWER_KEY_END] = end
    if doc := _text(properties, cs.KEY_DOCSTRING):
        view[cs.VIEWER_KEY_DOC] = inspect.cleandoc(doc)[: cs.VIEWER_MAX_DOC_CHARS]
    return view


def _most_connected(
    node_ids: Sequence[object],
    edges: Sequence[tuple[object, object, str]],
    limit: int,
) -> set[object]:
    degree: Counter[object] = Counter()
    for source, target, _ in edges:
        degree[source] += 1
        degree[target] += 1
    # Stable on ties, so the same export always keeps the same nodes.
    ranked = sorted(node_ids, key=lambda node_id: -degree[node_id])
    return set(ranked[:limit])


def build_view_data(
    graph_data: GraphData, title: str, max_nodes: int = cs.VIEWER_MAX_NODES
) -> dict[str, object]:
    nodes = [_view_node(node) for node in graph_data[cs.KEY_NODES]]
    known = {node[cs.VIEWER_KEY_ID] for node in nodes}
    # One edge per (source, target, type): the graph keeps a CALLS edge per
    # call site, and Orb draws each parallel edge as a wider arc.
    edges = list(
        dict.fromkeys(
            (rel[cs.KEY_FROM_ID], rel[cs.KEY_TO_ID], str(rel[cs.KEY_TYPE]))
            for rel in graph_data[cs.KEY_RELATIONSHIPS]
            if rel[cs.KEY_FROM_ID] in known and rel[cs.KEY_TO_ID] in known
        )
    )

    meta: dict[str, object] = dict(graph_data[cs.KEY_METADATA])
    if len(nodes) > max_nodes:
        keep = _most_connected(
            [node[cs.VIEWER_KEY_ID] for node in nodes], edges, max_nodes
        )
        nodes = [node for node in nodes if node[cs.VIEWER_KEY_ID] in keep]
        edges = [edge for edge in edges if edge[0] in keep and edge[1] in keep]
        meta[cs.VIEWER_KEY_TRUNCATED] = True
        meta[cs.VIEWER_KEY_SHOWN_NODES] = len(nodes)

    return {
        cs.VIEWER_KEY_TITLE: title,
        cs.VIEWER_KEY_META: meta,
        cs.KEY_NODES: nodes,
        cs.VIEWER_KEY_EDGES: [
            {
                cs.VIEWER_KEY_SOURCE: source,
                cs.VIEWER_KEY_TARGET: target,
                cs.VIEWER_KEY_KIND: kind,
            }
            for source, target, kind in edges
        ],
    }


def default_title(graph_data: GraphData) -> str:
    projects = graph_data[cs.KEY_METADATA].get(cs.VIEWER_KEY_PROJECTS)
    if not projects:
        projects = [
            name
            for node in graph_data[cs.KEY_NODES]
            if _label(node) == cs.VIEWER_PROJECT_LABEL
            and (name := _text(_properties(node), cs.KEY_NAME))
        ]
    names = dict.fromkeys(_PROJECT_DIGEST.sub("", name) for name in sorted(projects))
    return ", ".join(names) if names else cs.VIEWER_DEFAULT_TITLE


def render_graph_html(
    graph_data: GraphData,
    title: str | None = None,
    max_nodes: int = cs.VIEWER_MAX_NODES,
) -> str:
    title = title or default_title(graph_data)
    view = build_view_data(graph_data, title, max_nodes)
    template = _TEMPLATE_PATH.read_text(encoding=cs.ENCODING_UTF8)
    # The data goes in last: a graph string that happens to spell a
    # placeholder must not be substituted again.
    return (
        template.replace(cs.VIEWER_PLACEHOLDER_TITLE, html.escape(title))
        .replace(cs.VIEWER_PLACEHOLDER_ORB_URL, cs.VIEWER_ORB_URL)
        .replace(cs.VIEWER_PLACEHOLDER_ORB_SRI, cs.VIEWER_ORB_SRI)
        .replace(cs.VIEWER_PLACEHOLDER_DATA, _script_safe_json(view))
    )
