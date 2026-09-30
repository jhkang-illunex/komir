from rag_core.ragkit.semantic_capabilities import (
    produced_outputs,
    validate_requested_outputs,
)
from rag_core.ragkit.semantic_intent import SemanticRequirement


def test_capability_outputs_are_derived_from_typed_requirements():
    requirements = [
        SemanticRequirement(domain="concept", metric="retrieve", mineral="니켈", topic="용도"),
        SemanticRequirement(domain="price", metric="current", mineral="니켈"),
    ]
    assert produced_outputs(requirements) == {"usage", "concept", "latest_price"}
    assert validate_requested_outputs(requirements, {"usage", "latest_price"}) is None


def test_output_coverage_does_not_inspect_raw_query():
    requirements = [SemanticRequirement(domain="concept", metric="retrieve", topic="가격 데이터가 없는 이유")]
    assert validate_requested_outputs(requirements, {"latest_price"}) == (
        "requested_output_not_produced:latest_price"
    )
