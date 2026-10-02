import json
from pathlib import Path

import pytest


GOLD = Path(__file__).with_name("qa_build_set1_structured_gold_20261001.json")
METRICS = {
    "price": "price",
    "inventory": "inventory",
    "indicator": "indicator",
    "production": "production",
    "reserves": "reserves",
    "concentration": "concentration",
    "import_value": "import_value",
}


def _plan(case):
    from rag_core.ragkit.semantic_v2 import (
        EntityRef, Metric, SemanticRequirementPlanV2, SemanticRequirementV2,
        TimeRange,
    )

    tr = TimeRange.model_validate(case["period"]) if case["period"] else None
    return SemanticRequirementPlanV2(requirements=[SemanticRequirementV2(
        requirement_id=case["qa_id"],
        entity=EntityRef(value=case["entity"]),
        metric=Metric(METRICS[case["metric"]]),
        time_range=tr,
        indicator="composite_index" if case["metric"] == "indicator" else None,
    )])


def test_all_structured_gold_cases_have_complete_or_explicit_gap_metadata():
    data = json.loads(GOLD.read_text(encoding="utf-8"))
    assert data["total"] == 87
    assert len(data["cases"]) == 87
    for case in data["cases"]:
        assert case["source_id"] == "qa_build_set1"
        assert case["expected_operation_graph"]
        assert case["expected_ast_invariant"]
        assert case["expected_lowering_capability"]
        assert case["gold_status"] in {"GOLD_COMPLETE", "SEMANTIC_FIXTURE_GAP"}


@pytest.mark.parametrize("index", range(87))
def test_each_structured_gold_case_reaches_v2_ast_and_lowering(index):
    from rag_core.ragkit.semantic_v2 import LegacyActionLowerer, logical_program_from_requirements

    case = json.loads(GOLD.read_text(encoding="utf-8"))["cases"][index]
    if case["gold_status"] == "SEMANTIC_FIXTURE_GAP":
        pytest.skip("gold semantic fixture explicitly records an unsupported field gap")
    program = logical_program_from_requirements(_plan(case))
    calls = LegacyActionLowerer().lower(program)
    assert calls
    assert all(call.action_id in {
        "price.series", "trade.monthly", "trade.indicator", "trade.concentration",
        "resource.rank", "inventory.latest", "indicator.series",
    } for call in calls)
