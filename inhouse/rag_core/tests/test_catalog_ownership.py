"""Freeze declaration ownership without conflating allowed and guaranteed outputs."""

from types import SimpleNamespace

import pytest

from inhouse.rag_core.ragkit import semantic_capabilities as catalog
from inhouse.rag_core.ragkit import semantic_ir as ir
from inhouse.rag_core.ragkit.capability_specs import indicator, inventory, price, resource, trade


PRICE_FIELDS = frozenset({
    "mineral", "price", "date", "unit", "price_criterion", "price_criterion_serial",
    "price_measure", "price_measure_label", "source", "provenance",
})
IDENTITY_FIELDS = ("price_measure", "price_criterion", "price_measure_label", "price_criterion_serial")
INVENTORY_OUTPUTS = frozenset({"inventory_series", "inventory", "date", "period", "unit"})
IR_CONTRACTS = [
    (indicator.INDICATOR_IR_FIELDS, ("indicator", "series"),
     {"indicator", "value", "date", "unit", "series"}),
    (price.PRICE_CHANGE_IR_FIELDS, ("price_change", "price_change_rate"),
     {"price_change", "price_change_rate", "pct_change", "change_pct", "date", "period"}),
    (trade.IMPORT_AMOUNT_IR_FIELDS, ("import_value", "import_amount"),
     {"import_value", "import_amount", "import_amount_change", "value", "country", "period", "unit"}),
    (trade.IMPORT_CHANGE_IR_FIELDS, ("import_change", "import_value_change"),
     {"import_change", "import_value_change", "import_amount_change", "change_pct", "country", "period", "unit"}),
    (resource.PRODUCTION_IR_FIELDS, ("production", "production_volume"),
     {"production", "production_volume", "value", "country", "country_code", "year", "period", "unit"}),
    (resource.RESERVES_IR_FIELDS, ("reserves", "reserves_volume"),
     {"reserves", "reserves_volume", "value", "country", "country_code", "year", "period", "unit"}),
]


def test_price_and_inventory_constants_keep_exact_values_types_and_identity_order():
    assert price.PRICE_ALLOWED_OUTPUT_FIELDS == PRICE_FIELDS
    assert isinstance(price.PRICE_ALLOWED_OUTPUT_FIELDS, frozenset)
    assert price.PRICE_IDENTITY_FIELDS == IDENTITY_FIELDS
    assert isinstance(price.PRICE_IDENTITY_FIELDS, tuple)
    assert price.PRICE_CRITERION_MODES == frozenset({"REPRESENTATIVE", "EXPLICIT", "ALL"})
    assert isinstance(price.PRICE_CRITERION_MODES, frozenset)
    assert inventory.INVENTORY_SERIES_SEMANTIC_OUTPUTS == INVENTORY_OUTPUTS
    assert isinstance(inventory.INVENTORY_SERIES_SEMANTIC_OUTPUTS, frozenset)


@pytest.mark.parametrize("constant,aliases,expected", IR_CONTRACTS, ids=lambda item: str(item) if isinstance(item, tuple) else None)
def test_each_ir_constant_matches_both_original_mutable_alias_sets(constant, aliases, expected):
    assert isinstance(constant, frozenset) and constant == expected
    first, second = (ir._METRIC_FIELDS[key] for key in aliases)
    assert type(first) is set and type(second) is set
    assert first == second == expected
    assert first is not second and first is not constant and second is not constant


@pytest.mark.parametrize("constant,aliases,expected", IR_CONTRACTS)
@pytest.mark.parametrize("index", [0, 1])
def test_mutating_one_ir_alias_does_not_mutate_other_aliases_or_owner(constant, aliases, expected, index):
    snapshot = {key: set(value) for key, value in ir._METRIC_FIELDS.items()}
    target = ir._METRIC_FIELDS[aliases[index]]
    try:
        target.add("__ownership_probe__")
        target.remove(next(iter(expected)))
        assert constant == expected
        assert all(fields == snapshot[key] for key, fields in ir._METRIC_FIELDS.items() if key != aliases[index])
    finally:
        target.clear()
        target.update(snapshot[aliases[index]])
    assert ir._METRIC_FIELDS == snapshot


def test_catalog_and_ir_key_insertion_order_is_unchanged():
    assert list(catalog.CAPABILITY_ARGUMENTS) == [
        "price.overview", "price.series", "inventory.latest", "inventory.series",
        "indicator.series", "resource.rank", "resource.yoy", "trade.country_rank",
    ]
    assert list(catalog.CAPABILITY_OUTPUTS) == [
        ("concept", "retrieve"), ("document", "retrieve"), ("price", "current"),
        ("price", "price_series"), ("trade", "country_rank"), ("resource", "resource_rank"),
        ("inventory", "latest"), ("inventory", "series"), ("inventory", "inventory_series"),
        ("resource", "resource_yoy"), ("indicator", "series"),
    ]
    assert list(ir._METRIC_FIELDS) == [
        "inventory", "indicator", "series", "price", "price_change", "price_change_rate",
        "price_volatility", "import_value", "import_amount", "import_change", "import_value_change",
        "import_share", "country_share", "country_rank", "production", "production_volume",
        "reserves", "reserves_volume",
    ]


@pytest.mark.parametrize("action_id,metric,output_type", [
    ("price.overview", "current", "PriceOverview"), ("price.series", "price_series", "PriceSeries"),
])
def test_price_catalog_entries_keep_all_original_keys_values_and_order(action_id, metric, output_type):
    expected = {
        "domain": "price", "metric": metric, "canonical_metric": "price",
        "output_type": output_type, "criterion_modes": frozenset({"REPRESENTATIVE", "EXPLICIT", "ALL"}),
        "identity_fields": IDENTITY_FIELDS,
    }
    if action_id == "price.overview":
        expected["required"] = frozenset({"price_group"})
    expected["output_fields"] = PRICE_FIELDS
    if action_id == "price.overview":
        expected["group_map"] = {
            "strategic": ("strategic_six", "strategic_ten"), "strategic_six": ("strategic_six",),
            "strategic_ten": ("strategic_ten",), "battery_five": ("battery_five",),
        }
    actual = catalog.capability_spec(action_id)
    assert actual == expected and list(actual) == list(expected)
    if "group_map" in expected:
        assert list(actual["group_map"]) == list(expected["group_map"])


@pytest.mark.parametrize("metric", ["current", "price_series"])
@pytest.mark.parametrize("mode", ["REPRESENTATIVE", "EXPLICIT", "ALL", "all", "all_criteria", None])
def test_price_allowed_fields_do_not_become_mode_specific_guarantees_or_mode_validation(metric, mode):
    resolved = catalog.resolve_canonical_capability("price", metric, {"criterion_mode": mode})
    assert resolved["output_fields"] == PRICE_FIELDS and resolved["canonical_args"] == {}
    # Field allowance is not proof of an observed row or a produced semantic output.
    requirement = SimpleNamespace(domain="price", metric=metric)
    assert catalog.produced_outputs([requirement]) == ({"latest_price"} if metric == "current" else {"price_series"})
    assert catalog.validate_requested_outputs([requirement], {"price_criterion_serial"}) == (
        "requested_output_not_produced:price_criterion_serial")


@pytest.mark.parametrize("metric,expected", [(None, IDENTITY_FIELDS), ("price", IDENTITY_FIELDS),
                                            (" PRICE ", IDENTITY_FIELDS), ("current", ()), ("price_series", ())])
def test_identity_lookup_uses_canonical_metric_not_surface_alias(metric, expected):
    assert catalog.capability_identity_fields(" PRICE ", metric) == expected


@pytest.mark.parametrize("domain,metric", [
    ("price", "price"), ("price", "series"), ("price", "latest"),
    ("indicator", "indicator_series"), ("resource", "production_volume"),
    ("trade", "export_share"), ("trade", "import_amount"),
    ("inventory", "trend"), ("inventory", "time_series"), ("inventory", "inventory_series"),
])
def test_catalog_surface_aliases_are_not_expanded_by_constant_extraction(domain, metric):
    assert catalog.resolve_canonical_capability(domain, metric) is None
    assert catalog.capability_output_fields(domain, metric) == frozenset()


def test_catalog_fields_remain_distinct_from_ir_fallback_and_semantic_outputs():
    price_fields = catalog.capability_output_fields("price", "price_series")
    assert "value" not in price_fields and "value" in ir._METRIC_FIELDS["price"]
    assert "cmerc_prc" not in price_fields and "cmerc_prc" in ir._METRIC_FIELDS["price"]
    assert "provenance" in price_fields and "provenance" not in ir._METRIC_FIELDS["price"]
    indicator_fields = catalog.capability_output_fields("indicator", "series")
    assert indicator_fields == {"indicator", "value", "date", "period", "unit", "source", "provenance"}
    assert "series" not in indicator_fields and "series" in indicator.INDICATOR_IR_FIELDS
    assert "period" in indicator_fields and "period" not in indicator.INDICATOR_IR_FIELDS
    production_fields = catalog.capability_output_fields("resource", "production")
    assert "reserves_volume" in production_fields and "reserves_volume" not in resource.PRODUCTION_IR_FIELDS
    assert "production_volume" not in resource.RESERVES_IR_FIELDS
    inventory_fields = catalog.capability_output_fields("inventory", "series")
    assert "value" in inventory_fields and "value" not in INVENTORY_OUTPUTS
    assert "inventory_series" in INVENTORY_OUTPUTS and "inventory_series" not in inventory_fields


@pytest.mark.parametrize("domain,metric,field,allowed", [
    ("price", "price_series", "value", False), (None, "price_series", "value", True),
    ("price", "price_series", "price_criterion_serial", True),
    (None, "price_series", "price_criterion_serial", True),
    ("indicator", "series", "series", False), (None, "series", "series", True),
    ("indicator", "series", "period", True), (None, "series", "period", False),
    ("resource", "production", "reserves_volume", True),
    (None, "production", "reserves_volume", False),
])
def test_ir_field_validation_keeps_catalog_first_then_fallback(domain, metric, field, allowed):
    nodes = (
        ir.RequirementNode("source", ir.Operator.RETRIEVE, args={"domain": domain, "metric": metric}),
        ir.RequirementNode("project", ir.Operator.PROJECT, (ir.InputRef("source"),), {"fields": [field]}),
    )
    if allowed:
        assert ir.SemanticProgram(nodes, ("project",)).completeness_issues() == ()
    else:
        with pytest.raises(ValueError) as error:
            ir.SemanticProgram(nodes, ("project",))
        assert str(error.value).startswith(
            f"ast_incomplete: project requires field(s) ['{field}'] not produced by upstream;")


@pytest.mark.parametrize("metric", ["series", "inventory_series"])
def test_both_inventory_semantic_table_entries_keep_the_frozen_series_contract(metric):
    assert catalog.CAPABILITY_OUTPUTS[("inventory", metric)] == INVENTORY_OUTPUTS
    outputs = catalog.produced_outputs([SimpleNamespace(domain="inventory", metric=metric)])
    assert isinstance(outputs, frozenset) and outputs == INVENTORY_OUTPUTS
    assert "latest_inventory" not in outputs


@pytest.mark.parametrize("kind,bounded", [
    ("trailing_months", True), ("range", True), ("calendar_year", True),
    ("latest", False), ("future_horizon", False), ("RANGE", False), (None, False),
])
@pytest.mark.parametrize("as_mapping", [False, True])
def test_bounded_inventory_latest_adds_series_outputs_without_removing_latest(kind, bounded, as_mapping):
    period = {"kind": kind} if as_mapping else SimpleNamespace(kind=kind)
    requirement = SimpleNamespace(domain="inventory", metric="latest", period=period)
    expected = {"latest_inventory", "inventory"} | (set(INVENTORY_OUTPUTS) if bounded else set())
    assert catalog.produced_outputs([requirement]) == expected
    assert catalog.validate_requested_outputs([requirement], {"inventory_series"}) == (
        None if bounded else "requested_output_not_produced:inventory_series")
    # Produced outputs and catalog lookup retain their separate contracts.
    resolved = catalog.resolve_canonical_capability("inventory", "latest", {"period": {"kind": kind}})
    assert resolved["action_id"] == "inventory.latest"
    assert "period" not in resolved["output_fields"]


@pytest.mark.parametrize("period", [None, {}, SimpleNamespace()])
def test_missing_inventory_period_does_not_imply_series(period):
    requirement = SimpleNamespace(domain="inventory", metric="latest", period=period)
    assert catalog.produced_outputs([requirement]) == {"latest_inventory", "inventory"}


@pytest.mark.parametrize("domain,metric", [("Inventory", "latest"), ("inventory", "LATEST"), ("inventory", "trend")])
def test_produced_outputs_does_not_gain_catalog_string_normalization(domain, metric):
    requirement = SimpleNamespace(domain=domain, metric=metric, period={"kind": "range"})
    assert catalog.produced_outputs([requirement]) == frozenset()


def test_requested_output_aliases_and_sorted_missing_diagnostics_stay_bounded():
    requirement = SimpleNamespace(domain="price", metric="current")
    assert catalog.validate_requested_outputs([requirement], {"current_price"}) is None
    assert catalog.validate_requested_outputs([requirement], {"price", "current", "date"}) == (
        "requested_output_not_produced:current,date,price")
