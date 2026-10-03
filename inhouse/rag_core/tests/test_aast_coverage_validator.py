from rag_core.ragkit.aast_coverage import _period_signature, validate_aast
from rag_core.ragkit.semantic_ir import SemanticProgram


def program(nodes, roots):
    return SemanticProgram.from_dict({"nodes": nodes, "roots": roots})


def retrieve(node_id, mineral, metric="price", domain="price", expected_type="time_series"):
    return {
        "node_id": node_id,
        "operator": "retrieve",
        "inputs": [],
        "args": {"domain": domain, "metric": metric, "mineral": mineral},
        "expected_type": expected_type,
    }


def test_entity_preservation_detects_wrong_mineral():
    report = validate_aast(
        [{"requirement_id": "r1", "action_id": "price.series", "mineral": "리튬", "metric": "price"}],
        program([retrieve("p", "graphite")], ["p"]),
    )
    assert not report.valid
    assert any(item.reason == "ENTITY_PRESERVATION_FAILED" for item in report.violations)


def test_capability_and_branch_coverage_detect_document_replaced_by_trade():
    report = validate_aast(
        [
            {"requirement_id": "trade", "action_id": "trade.country_rank", "mineral": "니켈", "metric": "country_rank"},
            {"requirement_id": "doc", "action_id": "document.retrieve", "topic": "월간동향"},
        ],
        program([retrieve("p", "니켈")], ["p"]),
    )
    reasons = {item.reason for item in report.violations}
    assert "CAPABILITY_SELECTION_MISMATCH" in reasons
    assert "BRANCH_COVERAGE_FAILED" in reasons


def test_trade_series_is_not_ranked_country_output():
    report = validate_aast(
        [{"requirement_id": "imports", "domain": "trade", "action_id": "trade.country_rank",
          "mineral": "리튬", "metric": "country_rank", "scope": "KR"}],
        program([{
            "node_id": "imports", "operator": "retrieve", "inputs": [],
            "args": {"domain": "trade", "metric": "import_value", "flow": "import", "scope": "KR", "mineral": "리튬"},
        }], ["imports"]),
    )
    assert not report.valid
    assert any(item.reason == "CAPABILITY_SELECTION_MISMATCH"
               and item.details["planned_output"] == "TradeTimeSeries"
               for item in report.violations)


def test_export_country_rank_preserves_ranked_country_output_contract():
    report = validate_aast(
        [{"requirement_id": "exports", "domain": "trade",
          "action_id": "trade.country_rank", "mineral": "흑연",
          "metric": "country_rank", "flow": "export", "scope": "GLOBAL"}],
        program([{
            "node_id": "exports", "operator": "retrieve", "inputs": [],
            "args": {"domain": "trade", "metric": "export_amount",
                     "operation": "country_rank", "flow": "export",
                     "scope": "GLOBAL", "mineral": "흑연"},
        }], ["exports"]),
    )
    assert report.valid


def test_period_preservation_is_typed():
    report = validate_aast(
        [{"requirement_id": "r1", "action_id": "price.series", "mineral": "니켈", "metric": "price",
          "period": {"kind": "calendar_year", "calendar_year": 2024}}],
        program([retrieve("p", "니켈")], ["p"]),
    )
    assert any(item.reason == "PERIOD_PRESERVATION_FAILED" for item in report.violations)


def test_period_signature_is_hashable_and_scalar_structured_equivalent():
    scalar = _period_signature("2024")
    structured = _period_signature({"kind": "calendar_year", "calendar_year": 2024})
    assert scalar == structured
    assert {scalar, structured} == {scalar}


def test_period_signature_normalizes_range_forms():
    assert _period_signature("2026-01-01..2026-03-31") == _period_signature(
        {"kind": "date_range", "from": "2026-01-01", "to": "2026-03-31"}
    )


def test_valid_single_capability_passes():
    report = validate_aast(
        [{"requirement_id": "r1", "action_id": "price.series", "mineral": "니켈", "metric": "price"}],
        program([retrieve("p", "니켈")], ["p"]),
    )
    assert report.valid


def test_inventory_series_metric_uses_series_capability_when_inventory_domain_is_typed():
    report = validate_aast(
        [{"requirement_id": "inventory", "domain": "inventory", "metric": "series",
          "action_id": "inventory.series", "mineral": "니켈",
          "period": {"kind": "trailing_months", "trailing_months": 12}}],
        program([{
            "node_id": "inventory", "operator": "retrieve", "inputs": [],
            "args": {"domain": "inventory", "metric": "inventory", "mineral": "니켈",
                     "period": {"kind": "trailing_months", "trailing_months": 12}},
        }], ["inventory"]),
    )
    assert report.valid


def test_resource_world_scope_and_canonical_entity_alias_are_equivalent():
    report = validate_aast(
        [{"requirement_id": "production", "domain": "resource",
          "metric": "resource_rank", "mineral": "희토류", "scope": "WORLD"}],
        program([{
            "node_id": "resource", "operator": "retrieve", "inputs": [],
            "args": {"domain": "resource", "metric": "production_volume",
                     "mineral": "rare_earth_elements"},
            "expected_type": "table",
        }], ["resource"]),
    )
    assert report.valid


def test_scope_uses_equivalent_typed_action_plan_binding():
    report = validate_aast(
        [{"requirement_id": "r1", "domain": "trade", "action_id": "trade.country_rank",
          "mineral": "니켈", "metric": "country_rank", "scope": "KR"}],
        program([retrieve("t", "니켈", metric="import_share", domain="trade")], ["t"]),
        canonical_plan={"actions": [{"action_id": "trade.country_rank",
                                      "slots": {"trade_scope": "korea"}}]},
    )
    assert report.valid


def test_trade_scope_accepts_downstream_country_filter_and_export_metric():
    report = validate_aast(
        [
            {"requirement_id": "imports", "domain": "trade", "metric": "country_rank",
             "flow": "import", "scope": "KR", "mineral": "코발트"},
            {"requirement_id": "exports", "domain": "trade", "metric": "country_rank",
             "flow": "export", "scope": "GLOBAL", "mineral": "코발트"},
        ],
        program([
            {"node_id": "imports", "operator": "retrieve", "inputs": [],
             "args": {"domain": "trade", "metric": "import_amount", "flow": "import", "mineral": "코발트"}},
            {"node_id": "kr", "operator": "filter", "inputs": [{"node_id": "imports"}],
             "args": {"predicate": {"field": "country", "operator": "equals", "value": "KR"}}},
            {"node_id": "exports", "operator": "retrieve", "inputs": [],
             "args": {"domain": "trade", "metric": "export_amount", "flow": "export", "mineral": "코발트"}},
        ], ["kr", "exports"]),
    )
    assert report.valid


def test_period_uses_equivalent_typed_action_plan_binding():
    report = validate_aast(
        [{"requirement_id": "r1", "action_id": "price.series", "mineral": "니켈",
          "metric": "price_series",
          "period": {"kind": "trailing_months", "trailing_months": 12}}],
        program([retrieve("p", "니켈", metric="price")], ["p"]),
        canonical_plan={"actions": [{"action_id": "price.series", "slots": {
            "period": {"kind": "trailing_months", "trailing_months": 12}
        }}]},
    )
    assert report.valid


def test_period_preservation_uses_matching_candidate_not_arbitrary_set_member():
    report = validate_aast(
        [{"requirement_id": "forecast", "action_id": "price.series",
          "domain": "price", "mineral": "니켈", "metric": "price_forecast",
          "period": {"kind": "future_horizon", "future_horizon": 1}}],
        program([
            retrieve("current", "니켈", metric="price"),
            {"node_id": "forecast", "operator": "retrieve", "inputs": [],
             "args": {"domain": "price", "metric": "price_forecast",
                      "period": {"kind": "future_horizon", "future_horizon": 1},
                      "mineral": "니켈"}, "expected_type": "time_series"},
        ], ["current", "forecast"]),
    )
    assert report.valid


def test_forecast_metric_uses_forecast_capability_when_domain_is_price():
    report = validate_aast(
        [{"requirement_id": "forecast", "domain": "price", "metric": "price_forecast",
          "mineral": "니켈", "period": {"kind": "future_horizon", "future_horizon": 1}}],
        program([{
            "node_id": "forecast", "operator": "retrieve", "inputs": [],
            "args": {"domain": "price", "metric": "price_forecast", "mineral": "니켈",
                     "period": {"kind": "future_horizon", "future_horizon": 1}},
            "expected_type": "time_series",
        }], ["forecast"]),
    )
    assert report.valid


def test_indicator_series_is_equivalent_to_indicator_capability_metric():
    report = validate_aast(
        [{"requirement_id": "indicator", "domain": "indicator", "metric": "series",
          "indicator": "composite_index",
          "period": {"kind": "trailing_months", "trailing_months": 1}}],
        program([{
            "node_id": "indicator", "operator": "retrieve", "inputs": [],
            "args": {"domain": "indicator", "metric": "indicator",
                     "indicator": "composite_index",
                     "period": {"kind": "trailing_months", "trailing_months": 1}},
            "expected_type": "time_series",
        }], ["indicator"]),
    )
    assert report.valid


def test_derived_resource_yoy_requires_and_accepts_temporal_operation():
    report = validate_aast(
        [{"requirement_id": "r1", "domain": "resource", "metric": "resource_yoy",
          "mineral": "니켈", "scope": "WORLD"}],
        program([
            {"node_id": "resource", "operator": "retrieve", "inputs": [],
             "args": {"domain": "resource", "metric": "production_volume", "mineral": "니켈"},
             "expected_type": "fact_set"},
            {"node_id": "yoy", "operator": "calculate", "inputs": [{"node_id": "resource"}],
             "args": {"calculation": "yoy"}, "expected_type": "fact_set"},
        ], ["yoy"]),
    )
    assert report.valid


def test_derived_resource_yoy_rejects_base_metric_without_temporal_operation():
    report = validate_aast(
        [{"requirement_id": "r1", "domain": "resource", "metric": "resource_yoy",
          "mineral": "니켈", "scope": "WORLD"}],
        program([retrieve("resource", "니켈", metric="production_volume", domain="resource")], ["resource"]),
    )
    assert any(item.reason == "METRIC_PRESERVATION_FAILED" for item in report.violations)


def test_resource_rank_is_a_production_default_at_typed_boundary():
    report = validate_aast(
        [{"requirement_id": "r1", "domain": "resource", "metric": "resource_rank",
          "mineral": "코발트", "scope": "WORLD"}],
        program([{
            "node_id": "resource", "operator": "retrieve", "inputs": [],
            "args": {"domain": "resource", "metric": "resource_rank", "mineral": "코발트"},
            "expected_type": "fact_set",
        }], ["resource"]),
    )
    assert report.valid


def test_saved_result_projection_does_not_require_physical_retrieve_capability():
    report = validate_aast(
        [{"requirement_id": "followup", "domain": "price", "metric": "price_series",
          "relation": "refine_previous", "context_ref": "previous_successful_price_series"}],
        program([
            {"node_id": "saved", "operator": "entity", "inputs": [],
             "args": {"values": [{"price": 10}], "entity": ["니켈"]},
             "expected_type": "time_series"},
            {"node_id": "project", "operator": "project", "inputs": [{"node_id": "saved"}],
             "args": {"fields": ["price"]}, "expected_type": "time_series"},
        ], ["project"]),
    )
    assert report.valid


def test_relation_without_two_inputs_is_rejected_before_execution():
    report = validate_aast(
        [{"requirement_id": "r1", "action_id": "price.compare", "minerals": ["니켈", "구리"], "metric": "price"}],
        _invalid_program([
            retrieve("p", "니켈"),
            retrieve("q", "구리"),
            {"node_id": "cmp", "operator": "join", "inputs": [{"node_id": "p"}, {"node_id": "q"}],
             "args": {}, "expected_type": "table"},
        ], ["cmp"]),
    )
    assert any(item.reason == "JOIN_CONTRACT_FAILED" for item in report.violations)


def _invalid_program(nodes, roots):
    # Feed a deliberately malformed graph to the validator without invoking
    # the production SemanticProgram constructor; the validator is the
    # pre-execution boundary under test.
    from rag_core.ragkit.semantic_ir import InputRef, RequirementNode, Operator, ValueType
    parsed = tuple(RequirementNode(
        node_id=item["node_id"], operator=Operator(item["operator"]),
        inputs=tuple(InputRef(**ref) for ref in item.get("inputs", [])),
        args=item.get("args", {}), expected_type=ValueType(item.get("expected_type", "unknown")),
    ) for item in nodes)
    instance = object.__new__(SemanticProgram)
    object.__setattr__(instance, "nodes", parsed)
    object.__setattr__(instance, "roots", tuple(roots))
    return instance
