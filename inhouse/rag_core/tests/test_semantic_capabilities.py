from rag_core.ragkit.semantic_capabilities import (
    capability_output_fields,
    produced_outputs,
    resolve_canonical_capability,
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


def test_surface_price_group_resolves_to_registered_overview_contract():
    resolved = resolve_canonical_capability(
        "price", "current", {"price_group": "strategic"}
    )
    assert resolved["action_id"] == "price.overview"
    assert set(resolved["canonical_args"]["strategic_price_groups"]) == {
        "strategic_six", "strategic_ten"
    }
    assert {"price", "date", "price_criterion"}.issubset(
        capability_output_fields("price", "current", {"price_group": "strategic"})
    )


def test_surface_inventory_latest_resolves_to_observation_contract():
    resolved = resolve_canonical_capability("inventory", "latest", {})
    assert resolved["action_id"] == "inventory.latest"
    assert {"value", "date", "unit"}.issubset(
        capability_output_fields("inventory", "latest", {})
    )


def test_existing_trade_country_rank_resolves_to_country_share_contract():
    resolved = resolve_canonical_capability(
        "trade", "import_share", {"flow": "import", "scope": "KR"}
    )
    assert resolved["action_id"] == "trade.country_rank"
    assert resolved["spec"]["output_type"] == "CountryShare"
    assert {"country", "share_percentage", "import_share"}.issubset(
        capability_output_fields("trade", "import_share", {})
    )


def test_existing_indicator_series_resolves_to_declared_typed_contract():
    resolved = resolve_canonical_capability("indicator", "series", {})
    assert resolved["action_id"] == "indicator.series"
    assert resolved["spec"]["output_type"] == "IndicatorSeries"
    assert {"indicator", "value", "date", "unit"}.issubset(
        capability_output_fields("indicator", "series", {})
    )


def test_existing_resource_capabilities_resolve_to_ranking_and_change_contracts():
    ranking = resolve_canonical_capability("resource", "production", {})
    assert ranking["action_id"] == "resource.rank"
    assert ranking["spec"]["output_type"] == "ResourceRanking"
    assert {"country", "production_volume", "year", "unit"}.issubset(
        capability_output_fields("resource", "production", {})
    )

    change = resolve_canonical_capability("resource", "resource_yoy", {})
    assert change["action_id"] == "resource.yoy"
    assert change["spec"]["output_type"] == "ResourceChange"
    assert {"prior_year", "year", "change_pct"}.issubset(
        capability_output_fields("resource", "resource_yoy", {})
    )
