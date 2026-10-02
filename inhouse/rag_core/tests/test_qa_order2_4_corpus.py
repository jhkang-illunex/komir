"""Generated question corpus integrity, NOT Gemma/backend success tests."""
import json
import re
from collections import Counter
from pathlib import Path


HERE = Path(__file__).parent
CORPUS = json.loads((HERE / "qa_build_order2_4_500.json").read_text())
CASES = CORPUS["cases"]


def normalized(text):
    return re.sub(r"[\s?.,!]", "", text)


def test_counts_ids_and_orders():
    assert len(CASES) == CORPUS["total"] == 500
    assert len({c["id"] for c in CASES}) == 500
    assert Counter(c["order"] for c in CASES) == {
        "2nd-order": 160, "3rd-order": 180, "4th-order": 160,
    }
    patterns = Counter(c["pattern_id"] for c in CASES)
    assert len(patterns) == 125
    assert set(patterns.values()) == {4}


def test_no_exact_source_or_generated_duplicate():
    source = json.loads((HERE / "qa_build_corpus_set1_20261001.json").read_text())
    old = {normalized(c["question"]) for c in source["cases"]}
    new = {normalized(c["question"]) for c in CASES}
    assert len(new) == 500
    assert not old.intersection(new)
    source_ids = {c["id"] for c in source["cases"]}
    assert all(c["source_id"] in source_ids for c in CASES)


def test_all_have_design_invariants_but_no_fabricated_execution_result():
    for c in CASES:
        assert len(c["operation_graph"]) >= 3
        assert c["semantic_requirement"]["metrics"]
        assert c["expected_ast"]["invariant"] == c["result_invariant"]
        assert c["expected_lowering"]["capability_availability"] == "NOT_ASSESSED"
        assert c["validation"] == {
            "corpus_registered": True, "parser_executed": False,
            "backend_executed": False, "semantic_result_status": "NOT_EXECUTED",
        }
        assert c["expected_result"] is None
        assert not re.search(r"\{[a-z_]+\}", c["question"])


def test_multiturn_is_preserved_as_conversations():
    multi = [c for c in CASES if len(c["turns"]) > 1]
    assert len(multi) == CORPUS["multiturn_scenarios"] == 40
    assert sum(len(c["turns"]) for c in CASES) == CORPUS["utterance_count"] == 580
    for c in multi:
        assert len(c["turns"]) == 3
        assert [t["turn"] for t in c["turns"]] == [1, 2, 3]
        assert "MULTITURN_STATE_REQUIRED" in c["semantic_requirement"]["dependency_requirements"]
        assert "ResultRef" in " ".join(c["operation_graph"]) or "Snapshot" in " ".join(c["operation_graph"])
        for turn in c["turns"]:
            assert turn["question"] in c["question"]


def test_plain_text_matches_registered_cases():
    root = HERE.parents[2]
    lines = (root / "qa_build_order2_4_500.txt").read_text().splitlines()
    assert len(lines) == 500
    for line, c in zip(lines, CASES):
        assert line == f"[{c['id']}][ORDER-{c['order'][0]}][{c['tags'][0]}] {c['question']}"


def test_authored_patterns_are_all_represented():
    lines = [line for line in (HERE / "qa_order2_4_patterns.tsv").read_text().splitlines()
             if line and not line.startswith("#")]
    assert len(lines) == 125
    for index, line in enumerate(lines, 1):
        order, family, source, metrics, graph, invariant, template = line.split("|", 6)
        group = [c for c in CASES if c["pattern_id"] == f"PAT-{index:03d}"]
        assert len(group) == 4
        for c in group:
            assert c["source_id"] == f"SET1-{source}"
            assert c["order"].startswith(order)
            assert c["tags"][0] == family
            assert c["operation_graph"] == graph.split(">")
            assert c["semantic_requirement"]["metrics"] == metrics.split(",")
            assert invariant and template
