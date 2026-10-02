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


def test_extremum_price_selection_produces_value_and_date():
    requirement = SemanticRequirement(
        domain="price", metric="price_series", mineral="니켈",
        period={"kind": "trailing_months", "trailing_months": 3},
        selection={"mode": "extremum", "direction": "max", "measure": "price",
                   "return_fields": ["value", "date"]},
    )
    assert validate_requested_outputs([requirement], {"latest_price", "date"}) is None


def test_bounded_inventory_legacy_latest_produces_series_output():
    requirement = SemanticRequirement(
        domain="inventory", metric="latest", mineral="니켈",
        period={"kind": "trailing_months", "trailing_months": 12},
    )
    assert validate_requested_outputs([requirement], {"inventory_series", "date"}) is None
