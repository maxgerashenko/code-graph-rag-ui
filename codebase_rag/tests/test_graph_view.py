"""`cgr export -o graph.html`: the interactive graph page.

The page embeds the graph as JSON inside a <script> element and draws it
with Memgraph's Orb, so these check what the page is given: the trimmed node
records, one edge per (source, target, type), a cap on very large graphs,
and that no string from the indexed code can close the script element.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import MagicMock

from codebase_rag import constants as cs
from codebase_rag.graph_view import (
    build_view_data,
    default_title,
    is_viewer_output,
    render_graph_html,
)
from codebase_rag.main import export_graph_to_file
from codebase_rag.types_defs import GraphData, GraphMetadata


def _graph(
    nodes: list[dict], relationships: list[dict], **metadata: object
) -> GraphData:
    meta = GraphMetadata(
        total_nodes=len(nodes),
        total_relationships=len(relationships),
        exported_at="2026-11-11T00:00:00+00:00",
    )
    meta.update(metadata)
    return GraphData(nodes=nodes, relationships=relationships, metadata=meta)


def _node(node_id: int, label: str, **properties: object) -> dict:
    return {"node_id": node_id, "labels": [label], "properties": properties}


def _rel(source: int, target: int, kind: str = "CALLS") -> dict:
    return {"from_id": source, "to_id": target, "type": kind, "properties": {}}


def _embedded_data(page: str) -> dict:
    match = re.search(
        r'<script id="cgr-data" type="application/json">(.*?)</script>',
        page,
        re.DOTALL,
    )
    assert match, "the page carries no graph data"
    return json.loads(match.group(1))


SAMPLE = _graph(
    [
        _node(1, "Project", name="shop"),
        _node(
            2,
            "Function",
            name="checkout",
            qualified_name="shop.cart.checkout",
            path="cart.py",
            start_line=10,
            end_line=24,
            docstring="    Charge the cart.\n\n    Raises on a declined card.",
            absolute_path="/home/someone/shop/cart.py",
        ),
        _node(3, "Function", name="charge", qualified_name="shop.pay.charge"),
    ],
    [_rel(2, 3), _rel(2, 3), _rel(1, 2, "CONTAINS_FILE"), _rel(2, 99)],
)


class TestViewData:
    def test_keeps_what_the_page_shows_and_drops_the_rest(self) -> None:
        nodes = build_view_data(SAMPLE, "shop")["nodes"]
        checkout = next(n for n in nodes if n["id"] == 2)
        assert checkout == {
            "id": 2,
            "label": "Function",
            "name": "checkout",
            "qn": "shop.cart.checkout",
            "path": "cart.py",
            "start": 10,
            "end": 24,
            "doc": "Charge the cart.\n\nRaises on a declined card.",
        }

    def test_parallel_edges_collapse_and_dangling_ones_drop(self) -> None:
        edges = build_view_data(SAMPLE, "shop")["edges"]
        assert edges == [
            {"s": 2, "t": 3, "k": "CALLS"},
            {"s": 1, "t": 2, "k": "CONTAINS_FILE"},
        ]

    def test_a_large_graph_keeps_its_most_connected_nodes(self) -> None:
        hub = _node(0, "Module", name="hub")
        leaves = [_node(i, "Function", name=f"f{i}") for i in range(1, 6)]
        graph = _graph([hub, *leaves], [_rel(0, i) for i in range(1, 4)] + [_rel(1, 2)])

        view = build_view_data(graph, "big", max_nodes=3)

        assert sorted(n["id"] for n in view["nodes"]) == [0, 1, 2]
        assert {(e["s"], e["t"]) for e in view["edges"]} == {(0, 1), (0, 2), (1, 2)}
        meta = view["meta"]
        assert meta["truncated"] is True
        assert meta["shown_nodes"] == 3
        assert meta["total_nodes"] == 6

    def test_a_small_graph_is_not_marked_truncated(self) -> None:
        assert "truncated" not in build_view_data(SAMPLE, "shop")["meta"]


class TestTitle:
    def test_a_scoped_export_is_named_after_its_projects(self) -> None:
        graph = _graph([], [], projects=["shop", "api"])
        assert default_title(graph) == "api, shop"

    def test_a_whole_graph_export_is_named_after_its_project_nodes(self) -> None:
        assert default_title(SAMPLE) == "shop"

    def test_the_path_digest_is_left_out_of_the_title(self) -> None:
        graph = _graph([], [], projects=["shop__1a2b3c4d", "api__0f0f0f0f"])
        assert default_title(graph) == "api, shop"

    def test_a_project_node_is_drawn_without_its_digest(self) -> None:
        graph = _graph([_node(1, "Project", name="shop__1a2b3c4d")], [])
        assert build_view_data(graph, "shop")["nodes"][0]["name"] == "shop"

    def test_a_name_that_only_looks_like_a_digest_is_kept(self) -> None:
        graph = _graph([], [], projects=["my__project"])
        assert default_title(graph) == "my__project"

    def test_a_graph_without_projects_gets_a_generic_title(self) -> None:
        assert default_title(_graph([], [])) == cs.VIEWER_DEFAULT_TITLE


class TestPage:
    def test_the_page_embeds_the_graph_and_pins_orb(self) -> None:
        page = render_graph_html(SAMPLE)

        data = _embedded_data(page)
        assert data["title"] == "shop"
        assert {n["name"] for n in data["nodes"]} == {"shop", "checkout", "charge"}
        assert f'src="{cs.VIEWER_ORB_URL}"' in page
        assert f'integrity="{cs.VIEWER_ORB_SRI}"' in page
        assert "__CGR_" not in page

    def test_code_cannot_close_the_script_element(self) -> None:
        hostile = "</script><script>alert(1)</script><!-- &  "
        graph = _graph([_node(1, "Function", name=hostile, docstring=hostile)], [])

        page = render_graph_html(graph, title="<b>t</b>")

        assert page.count("</script>") == 3  # data, Orb, and the viewer's own
        assert "<script>alert(1)" not in page
        assert "<title>&lt;b&gt;t&lt;/b&gt; · code graph</title>" in page
        node = _embedded_data(page)["nodes"][0]
        assert node["name"] == hostile
        assert node["doc"] == hostile

    def test_each_filter_section_offers_show_all_and_hide_all(self) -> None:
        page = render_graph_html(SAMPLE)
        assert 'id="nodes-all"' in page and 'id="nodes-none"' in page
        assert 'id="edges-all"' in page and 'id="edges-none"' in page

    def test_a_placeholder_spelled_in_the_graph_is_left_alone(self) -> None:
        graph = _graph([_node(1, "Function", name=cs.VIEWER_PLACEHOLDER_ORB_URL)], [])
        assert (
            _embedded_data(render_graph_html(graph))["nodes"][0]["name"]
            == cs.VIEWER_PLACEHOLDER_ORB_URL
        )


class TestExport:
    def test_an_html_output_writes_the_page(self, tmp_path: Path) -> None:
        ingestor = MagicMock()
        ingestor.export_graph_to_dict.return_value = SAMPLE
        output = tmp_path / "out" / "graph.HTML"

        assert export_graph_to_file(ingestor, str(output))

        page = output.read_text(encoding="utf-8")
        assert page.startswith("<!doctype html>")
        assert _embedded_data(page)["title"] == "shop"

    def test_a_json_output_is_unchanged(self, tmp_path: Path) -> None:
        ingestor = MagicMock()
        ingestor.export_graph_to_dict.return_value = SAMPLE
        output = tmp_path / "graph.json"

        assert export_graph_to_file(ingestor, str(output))

        assert json.loads(output.read_text(encoding="utf-8")) == SAMPLE

    def test_only_the_html_suffix_selects_the_page(self) -> None:
        assert is_viewer_output(Path("g.html"))
        assert not is_viewer_output(Path("g.json"))
        assert not is_viewer_output(Path("g.htm.json"))
