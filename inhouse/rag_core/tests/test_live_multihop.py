from inhouse.rag_core.tests.registered_step_helpers import execute_registered
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from inhouse.rag_core.ragkit import live_multihop
from inhouse.rag_core.ragkit.indicator_result_adapter import canonical_indicator_rows
from inhouse.rag_core.ragkit.trade_rank_result_adapter import canonicalize_trade_rank_rows
from inhouse.rag_core.ragkit.action_contract import ActionPlan
from inhouse.rag_core.ragkit.action_results import ActionResult, RetrievalResult
from inhouse.rag_core.ragkit.history_context import ConversationContext, Turn, UserUtterance
from inhouse.rag_core.ragkit.pipe_runtime import ExecutionResult, ResultStatus, TypedResult
from inhouse.rag_core.ragkit.semantic_ir import InputRef, Operator, RequirementNode, SemanticProgram, ValueType
from inhouse.rag_core.ragkit.aast_coverage import CoverageReport, CoverageViolation
from inhouse.rag_core.retrieval.evidence import Evidence


class LiveMultiHopBridgeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        live_multihop.clear_semantic_cache()

    def test_trade_rank_total_column_is_normalized_to_declared_measure(self):
        rows = canonicalize_trade_rank_rows(
            [{"country": "중국", "total(수입금액합계(USD))": 12.5}],
            "import_amount", base_column_name=live_multihop._base_column_name,
        )
        self.assertEqual(rows[0]["import_amount"], 12.5)
        self.assertEqual(rows[0]["total(수입금액합계(USD))"], 12.5)

    def test_indicator_rows_normalize_source_date_to_canonical_date(self):
        action = SimpleNamespace(slots=SimpleNamespace(indicator="composite_index"))
        rows = canonical_indicator_rows(
            [{"crtr_ymd": "20261001", "indx": "123.4"}], action,
            resolve_field=live_multihop._resolve_row_field, numeric=live_multihop._numeric,
        )
        self.assertEqual(rows[0]["date"], "2026-10-01")
        self.assertEqual(rows[0]["value"], 123.4)

    def test_indicator_rows_resolve_display_labeled_source_columns(self):
        action = SimpleNamespace(slots=SimpleNamespace(indicator="composite_index"))
        rows = canonical_indicator_rows(
            [{"crtr_ymd(기준일자)": "20260905", "indx(지수)": "3651.45"}], action,
            resolve_field=live_multihop._resolve_row_field, numeric=live_multihop._numeric,
        )
        self.assertEqual(rows[0]["date"], "2026-09-05")
        self.assertEqual(rows[0]["value"], 3651.45)

    def test_trade_rank_does_not_guess_from_multiple_total_columns(self):
        rows = canonicalize_trade_rank_rows(
            [{"country": "중국", "total(import)": 12.5, "total(weight)": 2.0}],
            "import_amount", base_column_name=live_multihop._base_column_name,
        )
        self.assertNotIn("import_amount", rows[0])

    def test_history_alias_is_materialized_from_latest_typed_root(self):
        typed = TypedResult.success(ValueType.MINERAL_SET, [{"광종": "니켈"}], entity=("니켈",))
        previous = Turn(
            "turn-1",
            "session-1",
            UserUtterance("니켈 가격"),
            semantic_program=SemanticProgram(
                (RequirementNode("root", Operator.ENTITY, args={"values": ["니켈"]}),),
                ("root",),
            ),
            result=ExecutionResult("pipe-1", ResultStatus.SUCCESS, {"root": typed}, ()),
        )
        payload = {
            "nodes": [{"node_id": "next", "operator": "retrieve", "inputs": [{"node_id": "previous"}]}],
            "roots": ["next"],
        }

        normalized = live_multihop._normalize_history_aliases(payload, ConversationContext("session-1", (previous,)))
        program = SemanticProgram.from_dict(normalized)

        next_node = next(node for node in program.nodes if node.node_id == "next")
        bound_id = live_multihop._history_node_id("history:turn-1:root")
        self.assertEqual(next_node.inputs[0].node_id, bound_id)
        self.assertTrue(any(node.node_id == bound_id and node.operator == Operator.ENTITY for node in program.nodes))

    def test_history_requirement_materializes_only_missing_slots(self):
        typed = TypedResult.success(
            ValueType.TIME_SERIES, [{"date": "2026-10-01", "price": 10}],
            entity=("니켈",), period={"kind": "trailing_months", "trailing_months": 12},
            evidence=(Evidence("structured", "fixture", "fixture", "price=10"),),
        )
        previous = Turn(
            "turn-1", "session-1", UserUtterance("니켈 최근 1년 가격"),
            semantic_program=SemanticProgram(
                (RequirementNode("root", Operator.RETRIEVE),), ("root",),
            ),
            result=ExecutionResult("pipe-1", ResultStatus.SUCCESS, {"root": typed}, ()),
        )
        requirements = [{
            "domain": "price", "metric": "price_series", "relation": "refine_previous",
            "context_ref": "previous_successful_price_series",
            "period": {"kind": "trailing_months", "trailing_months": 3},
        }]
        materialized, bindings, failure = live_multihop._materialize_history_requirements(
            requirements, ConversationContext("session-1", (previous,)),
        )
        self.assertIsNone(failure)
        self.assertEqual(materialized[0]["mineral"], "니켈")
        self.assertEqual(materialized[0]["period"]["trailing_months"], 3)
        self.assertEqual(materialized[0]["relation"], "independent")
        self.assertEqual(materialized[0]["context_ref"], None)
        self.assertEqual(bindings[0]["inherited_fields"], ["mineral"])

    def test_legacy_followup_alias_passes_live_validator_with_in_progress_turn(self):
        typed = TypedResult.success(
            ValueType.TIME_SERIES, [{"price": 10, "date": "2026-10-01"}],
            entity=("니켈",),
            evidence=(Evidence("structured", "fixture", "fixture", "price=10"),),
        )
        previous = Turn(
            "turn-1", "session-1", UserUtterance("니켈 현재 가격"),
            semantic_program=None,
            result=ExecutionResult("legacy-turn-1", ResultStatus.SUCCESS, {"current_price": typed}, ()),
        )
        in_progress = Turn("turn-2", "session-1", UserUtterance("후속"), result=None)
        context = ConversationContext("session-1", (previous, in_progress))
        payload = {
            "result_access": "reference",
            "reference_scope": "active",
            "nodes": [{"node_id": "project_price", "operator": "project",
                       "inputs": [{"node_id": "result:turn-1:legacy"}],
                       "args": {"fields": ["price"], "aliases": {"price": "price"}}}],
            "roots": ["project_price"],
        }
        model = live_multihop.ASTProgramModel.model_validate(payload)
        program = SemanticProgram.from_dict(live_multihop._normalize_history_aliases(payload, context))
        live_multihop._validate_live_contract(program, model, context)

    def test_parser_root_is_normalized_to_terminal_dependency_node(self):
        program = SemanticProgram.from_dict({
            "nodes": [
                {"node_id": "rank", "operator": "rank"},
                {"node_id": "top", "operator": "top_k", "inputs": [{"node_id": "rank"}]},
                {"node_id": "answer", "operator": "arg_max", "inputs": [{"node_id": "top"}]},
            ],
            "roots": ["rank"],
        })

        self.assertEqual(program.roots, ("answer",))

    def test_bounded_repair_promotes_trade_series_to_country_rank(self):
        payload = {
            "nodes": [
                {"node_id": "imports", "operator": "retrieve", "inputs": [],
                 "args": {"domain": "trade", "metric": "import_value", "flow": "import", "scope": "KR", "mineral": "리튬"}},
                {"node_id": "rank", "operator": "rank", "inputs": [{"node_id": "imports"}],
                 "args": {"field": "import_value"}},
            ],
            "roots": ["rank"],
        }
        requirements = [{"requirement_id": "imports", "domain": "trade",
                         "action_id": "trade.country_rank", "metric": "country_rank",
                         "scope": "KR", "mineral": "리튬"}]
        report = live_multihop.validate_aast(requirements, live_multihop.SemanticProgram.from_dict(payload))
        self.assertFalse(report.valid)
        repaired = live_multihop._deterministic_coverage_repair(payload, report, requirements)
        self.assertIsNotNone(repaired)
        retrieve = next(node for node in repaired.nodes if node.node_id == "imports")
        rank = next(node for node in repaired.nodes if node.node_id == "rank")
        self.assertEqual(retrieve.args["metric"], "import_amount")
        self.assertEqual(retrieve.args["operation"], "country_rank")
        self.assertEqual(rank.args["field"], "import_amount")

    def test_ast_rejects_downstream_filter_field_missing_from_upstream(self):
        with self.assertRaisesRegex(ValueError, "ast_incomplete:.*import"):
            SemanticProgram.from_dict({
                "nodes": [
                    {"node_id": "entities", "operator": "entity", "args": {"values": ["니켈"]}},
                    {
                        "node_id": "filtered", "operator": "filter",
                        "inputs": [{"node_id": "entities"}],
                        "args": {"metric": "import_change", "predicate": "greater_than", "value": 0},
                    },
                ],
                "roots": ["filtered"],
            })

    def test_volatility_document_field_reference_is_complete(self):
        program = SemanticProgram.from_dict({
            "nodes": [
                {"node_id": "prices", "operator": "retrieve", "args": {"metric": "price_change"}},
                {"node_id": "ranked", "operator": "sort", "inputs": [{"node_id": "prices"}], "args": {"field": "price_change"}},
                {"node_id": "news", "operator": "retrieve_document", "inputs": [{"node_id": "ranked", "selector": "field", "selector_value": "mineral"}], "args": {"topic": "news"}},
            ],
            "roots": ["news"],
        })
        self.assertEqual(program.completeness_issues(), ())

    def test_trade_metadata_fields_are_available_to_downstream_projection(self):
        program = SemanticProgram.from_dict({
            "nodes": [
                {"node_id": "imports", "operator": "retrieve", "args": {"metric": "import_amount"}},
                {
                    "node_id": "country_share", "operator": "project",
                    "inputs": [{"node_id": "imports"}],
                    "args": {"fields": ["country", "period", "unit", "import_amount"]},
                },
            ],
            "roots": ["country_share"],
        })

        self.assertEqual(program.completeness_issues(), ())

    def test_annotated_price_columns_match_canonical_projection_fields(self):
        # Physical table adapters may annotate display labels on a canonical
        # column name.  The semantic contract compares the field identity,
        # not the display suffix.
        program = SemanticProgram.from_dict({
            "nodes": [
                {"node_id": "prices", "operator": "retrieve",
                 "args": {"metric": "price"}},
                {"node_id": "table", "operator": "project",
                 "inputs": [{"node_id": "prices"}],
                 "args": {"fields": ["cmerc_prc", "hghst_prc", "lowst_prc"],
                          "aliases": {"cmerc_prc": "cmerc_prc(통상가격)",
                                      "hghst_prc": "hghst_prc(최고가격)",
                                      "lowst_prc": "lowst_prc(최저가격)"}}},
            ],
            "roots": ["table"],
        })
        self.assertEqual(program.completeness_issues(), ())

    def test_price_series_capability_name_exposes_all_criterion_fields(self):
        # The live AST may use the capability-qualified metric name while the
        # row contract is keyed by canonical ``price``.  ALL criterion output
        # must therefore retain every source criterion identity field.
        program = SemanticProgram.from_dict({
            "nodes": [
                {"node_id": "prices", "operator": "retrieve",
                 "args": {"domain": "price", "metric": "price.series",
                          "criterion_mode": "ALL"}},
                {"node_id": "table", "operator": "project",
                 "inputs": [{"node_id": "prices"}],
                 "args": {"fields": [
                     "date", "price", "price_measure_label",
                     "price_criterion", "price_criterion_serial",
                 ], "aliases": {field: field for field in (
                     "date", "price", "price_measure_label",
                     "price_criterion", "price_criterion_serial",
                 )}}},
            ],
            "roots": ["table"],
        })
        self.assertEqual(program.completeness_issues(), ())

    def test_price_projection_preserves_registry_identity_when_ast_requests_core_fields(self):
        source = TypedResult.success(
            ValueType.TIME_SERIES,
            [{"date": "2026-10-01", "price": 10, "price_criterion": "LME CASH"}],
            entity=("니켈",),
            metric="price",
        )
        node = RequirementNode(
            node_id="project", operator=Operator.PROJECT,
            inputs=(InputRef("source"),), args={"fields": ["mineral", "price", "date"]},
        )

        result = execute_registered(object.__new__(live_multihop.LiveOperatorFactory), node, {"source": source})

        self.assertEqual(result.status.value, "success")
        self.assertEqual(result.value[0]["price_criterion"], "LME CASH")
        self.assertEqual(list(result.value[0]), [
            "mineral", "price", "date", "price_criterion", "price_measure_label",
        ])

    def test_ast_rejects_non_numeric_top_k_but_preserves_leaf_calculation_contract(self):
        with self.assertRaisesRegex(ValueError, "invalid top_k limit"):
            SemanticProgram.from_dict({
                "nodes": [{"node_id": "top", "operator": "top_k", "args": {"top_n": "unknown"}}],
                "roots": ["top"],
            })
        program = SemanticProgram.from_dict({
            "nodes": [{"node_id": "change", "operator": "calculate", "args": {"metric": "import_change"}}],
            "roots": ["change"],
        })
        self.assertEqual(program.roots, ("change",))

    def test_source_unavailable_result_maps_to_empty_without_contract_error(self):
        call = live_multihop.ActionCall(
            requirement_id="r1",
            action_id="price.series",
            slots=live_multihop.ActionSlots(mineral="니켈"),
        )
        evidence = Evidence("structured", "fixture", "fixture", "| 상태 | 값 |\n| --- | --- |\n| unavailable | - |")
        raw = RetrievalResult(
            ActionPlan(actions=[call]),
            [ActionResult("r1", "price.series", call.slots, "source_unavailable", [evidence])],
            [evidence],
            [],
        )

        result = live_multihop._typed_from_retrieval(raw, call, input_entities=[])

        self.assertEqual(result.status.value, "empty")
        self.assertEqual(result.failure_reason, "retrieval unavailable: source_unavailable")

    def test_semantic_metrics_lower_to_existing_actions_without_domain(self):
        price = RequirementNode(
            "price",
            Operator.RETRIEVE,
            args={"metric": "price_change_rate"},
            expected_type=ValueType.MINERAL_RANKING,
        )
        imports = RequirementNode(
            "imports",
            Operator.RETRIEVE,
            args={"metric": "import_value"},
            expected_type=ValueType.TRADE_SERIES,
        )

        self.assertEqual(live_multihop._action_id(price), "price.volatility_rank")
        self.assertEqual(live_multihop._action_id(imports), "trade.monthly")
        self.assertIsNone(live_multihop._action_slots(price).metric)
        self.assertEqual(live_multihop._action_slots(imports).metric, "import_amount")
        self.assertEqual(live_multihop._action_slots(price, mineral="nickel").mineral, "니켈")
        self.assertIsNone(live_multihop._action_slots(RequirementNode("price_query", Operator.RETRIEVE, args={"metric": "price"})).metric)

    def test_registry_surface_arguments_survive_slot_normalization(self):
        strategic = RequirementNode(
            "strategic", Operator.RETRIEVE,
            args={"domain": "price", "metric": "current", "price_group": "strategic"},
        )
        inventory = RequirementNode(
            "inventory", Operator.RETRIEVE,
            args={"domain": "inventory", "metric": "latest"},
        )
        self.assertEqual(live_multihop._action_id(strategic), "price.overview")
        self.assertEqual(
            live_multihop._action_slots(strategic).strategic_price_groups,
            ["strategic_six", "strategic_ten"],
        )
        self.assertEqual(live_multihop._action_id(inventory), "inventory.latest")
        self.assertIsNone(live_multihop._action_slots(inventory).metric)

    def test_price_output_contract_accepts_canonical_criterion_for_label(self):
        self.assertEqual(
            live_multihop._resolve_row_field(
                [{"price_criterion": "LME CASH"}], "price_measure_label", strict=True
            ),
            "price_criterion",
        )

    def test_price_overview_treats_missing_serial_as_optional_identity(self):
        rows = [{"price_measure": "cash", "price_criterion": "LME CASH"}]
        self.assertIsNone(
            live_multihop._resolve_row_field(rows, "price_criterion_serial", strict=True)
        )

    def test_indicator_series_metric_exposes_canonical_projection_fields(self):
        program = SemanticProgram.from_dict({
            "nodes": [
                {"node_id": "series", "operator": "retrieve",
                 "args": {"domain": "indicator", "metric": "series",
                          "indicator": "composite_index"}},
                {"node_id": "project", "operator": "project",
                 "inputs": [{"node_id": "series"}],
                 "args": {"fields": ["date", "indicator", "value"]}},
            ],
            "roots": ["project"],
        })
        self.assertEqual(program.completeness_issues(), ())

    def test_indicator_series_projection_alias_resolves_to_canonical_value(self):
        self.assertEqual(
            live_multihop._resolve_row_field(
                [{"date": "2026-09-01", "value": 101.5}],
                "series",
                strict=True,
            ),
            "value",
        )

    def test_ordered_last_binds_unique_canonical_date(self):
        source = TypedResult.success(
            ValueType.TIME_SERIES,
            [{"date": "2026-09-30", "value": 10}, {"date": "2026-10-01", "value": 12}],
            metric="price", unit="USD/mt",
        )
        node = RequirementNode(
            node_id="latest", operator=Operator.AGGREGATE,
            inputs=(InputRef("source"),),
            args={"aggregation": "last", "field": "value", "output_field": "current_value"},
        )
        result = execute_registered(object.__new__(live_multihop.LiveOperatorFactory), node, {"source": source})
        self.assertEqual(result.status.value, "success")
        self.assertEqual(result.value[0]["current_value"], 12)

    def test_trade_scope_filter_is_bound_to_query_input_and_share_output_capability(self):
        payload = {
            "nodes": [
                {"node_id": "imports", "operator": "retrieve",
                 "args": {"domain": "trade", "metric": "import_value", "mineral": "lithium"}},
                {"node_id": "scope", "operator": "filter", "inputs": [{"node_id": "imports"}],
                 "args": {"predicate": {"field": "reporter_country", "operator": "equals", "value": "South Korea"}}},
                {"node_id": "top", "operator": "top_k", "inputs": [{"node_id": "scope"}],
                 "args": {"top_n": 10}},
                {"node_id": "table", "operator": "project", "inputs": [{"node_id": "top"}],
                 "args": {"fields": ["country", "value", "import_share"],
                          "aliases": {"country": "country", "value": "value", "import_share": "import_share"}}},
            ],
            "roots": ["table"],
        }
        normalized = live_multihop._normalize_relation_contract(payload)
        self.assertNotIn("scope", {node["node_id"] for node in normalized["nodes"]})
        retrieve = next(node for node in normalized["nodes"] if node["node_id"] == "imports")
        self.assertEqual(retrieve["args"]["reporter_country"], "South Korea")
        self.assertEqual(retrieve["args"]["metric"], "import_share")
        program = SemanticProgram.from_dict(normalized)
        self.assertEqual(program.completeness_issues(), ())
        self.assertEqual(live_multihop._action_id(program.nodes[0]), "trade.country_rank")

    def test_resource_yoy_graph_uses_existing_typed_capability(self):
        payload = {
            "nodes": [
                {"node_id": "production", "operator": "retrieve",
                 "args": {"domain": "resource", "metric": "production_volume",
                          "mineral": "니켈"}},
                {"node_id": "yoy", "operator": "calculate",
                 "inputs": [{"node_id": "production"}],
                 "args": {"calculation": "yoy"}},
                {"node_id": "project", "operator": "project",
                 "inputs": [{"node_id": "yoy"}],
                 "args": {"fields": ["year", "value"]}},
            ],
            "roots": ["project"],
        }
        normalized = live_multihop._normalize_relation_contract(payload)
        ids = {node["node_id"] for node in normalized["nodes"]}
        self.assertNotIn("yoy", ids)
        resource = next(node for node in normalized["nodes"] if node["node_id"] == "production")
        self.assertEqual(resource["args"]["calculation"], "yoy")
        resource_node = RequirementNode(
            resource["node_id"], Operator.RETRIEVE, args=resource["args"],
        )
        self.assertEqual(live_multihop._action_id(resource_node), "resource.yoy")
        project = next(node for node in normalized["nodes"] if node["node_id"] == "project")
        self.assertEqual(project["inputs"][0]["node_id"], "production")

    def test_resource_yoy_normalizes_through_presentation_projection(self):
        normalized = live_multihop._normalize_relation_contract({
            "nodes": [
                {"node_id": "production", "operator": "retrieve",
                 "args": {"domain": "resource", "metric": "production_volume",
                          "mineral": "니켈"}},
                {"node_id": "base", "operator": "project",
                 "inputs": [{"node_id": "production"}],
                 "args": {"fields": ["year", "production_volume", "value"]}},
                {"node_id": "yoy", "operator": "calculate",
                 "inputs": [{"node_id": "base"}],
                 "args": {"calculation": "yoy"}},
                {"node_id": "result", "operator": "project",
                 "inputs": [{"node_id": "yoy"}],
                 "args": {"fields": ["year", "value"]}},
            ],
            "roots": ["result"],
        })
        ids = {node["node_id"] for node in normalized["nodes"]}
        self.assertNotIn("base", ids)
        self.assertNotIn("yoy", ids)
        self.assertEqual(next(node for node in normalized["nodes"] if node["node_id"] == "result")["inputs"][0]["node_id"], "production")
        resource = next(node for node in normalized["nodes"] if node["node_id"] == "production")
        self.assertEqual(resource["args"]["calculation"], "yoy")

    def test_indicator_period_change_uses_existing_typed_capability(self):
        normalized = live_multihop._normalize_relation_contract(
            {
                "nodes": [
                    {"node_id": "series", "operator": "retrieve",
                     "args": {"domain": "indicator", "metric": "series",
                              "indicator": "composite_index",
                              "period": {"kind": "trailing_months", "trailing_months": 1}}},
                    {"node_id": "change", "operator": "calculate",
                     "inputs": [{"node_id": "series"}],
                     "args": {"calculation": "period_change"}},
                ],
                "roots": ["change"],
            },
            [{"domain": "indicator", "metric": "series", "indicator": "composite_index",
              "indicator_variant": "composite", "operation": "period_change",
              "period": {"kind": "trailing_months", "trailing_months": 1}}],
        )
        ids = {node["node_id"] for node in normalized["nodes"]}
        self.assertNotIn("change", ids)
        series = next(node for node in normalized["nodes"] if node["node_id"] == "series")
        self.assertEqual(series["args"]["indicator_operation"], "period_change")
        self.assertEqual(series["args"]["indicator_variant"], "composite")
        self.assertEqual(normalized["roots"], ["series"])

    def test_indicator_period_change_does_not_rewrite_without_typed_requirement(self):
        normalized = live_multihop._normalize_relation_contract({
            "nodes": [
                {"node_id": "series", "operator": "retrieve",
                 "args": {"domain": "indicator", "metric": "series",
                          "indicator": "composite_index"}},
                {"node_id": "change", "operator": "calculate",
                 "inputs": [{"node_id": "series"}],
                 "args": {"calculation": "period_change"}},
            ],
            "roots": ["change"],
        })
        self.assertIn("change", {node["node_id"] for node in normalized["nodes"]})

    def test_indicator_rows_normalize_existing_compact_date(self):
        action = SimpleNamespace(slots=SimpleNamespace(indicator="composite_index"))
        rows = canonical_indicator_rows(
            [{"date": "20260905", "indx": "3651.45"}], action,
            resolve_field=live_multihop._resolve_row_field, numeric=live_multihop._numeric,
        )
        self.assertEqual(rows[0]["date"], "2026-09-05")
        self.assertEqual(rows[0]["value"], 3651.45)

    def test_scope_repair_preserves_typed_trade_dimension(self):
        program = {
            "nodes": [{"node_id": "imports", "operator": "retrieve",
                       "args": {"domain": "trade", "metric": "import_amount",
                                "flow": "import", "mineral": "리튬"}}],
            "roots": ["imports"],
        }
        repaired = live_multihop._deterministic_coverage_repair(
            program,
            CoverageReport(False, (CoverageViolation(
                "ENTITY_PRESERVATION_FAILED", "required_scope=KR, planned=['global']",
                requirement_id="requirement_1"),)),
            [{"domain": "trade", "metric": "country_rank", "scope": "KR"}],
        )
        self.assertIsNotNone(repaired)
        self.assertEqual(repaired.nodes[0].args["scope"], "KR")
        self.assertNotIn("partner_country", repaired.nodes[0].args)

    def test_trade_country_rank_preserves_export_metric_contract(self):
        normalized = live_multihop._normalize_relation_contract({
            "nodes": [{
                "node_id": "exports", "operator": "retrieve",
                "args": {"domain": "trade", "flow": "export",
                         "metric": "country_rank", "mineral": "코발트"},
            }],
            "roots": ["exports"],
        })
        node = normalized["nodes"][0]
        self.assertEqual(node["args"]["metric"], "export_amount")
        self.assertEqual(node["args"]["operation"], "country_rank")
        self.assertEqual(live_multihop._action_id(RequirementNode(
            "exports", Operator.RETRIEVE, args=node["args"],
        )), "trade.country_rank")
        self.assertIn("export_share", live_multihop._METRIC_FIELDS["country_rank"])

    def test_concentration_metric_uses_existing_concentration_capability(self):
        node = RequirementNode(
            "concentration", Operator.RETRIEVE,
            args={"domain": "trade", "metric": "concentration", "mineral": "니켈"},
        )
        self.assertEqual(live_multihop._action_id(node), "trade.concentration")

    def test_forecast_boundary_preserves_metric_period_and_operation(self):
        node = RequirementNode(
            "forecast", Operator.RETRIEVE,
            args={"domain": "price", "metric": "price_forecast",
                  "period": {"kind": "future_horizon", "future_horizon": 1},
                  "output": "latest_value"},
        )
        self.assertEqual(live_multihop._action_id(node), "forecast.price")
        slots = live_multihop._action_slots(node, mineral="nickel")
        self.assertEqual(slots.forecast_operation, "next_month_value")
        self.assertEqual(slots.period.kind, "future_horizon")
        self.assertEqual(slots.period.future_horizon, 1)

    def test_forecast_boundary_rejects_non_future_period(self):
        node = RequirementNode(
            "forecast", Operator.RETRIEVE,
            args={"metric": "price_forecast",
                  "period": {"kind": "trailing_months", "trailing_months": 3}},
        )
        with self.assertRaisesRegex(ValueError, "forecast period"):
            live_multihop._action_slots(node, mineral="nickel")

    def test_compare_infers_fields_through_project_and_yoy(self):
        normalized = live_multihop._normalize_relation_contract({
            "nodes": [
                {"node_id": "price", "operator": "retrieve",
                 "args": {"domain": "price", "metric": "price", "mineral": "니켈"}},
                {"node_id": "price_view", "operator": "project",
                 "inputs": [{"node_id": "price"}], "args": {"fields": ["date", "value"]}},
                {"node_id": "production", "operator": "retrieve",
                 "args": {"domain": "resource", "metric": "production_volume", "mineral": "니켈"}},
                {"node_id": "yoy", "operator": "calculate",
                 "inputs": [{"node_id": "production"}], "args": {"calculation": "yoy"}},
                {"node_id": "compare", "operator": "compare",
                 "inputs": [{"node_id": "price_view"}, {"node_id": "yoy"}],
                 "args": {"operation": "side_by_side"}},
            ], "roots": ["compare"],
        })
        compare = next(node for node in normalized["nodes"] if node["node_id"] == "compare")
        self.assertEqual(compare["args"]["left_field"], "value")
        self.assertEqual(compare["args"]["right_field"], "change_pct")

    def test_forecast_metric_is_restored_from_typed_requirement_only(self):
        normalized = live_multihop._normalize_relation_contract({
            "nodes": [{"node_id": "forecast", "operator": "retrieve",
                       "args": {"domain": "price", "mineral": "니켈",
                                "period": {"kind": "future_horizon", "future_horizon": 1},
                                "output": "time_series"}}],
            "roots": ["forecast"],
        }, [{"domain": "price", "metric": "price_forecast", "mineral": "니켈",
             "period": {"kind": "future_horizon", "future_horizon": 1}}])
        self.assertEqual(normalized["nodes"][0]["args"]["metric"], "price_forecast")

    def test_historical_series_is_not_rewritten_as_forecast(self):
        normalized = live_multihop._normalize_relation_contract({
            "nodes": [{"node_id": "history", "operator": "retrieve",
                       "args": {"domain": "price", "mineral": "니켈",
                                "period": {"kind": "trailing_months", "trailing_months": 6},
                                "output": "time_series"}}],
            "roots": ["history"],
        }, [{"domain": "price", "metric": "price_forecast", "mineral": "니켈",
             "period": {"kind": "future_horizon", "future_horizon": 1}}])
        self.assertNotIn("metric", normalized["nodes"][0]["args"])

    def test_compare_uses_forecast_predicted_price_field(self):
        normalized = live_multihop._normalize_relation_contract({
            "nodes": [
                {"node_id": "history", "operator": "retrieve",
                 "args": {"domain": "price", "metric": "price", "mineral": "니켈",
                          "period": {"kind": "trailing_months", "trailing_months": 6}}},
                {"node_id": "forecast", "operator": "retrieve",
                 "args": {"domain": "price", "metric": "price_forecast", "mineral": "니켈",
                          "period": {"kind": "future_horizon", "future_horizon": 1}}},
                {"node_id": "compare", "operator": "compare",
                 "inputs": [{"node_id": "history"}, {"node_id": "forecast"}],
                 "args": {"operation": "side_by_side", "left_field": "value", "right_field": "value"}},
            ], "roots": ["compare"],
        })
        compare = next(node for node in normalized["nodes"] if node["node_id"] == "compare")
        self.assertEqual(compare["args"]["right_field"], "predicted_price")

    def test_historical_forecast_join_normalizes_to_temporal_continuation(self):
        normalized = live_multihop._normalize_relation_contract({
            "nodes": [
                {"node_id": "history", "operator": "retrieve",
                 "args": {"domain": "price", "metric": "price", "mineral": "니켈",
                          "period": {"kind": "trailing_months", "trailing_months": 6}}},
                {"node_id": "forecast", "operator": "retrieve",
                 "args": {"domain": "price", "metric": "price_forecast", "mineral": "니켈",
                          "period": {"kind": "future_horizon", "future_horizon": 1}}},
                {"node_id": "joined", "operator": "join",
                 "inputs": [{"node_id": "history"}, {"node_id": "forecast"}],
                 "args": {"join_key": ["date"], "how": "full"}},
            ], "roots": ["joined"],
        }, [
            {"domain": "price", "metric": "price_series", "mineral": "니켈",
             "period": {"kind": "trailing_months", "trailing_months": 6}},
            {"domain": "price", "metric": "price_forecast", "mineral": "니켈",
             "period": {"kind": "future_horizon", "future_horizon": 1}},
        ])
        joined = next(node for node in normalized["nodes"] if node["node_id"] == "joined")
        self.assertEqual(joined["operator"], "compare")
        self.assertEqual(joined["args"]["operation"], "temporal_continuation")

    def test_historical_forecast_side_by_side_compare_normalizes_to_continuation(self):
        normalized = live_multihop._normalize_relation_contract({
            "nodes": [
                {"node_id": "history", "operator": "retrieve",
                 "args": {"domain": "price", "metric": "price", "mineral": "니켈",
                          "period": {"kind": "trailing_months", "trailing_months": 6}}},
                {"node_id": "forecast", "operator": "retrieve",
                 "args": {"domain": "price", "metric": "price_forecast", "mineral": "니켈",
                          "period": {"kind": "future_horizon", "future_horizon": 1}}},
                {"node_id": "combined", "operator": "compare",
                 "inputs": [{"node_id": "history"}, {"node_id": "forecast"}],
                 "args": {"operation": "side_by_side"}},
            ], "roots": ["combined"],
        }, [
            {"domain": "price", "metric": "price_series", "mineral": "니켈",
             "period": {"kind": "trailing_months", "trailing_months": 6}},
            {"domain": "price", "metric": "price_forecast", "mineral": "니켈",
             "period": {"kind": "future_horizon", "future_horizon": 1}},
        ])
        combined = next(node for node in normalized["nodes"] if node["node_id"] == "combined")
        self.assertEqual(combined["args"]["operation"], "temporal_continuation")

    def test_explicit_comparison_is_not_normalized_to_continuation(self):
        normalized = live_multihop._normalize_relation_contract({
            "nodes": [
                {"node_id": "history", "operator": "retrieve",
                 "args": {"domain": "price", "metric": "price", "mineral": "니켈",
                          "period": {"kind": "trailing_months", "trailing_months": 6}}},
                {"node_id": "forecast", "operator": "retrieve",
                 "args": {"domain": "price", "metric": "price_forecast", "mineral": "니켈",
                          "period": {"kind": "future_horizon", "future_horizon": 1}}},
                {"node_id": "combined", "operator": "compare",
                 "inputs": [{"node_id": "history"}, {"node_id": "forecast"}],
                 "args": {"operation": "side_by_side"}},
            ], "roots": ["combined"],
        }, [
            {"domain": "price", "metric": "price_series", "mineral": "니켈",
             "period": {"kind": "trailing_months", "trailing_months": 6},
             "comparison_operation": "same_period"},
            {"domain": "price", "metric": "price_forecast", "mineral": "니켈",
             "period": {"kind": "future_horizon", "future_horizon": 1}},
        ])
        combined = next(node for node in normalized["nodes"] if node["node_id"] == "combined")
        self.assertEqual(combined["args"]["operation"], "side_by_side")
    def test_indicator_boundary_preserves_selector_and_period(self):
        node = RequirementNode(
            "indicator", Operator.RETRIEVE,
            args={"domain": "indicator", "metric": "series",
                  "indicator": "composite_index", "indicator_variant": "composite",
                  "indicator_operation": "period_change",
                  "period": {"kind": "trailing_months", "trailing_months": 1}},
        )
        self.assertEqual(live_multihop._action_id(node), "indicator.series")
        slots = live_multihop._action_slots(node)
        self.assertEqual(slots.indicator, "composite_index")
        self.assertEqual(slots.indicator_operation, "period_change")
        self.assertEqual(slots.period.trailing_months, 1)

    def test_indicator_output_normalizes_numeric_series_to_value(self):
        call = live_multihop.ActionCall(
            requirement_id="indicator", action_id="indicator.series",
            slots=live_multihop.ActionSlots(
                indicator="composite_index", indicator_variant="composite",
            ),
        )
        evidence = Evidence(
            "structured", "fixture", "fixture",
            "| date | series |\n| --- | --- |\n| 2026-09-01 | 101.5 |",
        )
        raw = RetrievalResult(
            ActionPlan(actions=[call]),
            [ActionResult("indicator", "indicator.series", call.slots, "success", [evidence])],
            [evidence], [],
        )
        result = live_multihop._typed_from_retrieval(raw, call, input_entities=[])
        self.assertEqual(result.status.value, "success")
        self.assertEqual(result.value[0]["indicator"], "composite_index")
        self.assertEqual(result.value[0]["value"], 101.5)

    def test_indicator_output_normalizes_index_source_alias_to_value(self):
        call = live_multihop.ActionCall(
            requirement_id="indicator", action_id="indicator.series",
            slots=live_multihop.ActionSlots(indicator="composite_index"),
        )
        evidence = Evidence(
            "structured", "fixture", "fixture",
            "| date | indx |\n| --- | --- |\n| 2026-09-01 | 101.2 |",
        )
        raw = RetrievalResult(
            ActionPlan(actions=[call]),
            [ActionResult("indicator", "indicator.series", call.slots, "success", [evidence])],
            [evidence], [],
        )
        result = live_multihop._typed_from_retrieval(raw, call, input_entities=[])
        self.assertEqual(result.status.value, "success")
        self.assertEqual(result.value[0]["value"], 101.2)

    def test_indicator_output_contract_rejects_missing_date_or_value(self):
        call = live_multihop.ActionCall(
            requirement_id="indicator", action_id="indicator.series",
            slots=live_multihop.ActionSlots(indicator="composite_index"),
        )
        evidence = Evidence(
            "structured", "fixture", "fixture",
            "| series |\n| --- |\n| 101.5 |",
        )
        raw = RetrievalResult(
            ActionPlan(actions=[call]),
            [ActionResult("indicator", "indicator.series", call.slots, "success", [evidence])],
            [evidence], [],
        )
        result = live_multihop._typed_from_retrieval(raw, call, input_entities=[])
        self.assertEqual(result.status.value, "empty")
        self.assertEqual(result.failure_reason, "indicator_output_contract_invalid")

    def test_country_share_scope_normalizes_to_global_trade_scope(self):
        node = RequirementNode("country", Operator.RETRIEVE, args={"metric": "import_value", "scope": "country_share"})
        self.assertEqual(live_multihop._action_slots(node).trade_scope, "global")

    def test_filter_accepts_compact_string_predicate_without_runtime_error(self):
        factory = live_multihop.LiveOperatorFactory(
            message="가격 상승 광물", session_id="filter-test", profile="public",
            llm=object(), history=[],
        )
        source = TypedResult.success(
            ValueType.MINERAL_RANKING,
            [{"광종": "니켈", "pct_change": "12.5"}, {"광종": "리튬", "pct_change": "-2.0"}],
            entity=("니켈", "리튬"),
        )
        node = RequirementNode(
            "filtered", Operator.FILTER,
            args={"metric": "price_change_rate", "predicate": "greater_than", "value": 0},
        )

        result = execute_registered(factory, node, {"rank": source})

        self.assertEqual(result.status.value, "success")
        self.assertEqual(result.value, [{"광종": "니켈", "pct_change": "12.5"}])

    def test_sort_keeps_rows_with_missing_metric_at_the_end(self):
        factory = live_multihop.LiveOperatorFactory(
            message="국가 순위", session_id="sort-test", profile="public", llm=object(), history=[],
        )
        source = TypedResult.success(
            ValueType.FACT_SET,
            [{"국가": "중국", "import_amount": None}, {"국가": "호주", "import_amount": 10}],
        )
        node = RequirementNode("sorted", Operator.SORT, args={"field": "import_amount", "order": "desc"})
        result = execute_registered(factory, node, {"source": source})
        self.assertEqual([row["국가"] for row in result.value], ["호주", "중국"])

    def test_projection_binds_existing_korean_trade_columns_to_typed_fields(self):
        factory = live_multihop.LiveOperatorFactory(
            message="국가별 수입 비중", session_id="project-test", profile="public", llm=object(), history=[],
        )
        source = TypedResult.success(
            ValueType.COUNTRY_SHARE,
            [{"국가": "중국", "수입액": "90", "비중": "45.0", "기간": "2025", "단위": "USD"}],
        )
        node = RequirementNode(
            "projected", Operator.PROJECT,
            args={"fields": ["country", "share_percentage", "period", "unit"]},
        )

        result = execute_registered(factory, node, {"source": source})

        self.assertEqual(result.value, [{"country": "중국", "share_percentage": "45.0", "period": "2025", "unit": "USD"}])

    def test_semantic_history_is_bounded_and_excludes_raw_result_payload(self):
        typed = TypedResult.success(
            ValueType.TRADE_SERIES,
            [{"월": "2026-01", "수입액": "999999999999999999999999"}],
            entity=("니켈",), metric="import_amount", provenance=("trade:fixture",),
        )
        turns = tuple(
            Turn(
                f"turn-{index}", "compact-session", UserUtterance("이전 질문"),
                semantic_program=SemanticProgram(
                    (RequirementNode("root", Operator.RETRIEVE, args={"metric": "import_amount"}),),
                    ("root",),
                ),
                result=ExecutionResult(f"pipe-{index}", ResultStatus.SUCCESS, {"root": typed}, ()),
            )
            for index in range(12)
        )
        payload = live_multihop._semantic_context_payload(ConversationContext("compact-session", turns))
        self.assertEqual(len(payload), 8)
        # Schema names are required for typed follow-ups, raw numeric payloads are not.
        self.assertNotIn("999999999999999999999999", str(payload))
        self.assertIn("operators", payload[-1]["ast"])
        self.assertIn("provenance", payload[-1]["results"][0])

    async def test_semantic_ast_cache_reuses_same_typed_context(self):
        class FakeLLM:
            model = "fake-gemma"
            calls = 0

            def invoke(self, **_kwargs):
                self.calls += 1
                return SimpleNamespace(output=live_multihop.ASTProgramModel.model_validate({
                    "nodes": [{"node_id": "root", "operator": "entity", "args": {"values": ["니켈"]}}],
                    "roots": ["root"],
                }))

        llm = FakeLLM()
        context = ConversationContext("cache-session")
        first = await live_multihop._parse_ast(llm, "니켈", context)
        second = await live_multihop._parse_ast(llm, "니켈", context)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(llm.calls, 1)
        self.assertEqual(live_multihop.semantic_cache_stats(), {"size": 1, "hits": 1, "misses": 1})

    async def test_real_bridge_uses_existing_action_executor_and_sse_blocks(self):
        program = SemanticProgram(
            nodes=(
                RequirementNode("rank", Operator.RANK, args={"domain": "price", "metric": "price_change", "top_n": 3}, expected_type=ValueType.MINERAL_RANKING),
                RequirementNode("top", Operator.TOP_K, (InputRef("rank"),), {"k": 2}, ValueType.MINERAL_SET),
                RequirementNode("imports", Operator.RETRIEVE, (InputRef("top"),), {"domain": "trade", "metric": "country_share", "scope": "KR"}, ValueType.COUNTRY_SHARE),
                RequirementNode("answer", Operator.ARG_MAX, (InputRef("imports"),), {"field": "import_amount"}, ValueType.SCALAR_METRIC),
            ),
            roots=("answer",),
        )

        def fake_retrieve(_question, *, action_plan, **_kwargs):
            call = action_plan.actions[0]
            if call.action_id == "price.volatility_rank":
                text = "| 광종 | 변동률(%) |\n| --- | --- |\n| 니켈 | 20 |\n| 리튬 | 10 |\n| 구리 | 5 |"
            else:
                text = "| 국가 | import_amount(USD) |\n| --- | --- |\n| 중국 | 90 |"
            evidence = Evidence("structured", "KOMIS fixture", "fixture", text, unit="USD")
            action_result = ActionResult(call.requirement_id, call.action_id, call.slots, "success", [evidence])
            return RetrievalResult(action_plan, [action_result], [evidence], [])

        with patch.object(live_multihop, "_parse_ast", new=AsyncMock(return_value=program)), \
             patch.object(live_multihop, "retrieve_evidence", side_effect=fake_retrieve):
            run = await live_multihop.run_live_multihop(
                message="가격 상승률 상위 3개 중 수입액이 가장 큰 광물",
                session_id="live-test-session",
                profile="public",
                llm=object(),
                history=[],
            )

        self.assertEqual(run.orchestration.root_result.status.value, "success")
        self.assertEqual(run.orchestration.root_result.value[0]["국가"], "중국")
        event_types = [event.type for event in live_multihop.live_run_events(run)]
        self.assertIn("delta", event_types)
        self.assertIn("table", event_types)
        self.assertEqual(event_types[-1], "done")
