from __future__ import annotations

import json

from rag_core.retrieval import pageindex


def test_no_summary_tree_searches_actual_node_body(tmp_path):
    trees_root = tmp_path / "trees"
    okf_root = tmp_path / "okf"
    trees_root.mkdir()
    okf_root.mkdir()
    (okf_root / "sample.md").write_text(
        "# FOREWORD\nEstimated world lithium production increased to 290,000 tons in 2025.\n"
        "# OTHER\nUnrelated text.\n",
        encoding="utf-8",
    )
    tree = {
        "doc_id": "doc_sample",
        "title": "Annual report",
        "doc_name": "sample",
        "source_group": "public",
        "okf_path": "sample.md",
        "resource": "sample.pdf",
        "body_line_offset": 0,
        "structure": [
            {"node_id": "n1", "title": "FOREWORD", "line_num": 1, "nodes": []},
            {"node_id": "n2", "title": "OTHER", "line_num": 3, "nodes": []},
        ],
    }
    (trees_root / "sample.tree.json").write_text(json.dumps(tree), encoding="utf-8")
    pageindex.reload_trees()

    hits = pageindex.search_nodes(
        "lithium production 2025",
        doc="doc_sample",
        node_limit=1,
        trees_root=trees_root,
        okf_root=okf_root,
    )

    assert [hit["node_id"] for hit in hits] == ["n1"]
    assert pageindex.read_node_text(hits[0], okf_root=okf_root).startswith("# FOREWORD")


def test_body_span_finds_fact_after_a_shallow_root_node(tmp_path):
    trees_root = tmp_path / "trees"
    okf_root = tmp_path / "okf"
    trees_root.mkdir()
    okf_root.mkdir()
    (okf_root / "report.md").write_text(
        "# Report\nintro\n# Metals\nother section\n"
        "##### Nickel\nLithium battery demand grows from 342,000 tons to 868,000 tons.\n",
        encoding="utf-8",
    )
    tree = {
        "doc_id": "report", "title": "Market report", "doc_name": "report",
        "source_group": "public", "okf_path": "report.md", "resource": "report.pdf",
        "content_keywords": ["lithium", "battery", "demand"],
        "body_line_offset": 0,
        "structure": [{"node_id": "root", "title": "Report", "line_num": 1, "nodes": []}],
    }
    (trees_root / "report.tree.json").write_text(json.dumps(tree), encoding="utf-8")
    pageindex.reload_trees()

    result = pageindex.lookup(
        "lithium battery demand", node_limit=1,
        trees_root=trees_root, okf_root=okf_root,
    )

    assert result["nodes"][0]["node_id"] == "body-span-6"
    assert "342,000 tons to 868,000 tons" in result["nodes"][0]["text"]
