# -*- coding: utf-8 -*-
"""Typed semantic normalization tests (legacy contract remains the oracle)."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rag_core.ragkit.action_contract import (  # noqa: E402
    ActionPlan,
    _extract_action_plan_legacy,
    extract_action_plan,
    _history_for_action_query,
    history_is_required,
)
from rag_core.ragkit.semantic_intent import (  # noqa: E402
    SemanticPlan,
    SemanticRequirement,
    SemanticResolutionError,
    canonical_signature,
    _bind_price_context,
    _normalize_semantic_plan,
    parse_and_resolve,
    resolve_semantic_plan,
)
from rag_core.ragkit.multi_action_state import PriceContextV1, CarryActionV1, CarrySlotsV1  # noqa: E402


class SemanticLLM:
    def __init__(self, plan: SemanticPlan):
        self.plan = plan
        self.tasks: list[str] = []
        self.payloads: list[dict] = []

    def invoke(self, **kwargs):
        self.tasks.append(kwargs["task"])
        self.payloads.append(kwargs.get("payload", {}))
        if kwargs["task"] == "semantic_intent":
            return SimpleNamespace(output=self.plan)
        raise AssertionError(f"unexpected fallback task: {kwargs['task']}")


def _concentration_plan() -> SemanticPlan:
    return SemanticPlan(requirements=[SemanticRequirement(
        domain="trade", metric="concentration", flow="import", mineral="니켈", scope="KR",
    )])


class SemanticIntentTest(unittest.TestCase):
    def test_primitive_schema_does_not_accept_physical_action_names(self):
        with self.assertRaises(ValueError):
            SemanticRequirement.model_validate({
                "domain": "trade.concentration", "metric": "trade.concentration",
            })

    def test_five_concentration_paraphrases_share_canonical_signature(self):
        questions = [
            "니켈 수입 집중도를 알려줘",
            "니켈 수입이 특정 국가에 얼마나 몰려 있어?",
            "니켈 수입선이 편중되어 있어?",
            "니켈을 일부 국가에 많이 의존하고 있어?",
            "니켈 공급국이 몇 나라에 집중돼 있나?",
        ]
        expected = canonical_signature(_concentration_plan())
        for question in questions:
            # Parser output is the model boundary; every natural-language
            # variant is expected to normalize to this same typed value.
            parsed = _concentration_plan()
            intent_plan, action_plan = resolve_semantic_plan(parsed, question)
            self.assertEqual(canonical_signature(parsed), expected)
            self.assertEqual(action_plan.actions[0].action_id, "trade.concentration")
            self.assertEqual(action_plan.actions[0].slots.mineral, "니켈")
            self.assertEqual(action_plan.actions[0].slots.flow, "import")
            self.assertEqual(intent_plan.requirements[0].intent, "trade_concentration")

    def test_country_rank_share_does_not_create_duplicate_concentration_branch(self):
        plan = SemanticPlan(requirements=[
            SemanticRequirement(
                domain="trade", metric="country_rank", flow="import",
                mineral="리튬", scope="KR",
            ),
            SemanticRequirement(
                domain="trade", metric="concentration", flow="import",
                mineral="리튬", scope="KR",
            ),
        ])
        normalized = _normalize_semantic_plan(
            plan, "한국의 리튬 수입 상위국과 국가별 비중을 알려줘",
        )
        self.assertEqual(
            [(item.domain, item.metric) for item in normalized.requirements],
            [("trade", "country_rank")],
        )

    def test_explicit_concentration_remains_independent_from_country_rank(self):
        plan = SemanticPlan(requirements=[
            SemanticRequirement(
                domain="trade", metric="country_rank", flow="import",
                mineral="리튬", scope="KR",
            ),
            SemanticRequirement(
                domain="trade", metric="concentration", flow="import",
                mineral="리튬", scope="KR",
            ),
        ])
        normalized = _normalize_semantic_plan(
            plan, "한국의 리튬 수입 상위국과 수입 집중도를 알려줘",
        )
        self.assertEqual(
            [item.metric for item in normalized.requirements],
            ["country_rank", "concentration"],
        )

    def test_enabled_mode_uses_semantic_parser_after_legacy_shortcut_miss(self):
        llm = SemanticLLM(_concentration_plan())
        with patch.dict(os.environ, {"SEMANTIC_INTENT_MODE": "enabled"}, clear=False):
            plan = extract_action_plan("니켈 수입선이 편중되어 있어?", llm)
        self.assertIsInstance(plan, ActionPlan)
        self.assertEqual(plan.actions[0].action_id, "trade.concentration")
        self.assertEqual(plan.actions[0].requirement_id, "import_concentration")
        self.assertEqual(llm.tasks, ["semantic_intent"])

    def test_enabled_mode_prefers_typed_semantic_parser_over_legacy_shortcut(self):
        llm = SemanticLLM(_concentration_plan())
        with patch.dict(os.environ, {"SEMANTIC_INTENT_MODE": "enabled"}, clear=False):
            plan = extract_action_plan("니켈 수입 집중도를 알려줘", llm)
        self.assertEqual(plan.actions[0].action_id, "trade.concentration")
        self.assertEqual(llm.tasks, ["semantic_intent"])

    def test_latest_price_shortcut_does_not_swallow_suffix_or_date_into_mineral(self):
        # The deterministic shortcut must miss these forms so that the typed
        # semantic parser can normalize the actual mineral and/or future period.
        for question in ("리튬 최신 가격 얼마야?", "2027년 7월 리튬 가격 알려줘"):
            self.assertIsNone(
                _extract_action_plan_legacy(question, SemanticLLM(_concentration_plan()), [], allow_llm=False),
                question,
            )

    def test_enabled_mode_routes_add01_to_semantic_current_price(self):
        llm = SemanticLLM(SemanticPlan(requirements=[SemanticRequirement(
            domain="price", metric="current", mineral="리튬",
        )]))
        with patch.dict(os.environ, {"SEMANTIC_INTENT_MODE": "enabled"}, clear=False):
            plan = extract_action_plan("리튬 최신 가격 얼마야?", llm)
        self.assertEqual(plan.actions[0].action_id, "price.series")
        self.assertEqual(plan.actions[0].slots.mineral, "리튬")
        self.assertEqual(llm.tasks, ["semantic_intent"])

    def test_enabled_mode_routes_add04_to_semantic_price_forecast(self):
        llm = SemanticLLM(SemanticPlan(requirements=[SemanticRequirement(
            domain="price", metric="price_forecast", mineral="리튬",
            period={"kind": "future_horizon", "future_horizon": 10, "explicit": True},
        )]))
        with patch.dict(os.environ, {"SEMANTIC_INTENT_MODE": "enabled"}, clear=False):
            plan = extract_action_plan("2027년 7월 리튬 가격 알려줘", llm)
        self.assertEqual(plan.actions[0].action_id, "forecast.price")
        self.assertEqual(plan.actions[0].slots.mineral, "리튬")
        self.assertEqual(plan.actions[0].slots.period.future_horizon, 10)
        self.assertEqual(llm.tasks, ["semantic_intent"])

    def test_price_claim_cause_keeps_300_percent_and_two_typed_requirements(self):
        question = "니켈 가격이 2025년에 정확히 300% 올랐는데 원인이 뭐야"
        llm = SemanticLLM(SemanticPlan(requirements=[
            SemanticRequirement(
                domain="price", metric="price_claim", mineral="니켈",
                period={"kind": "calendar_year", "calendar_year": 2025},
                claimed_change_pct=300, comparator="equals",
            ),
        ]))
        result = parse_and_resolve(question, llm)
        self.assertIsNone(result.reason)
        self.assertEqual(
            [(item.domain, item.metric) for item in result.semantic_plan.requirements],
            [("price", "price_claim"), ("document", "retrieve")],
        )
        self.assertEqual(
            [call.action_id for call in result.action_plan.actions],
            ["price.verify_claim", "document.retrieve"],
        )
        self.assertEqual(result.action_plan.actions[0].slots.claimed_change_pct, 300)

    def test_price_series_misclassification_is_repaired_for_claim_cause_shape(self):
        question = "니켈 가격이 2025년에 정확히 300% 올랐는데 원인이 뭐야"
        llm = SemanticLLM(SemanticPlan(requirements=[
            SemanticRequirement(
                domain="price", metric="price_series", mineral="니켈",
                period={"kind": "calendar_year", "calendar_year": 2025},
            ),
            SemanticRequirement(domain="document", metric="retrieve", topic="니켈 가격 원인"),
        ]))
        result = parse_and_resolve(question, llm)
        self.assertIsNone(result.reason)
        self.assertEqual([call.action_id for call in result.action_plan.actions],
                         ["price.verify_claim", "document.retrieve"])
        self.assertEqual(result.action_plan.actions[0].slots.claimed_change_pct, 300)

    def test_numeric_price_claim_without_cause_resolves_to_claim_action(self):
        question = "2025년 니켈 가격이 300% 이상 올랐어?"
        llm = SemanticLLM(SemanticPlan(requirements=[SemanticRequirement(
            domain="price", metric="price_series", mineral="니켈",
            period={"kind": "calendar_year", "calendar_year": 2025},
        )]))
        result = parse_and_resolve(question, llm)
        self.assertIsNone(result.reason)
        self.assertEqual([(item.domain, item.metric) for item in result.semantic_plan.requirements],
                         [("price", "price_claim")])
        action = result.action_plan.actions[0]
        self.assertEqual(action.action_id, "price.verify_claim")
        self.assertEqual(action.slots.claimed_change_pct, 300)
        self.assertEqual(action.slots.comparator, "greater_than")

    def test_production_import_vulnerability_keeps_both_population_actions(self):
        plan = SemanticPlan(requirements=[
            SemanticRequirement(domain="resource", metric="resource_rank", mineral="코발트", scope="WORLD"),
            SemanticRequirement(domain="trade", metric="country_rank", mineral="코발트",
                                flow="import", scope="KR"),
            SemanticRequirement(domain="concept", metric="retrieve", mineral="코발트",
                                topic="공급망 취약점 설명"),
        ])
        _intent, action_plan = resolve_semantic_plan(plan, "코발트 세계 생산국 비중과 한국 수입국 비중을 비교하고 공급망 취약점을 설명해줘")
        self.assertEqual([call.action_id for call in action_plan.actions],
                         ["resource.rank", "trade.country_rank"])

    def test_added_first_order_legacy_shortcuts_keep_existing_action_contracts(self):
        cases = {
            "아연 가격 2010년 이후 최고가와 그 날짜 알려줘": ("price.series", "price_extrema"),
            "한국의 코발트 수입액과 수입중량 최근 12개월을 각각 차트로 보여줘": ("trade.monthly", "trade_monthly_import_amount_12m"),
            "2026년 1~7월 리튬 수입액을 작년 같은 기간과 비교해줘": ("trade.monthly", "trade_monthly_import_amount_2026-01_2026-07"),
            "리튬 수급안정화지수 최근값과 위기 여부 알려줘": ("indicator.series", "supply_stability_latest"),
            "리튬에 해당하는 HS코드 목록 보여줘": ("document.lookup", "hs_code_lookup"),
            "리튬 가격 화면으로 가줘": ("menu.navigate", "price_page"),
        }
        for question, (action_id, requirement_id) in cases.items():
            plan = _extract_action_plan_legacy(question, None, [], allow_llm=False)
            self.assertIsNotNone(plan, question)
            self.assertEqual(plan.actions[0].action_id, action_id, question)
            self.assertEqual(plan.actions[0].requirement_id, requirement_id, question)

    def test_trade_price_misclassification_normalizes_to_monthly_trade(self):
        plan = SemanticPlan(requirements=[
            SemanticRequirement(
                domain="trade", metric="price_series", flow="import", mineral="코발트",
                metric_unit="amount", period={"kind": "trailing_months", "trailing_months": 12},
            ),
            SemanticRequirement(
                domain="trade", metric="price_series", flow="import", mineral="코발트",
                metric_unit="weight", period={"kind": "trailing_months", "trailing_months": 12},
            ),
        ])
        intent_plan, action_plan = resolve_semantic_plan(
            plan, "한국의 코발트 수입액과 수입중량 최근 12개월을 각각 차트로 보여줘",
        )
        self.assertEqual([item.intent for item in intent_plan.requirements], ["trade_monthly", "trade_monthly"])
        self.assertEqual([item.action_id for item in action_plan.actions], ["trade.monthly", "trade.monthly"])
        self.assertEqual({item.slots.metric for item in action_plan.actions}, {"import_amount", "import_weight"})

    def test_indicator_latest_and_hs_lookup_keep_typed_capabilities(self):
        indicator_intent, indicator_action = resolve_semantic_plan(
            SemanticPlan(requirements=[SemanticRequirement(
                domain="indicator", metric="latest", indicator="supply_stability", mineral="리튬",
            )]),
            "리튬 수급안정화지수 최근값과 위기 여부 알려줘",
        )
        self.assertEqual(indicator_intent.requirements[0].intent, "indicator")
        self.assertEqual(indicator_action.actions[0].action_id, "indicator.series")
        self.assertEqual(indicator_action.actions[0].slots.indicator, "supply_stability")
        _, hs_action = resolve_semantic_plan(
            SemanticPlan(requirements=[SemanticRequirement(
                domain="trade", metric="lookup", mineral="리튬", topic="HS코드 목록",
            )]),
            "리튬에 해당하는 HS코드 목록 보여줘",
        )
        self.assertEqual(hs_action.actions[0].action_id, "document.lookup")

    def test_semantic_year_range_is_preserved_for_monthly_trade(self):
        _, action_plan = resolve_semantic_plan(
            SemanticPlan(requirements=[SemanticRequirement(
                domain="trade", metric="price_compare", flow="import", mineral="리튬",
                metric_unit="amount", period={"kind": "range", "start": "2026-01", "end": "2026-07"},
            )]),
            "2026년 1~7월 리튬 수입액을 작년 같은 기간과 비교해줘",
        )
        period = action_plan.actions[0].slots.period
        self.assertEqual((period.kind, period.start, period.end), ("range", "2026-01-01", "2026-07-31"))

    def test_monthly_trade_comparison_keeps_amount_weight_and_all_windows(self):
        plan = _extract_action_plan_legacy(
            "한국의 니켈 수입액과 수입중량을 각각 최근 3개월·6개월·12개월로 비교하고, 기간별 증감률을 표로 보여줘",
            None,
            [],
            allow_llm=False,
        )
        self.assertEqual(len(plan.actions), 6)
        self.assertEqual({item.slots.metric for item in plan.actions}, {"import_amount", "import_weight"})
        self.assertEqual(
            {item.slots.period.trailing_months for item in plan.actions},
            {3, 6, 12},
        )

    def test_explicit_new_query_does_not_inherit_unresolved_followup_history(self):
        llm = SemanticLLM(SemanticPlan(requirements=[SemanticRequirement(
            domain="resource", metric="resource_rank", mineral="코발트", scope="WORLD", top_n=6,
        )]))
        history = [
            {"role": "user", "content": "그중에 3번째 국가에서 생산량이 1위인 광종이 무엇인가요?"},
            {"role": "assistant", "content": "요청 범위가 넓습니다."},
        ]
        with patch.dict(os.environ, {"SEMANTIC_INTENT_MODE": "enabled"}, clear=False):
            plan = extract_action_plan("코발트 생산량 상위 6개국 알려줘", llm, history=history)
        self.assertEqual(plan.actions[0].slots.top_n, 6)
        self.assertEqual(llm.payloads[0]["history"], [])

    def test_reference_followup_retains_history_for_dependency_resolution(self):
        history = [{"role": "assistant", "content": "코발트 상위 국가 표"}]
        self.assertEqual(_history_for_action_query("그중에 3번째 국가", history), history)

    def test_explicit_query_blocks_history_even_after_unrelated_turn(self):
        history = [{"role": "assistant", "content": "리튬 가격 전망"}]
        self.assertFalse(history_is_required("니켈 최근 1년 가격 추이를 보여줘"))
        self.assertEqual(_history_for_action_query("니켈 최근 1년 가격 추이를 보여줘", history), [])

    def test_explicit_entity_overrides_previous_entity(self):
        history = [{"role": "assistant", "content": "리튬 가격 알려줘"}]
        self.assertEqual(_history_for_action_query("니켈 가격 알려줘", history), [])

    def test_period_followup_retains_typed_history(self):
        history = [{"role": "assistant", "content": "니켈 최근 1년 가격"}]
        self.assertTrue(history_is_required("그중 최근 3개월만 보여줘"))
        self.assertEqual(_history_for_action_query("그중 최근 3개월만 보여줘", history), history)

    def test_shadow_mode_records_semantic_call_but_returns_legacy_plan(self):
        llm = SemanticLLM(_concentration_plan())
        with self.assertLogs("rag_core.ragkit.semantic_intent", level="INFO") as logs:
            with patch.dict(os.environ, {"SEMANTIC_INTENT_MODE": "shadow"}, clear=False):
                plan = extract_action_plan("니켈 수입 집중도를 알려줘", llm)
        self.assertEqual(plan.actions[0].requirement_id, "import_concentration")
        self.assertEqual(llm.tasks, ["semantic_intent", "semantic_requirement_v2"])
        self.assertIn("semantic_canonical_signature", "\n".join(logs.output))
        self.assertIn("semantic_resolved_action_plan", "\n".join(logs.output))
        self.assertIn("semantic_fallback_reason", "\n".join(logs.output))

    def test_first_order_inventory_capability_resolves_to_existing_action(self):
        plan = SemanticPlan(requirements=[SemanticRequirement(
            domain="inventory", metric="latest", mineral="니켈", scope="KR",
        )])
        _, action_plan = resolve_semantic_plan(plan, "니켈 재고 알려줘")
        self.assertEqual(action_plan.actions[0].action_id, "inventory.latest")

    def test_inventory_series_resolves_to_distinct_series_action(self):
        plan = SemanticPlan(requirements=[SemanticRequirement(
            domain="inventory", metric="series", mineral="니켈",
            period={"kind": "trailing_months", "trailing_months": 12},
        )])
        _, action_plan = resolve_semantic_plan(plan, "최근 1년간 니켈 재고 추이를 보여줘")
        action = action_plan.actions[0]
        self.assertEqual(action.action_id, "inventory.series")
        self.assertEqual(action.slots.period.kind, "trailing_months")

    def test_inventory_latest_metric_with_bounded_period_is_normalized_to_series(self):
        plan = SemanticPlan(requirements=[SemanticRequirement(
            domain="inventory", metric="latest", mineral="니켈",
            period={"kind": "trailing_months", "trailing_months": 12},
        )])
        _, action_plan = resolve_semantic_plan(plan, "최근 1년간 니켈 재고 추이를 보여줘")
        self.assertEqual(action_plan.actions[0].action_id, "inventory.series")

    def test_price_forecast_resolves_to_existing_forecast_action(self):
        plan = SemanticPlan(requirements=[SemanticRequirement(
            domain="price", metric="price_forecast", mineral="니켈",
            period={"kind": "future_horizon", "future_horizon": 1},
        )])
        _, action_plan = resolve_semantic_plan(plan, "니켈 다음달 가격 전망 알려줘")
        action = action_plan.actions[0]
        self.assertEqual(action.action_id, "forecast.price")
        self.assertEqual(action.slots.forecast_operation, "next_month_value")

    def test_unbounded_price_trend_defaults_to_typed_rolling_series(self):
        plan = SemanticPlan(requirements=[SemanticRequirement(
            domain="price", metric="price_series", mineral="니켈",
        )])
        normalized = _normalize_semantic_plan(plan, "니켈 가격 추이 좀 보여줘")
        period = normalized.requirements[0].period
        self.assertEqual((period.kind, period.trailing_months), ("trailing_months", 12))

    def test_all_price_criteria_is_distinct_from_representative_series(self):
        base = SemanticPlan(requirements=[SemanticRequirement(
            domain="price", metric="price_series", mineral="니켈",
        )])
        representative = _normalize_semantic_plan(base, "최근 1년간 니켈 가격 추이를 보여줘")
        all_criteria = _normalize_semantic_plan(base, "최근 1년간 니켈 모든 가격 추이를 보여줘")

        self.assertEqual(representative.requirements[0].criterion_mode, "REPRESENTATIVE")
        self.assertEqual(all_criteria.requirements[0].criterion_mode, "ALL")
        _, representative_actions = resolve_semantic_plan(
            representative, "최근 1년간 니켈 가격 추이를 보여줘"
        )
        _, all_actions = resolve_semantic_plan(
            all_criteria, "최근 1년간 니켈 모든 가격 추이를 보여줘"
        )
        self.assertEqual(representative_actions.actions[0].slots.criterion_mode, "REPRESENTATIVE")
        self.assertEqual(all_actions.actions[0].slots.criterion_mode, "ALL")

    def test_yearly_average_preserves_existing_price_operation_contract(self):
        plan = SemanticPlan(requirements=[SemanticRequirement(
            domain="price", metric="price_series", mineral="니켈",
            operation="yearly_average",
        )])
        _, action_plan = resolve_semantic_plan(plan, "니켈 가격 년도별 평균 가격을 알려줘")
        action = action_plan.actions[0]
        self.assertEqual(action.action_id, "price.series")
        self.assertEqual(action.slots.price_operation, "yearly_average")
        self.assertEqual(action.slots.period.kind, "latest")

    def test_price_year_over_year_defaults_to_monthly_average(self):
        plan = SemanticPlan(requirements=[SemanticRequirement(
            domain="price", metric="price_series", mineral="니켈",
            operation="period_change", comparison="same_month_previous_year",
        )])
        _, action_plan = resolve_semantic_plan(plan, "니켈 가격 전년 동월 대비 변화율은?")
        action = action_plan.actions[0]
        self.assertEqual(action.action_id, "price.series")
        self.assertEqual(action.slots.price_operation, "year_over_year")
        self.assertEqual(action.slots.price_yoy_basis, "monthly_average")
        self.assertEqual(action.slots.period.trailing_months, 13)

    def test_price_year_over_year_can_use_monthly_latest_observation(self):
        plan = SemanticPlan(requirements=[SemanticRequirement(
            domain="price", metric="price_series", mineral="니켈",
            operation="period_change", comparison="same_month_previous_year",
            aggregation="monthly_latest",
        )])
        _, action_plan = resolve_semantic_plan(plan, "니켈 가격 전년 동월 대비 변화율을 월 최신 관측값 기준으로 알려줘")
        self.assertEqual(action_plan.actions[0].slots.price_yoy_basis, "monthly_latest")

    def test_price_period_extrema_resolves_to_existing_price_series(self):
        plan = SemanticPlan(requirements=[SemanticRequirement(
            domain="price", metric="price_series", mineral="아연",
            period={"kind": "range", "start": "2010-01-01", "end": "2026-09-30"},
            operation="period_extrema",
        )])
        _, action_plan = resolve_semantic_plan(plan, "아연 가격 2010년 이후 최고가와 그 날짜 알려줘")
        action = action_plan.actions[0]
        self.assertEqual(action.action_id, "price.series")
        self.assertEqual(action.slots.price_operation, "period_extrema")
        self.assertEqual(action.slots.period.kind, "range")

    def test_relative_week_and_argmin_resolve_without_lexical_shortcut(self):
        plan = SemanticPlan(requirements=[SemanticRequirement(
            domain="price", metric="price_series", mineral="니켈",
            period={"kind": "relative", "relative_value": 1,
                    "relative_unit": "week", "relative_anchor": "latest_available"},
            selection={"mode": "extremum", "direction": "min", "measure": "price",
                       "return_fields": ["value", "date"]},
        )])
        _, action_plan = resolve_semantic_plan(plan, "최근 1주일 가격 중 가장 낮았던 날은?")
        action = action_plan.actions[0]
        self.assertEqual(action.action_id, "price.series")
        self.assertEqual(action.slots.price_operation, "period_extrema")
        self.assertEqual(action.slots.selection_direction, "min")
        self.assertEqual(action.slots.period.kind, "range")

    def test_find_n_is_typed_ordinal_selection_on_price_series(self):
        plan = SemanticPlan(requirements=[SemanticRequirement(
            domain="price", metric="price_series", mineral="니켈",
            period={"kind": "relative", "relative_value": 1, "relative_unit": "week"},
            selection={"mode": "ordinal", "position": 3},
        )])
        _, action_plan = resolve_semantic_plan(plan, "그중 세 번째 관측값은?")
        action = action_plan.actions[0]
        self.assertEqual(action.action_id, "price.series")
        self.assertEqual(action.slots.selection_mode, "ordinal")
        self.assertEqual(action.slots.selection_position, 3)

    def test_followup_selection_inherits_only_previous_typed_price_context(self):
        context = PriceContextV1(profile="public", action=CarryActionV1(
            requirement_id="price_니켈", action_id="price.series",
            slots=CarrySlotsV1(mineral="니켈", period={"kind": "range", "start": "2026-09-24", "end": "2026-09-30"}),
        ))
        plan = SemanticPlan(requirements=[SemanticRequirement(
            domain="price", metric="price_series",
            relation="refine_previous", context_ref="previous_successful_price_series",
            selection={"mode": "extremum", "direction": "min", "measure": "price"},
        )])
        _, action_plan = resolve_semantic_plan(
            _bind_price_context(plan, context), "그중 가격이 제일 낮았던 날은?",
        )
        action = action_plan.actions[0]
        self.assertEqual(action.slots.mineral, "니켈")
        self.assertEqual(action.slots.period.kind, "range")
        self.assertEqual(action.slots.selection_direction, "min")

    def test_argmin_resource_rank_fails_closed_instead_of_inverting_adapter(self):
        plan = SemanticPlan(requirements=[SemanticRequirement(
            domain="resource", metric="resource_rank", mineral="코발트", scope="WORLD",
            selection={"mode": "extremum", "direction": "min", "measure": "production"},
        )])
        with self.assertRaises(SemanticResolutionError):
            resolve_semantic_plan(plan, "생산량이 가장 적은 국가는?")

    def test_resource_production_country_rank_is_not_trade_export(self):
        plan = SemanticPlan(requirements=[
            SemanticRequirement(domain="resource", metric="resource_rank", mineral="코발트", scope="WORLD"),
            SemanticRequirement(domain="trade", metric="country_rank", mineral="코발트", flow="import", scope="KR"),
        ])
        _, action_plan = resolve_semantic_plan(plan, "코발트 세계 생산국이랑 우리나라 수입국 비교해줘")
        self.assertEqual([item.action_id for item in action_plan.actions], ["resource.rank", "trade.country_rank"])

    def test_resource_rank_argmax_preserves_singular_superlative(self):
        plan = SemanticPlan(requirements=[SemanticRequirement(
            domain="resource", metric="resource_rank", mineral="코발트", scope="WORLD",
            operation="argmax",
        )])
        _, action_plan = resolve_semantic_plan(plan, "코발트 생산량 기준으로 어디가 제일 커?")
        action = action_plan.actions[0]
        self.assertEqual(action.action_id, "resource.rank")
        self.assertEqual(action.slots.top_n, 1)

    def test_resource_rank_reserves_is_not_mine_profile(self):
        plan = SemanticPlan(requirements=[SemanticRequirement(
            domain="resource", metric="resource_rank", mineral="희토류", scope="WORLD",
            operation="reserves",
        )])
        _, action_plan = resolve_semantic_plan(plan, "희토류 매장량 상위 국가를 알려줘")
        action = action_plan.actions[0]
        self.assertEqual(action.action_id, "resource.rank")
        self.assertEqual(action.slots.metric, "reserves")

    def test_resource_rank_composite_keeps_both_requested_metrics(self):
        plan = SemanticPlan(requirements=[
            SemanticRequirement(
                domain="resource", metric="resource_rank", mineral="희토류", scope="WORLD",
            ),
            SemanticRequirement(
                domain="resource", metric="resource_rank", mineral="희토류", scope="WORLD",
                operation="reserves",
            ),
        ])
        _, action_plan = resolve_semantic_plan(plan, "희토류 생산량 상위 국가와 매장량 상위 국가를 각각 알려줘")
        self.assertEqual(len(action_plan.actions), 2)
        self.assertEqual(
            [(item.action_id, item.slots.metric, item.slots.top_n) for item in action_plan.actions],
            [("resource.rank", "production", 5), ("resource.rank", "reserves", 5)],
        )
        # The regression contract is the requested metric set, not just action count.
        self.assertEqual(
            {item.slots.metric for item in action_plan.actions},
            {"production", "reserves"},
        )

    def test_resource_rank_composite_variant_has_same_metric_set(self):
        plan = SemanticPlan(requirements=[
            SemanticRequirement(
                domain="resource", metric="resource_rank", mineral="희토류", scope="WORLD",
            ),
            SemanticRequirement(
                domain="resource", metric="resource_rank", mineral="희토류", scope="WORLD",
                operation="reserves",
            ),
        ])
        _, action_plan = resolve_semantic_plan(plan, "희토류 생산량과 매장량 상위 국가를 각각 알려줘")
        self.assertEqual(
            {item.slots.metric for item in action_plan.actions},
            {"production", "reserves"},
        )

    def test_independent_comparison_keeps_each_requirement_and_action(self):
        plan = SemanticPlan(requirements=[
            SemanticRequirement(
                domain="resource", metric="resource_rank", mineral="구리", scope="WORLD",
            ),
            SemanticRequirement(
                domain="resource", metric="resource_rank", mineral="구리", scope="WORLD",
                operation="reserves",
            ),
            SemanticRequirement(
                domain="trade", metric="country_rank", mineral="구리", flow="import", scope="KR",
            ),
        ])
        intent_plan, action_plan = resolve_semantic_plan(
            plan, "구리 생산량·매장량 상위국과 한국 수입국을 각각 비교해줘",
        )
        self.assertEqual(len(intent_plan.requirements), 3)
        self.assertEqual(len(action_plan.actions), 3)
        self.assertEqual(
            [(item.action_id, item.slots.metric) for item in action_plan.actions],
            [("resource.rank", "production"), ("resource.rank", "reserves"),
             ("trade.country_rank", "import_amount")],
        )

    def test_semantic_resolution_fails_closed_if_mapper_drops_a_requirement(self):
        duplicate = SemanticRequirement(
            domain="resource", metric="resource_rank", mineral="구리", scope="WORLD",
        )
        with self.assertRaisesRegex(SemanticResolutionError, "independent_requirement_dropped"):
            resolve_semantic_plan(
                SemanticPlan(requirements=[duplicate, duplicate]),
                "구리 생산량 상위국을 두 번 각각 알려줘",
            )

    def test_parser_boundary_preserves_composite_requirements_before_resolution(self):
        parsed_plan = SemanticPlan(requirements=[
            SemanticRequirement(
                domain="resource", metric="resource_rank", mineral="희토류", scope="WORLD",
            ),
            SemanticRequirement(
                domain="resource", metric="resource_rank", mineral="희토류", scope="WORLD",
                operation="reserves",
            ),
        ])
        result = parse_and_resolve(
            "희토류 생산량 상위 국가와 매장량 상위 국가를 각각 알려줘",
            SemanticLLM(parsed_plan),
        )
        self.assertIsNone(result.reason)
        self.assertEqual(len(result.semantic_plan.requirements), 2)
        self.assertEqual(
            {item.operation for item in result.semantic_plan.requirements},
            {None, "reserves"},
        )
        self.assertEqual(
            {item.slots.metric for item in result.action_plan.actions},
            {"production", "reserves"},
        )

    def test_global_export_scope_world_alias_resolves_to_global_trade_rank(self):
        plan = SemanticPlan(requirements=[SemanticRequirement(
            domain="trade", metric="country_rank", mineral="리튬", flow="export", scope="WORLD",
        )])
        _, action_plan = resolve_semantic_plan(plan, "리튬 주요 수출국을 알려줘")
        action = action_plan.actions[0]
        self.assertEqual(action.action_id, "trade.country_rank")
        self.assertEqual(action.slots.trade_scope, "global")

    def test_known_battery_group_expands_to_independent_trade_actions(self):
        plan = SemanticPlan(requirements=[SemanticRequirement(
            domain="trade", metric="country_rank", minerals=["리튬", "니켈"], flow="import", scope="KR",
        )])
        _, action_plan = resolve_semantic_plan(plan, "2차전지 광물 수입국 구성 알려줘")
        self.assertEqual([item.action_id for item in action_plan.actions], ["trade.country_rank", "trade.country_rank"])
        self.assertEqual([item.slots.mineral for item in action_plan.actions], ["리튬", "니켈"])

    def test_strategic_price_group_maps_to_existing_overview_action(self):
        plan = SemanticPlan(requirements=[SemanticRequirement(
            domain="price", metric="current", price_group="strategic",
        )])
        _, action_plan = resolve_semantic_plan(plan, "전략광종 가격 현황 한눈에 보여줘")
        action = action_plan.actions[0]
        self.assertEqual(action.action_id, "price.overview")
        self.assertEqual(action.slots.strategic_price_groups, ["strategic_six", "strategic_ten"])

    def test_document_facts_keeps_the_existing_derived_facts_action(self):
        plan = SemanticPlan(requirements=[SemanticRequirement(
            domain="document", metric="facts", topic="2026년 4월 희소금속 월간동향 광종 목록",
        )])
        _, action_plan = resolve_semantic_plan(plan, "2026년 4월 희소금속 월간동향 광종 목록")
        self.assertEqual(action_plan.actions[0].action_id, "document.facts.retrieve")

    def test_concept_topic_completes_omitted_mineral_slot(self):
        plan = SemanticPlan(requirements=[SemanticRequirement(
            domain="concept", metric="retrieve", topic="구리의 기본적인 성질",
        )])
        _, action_plan = resolve_semantic_plan(plan, "구리의 기본적인 성질을 설명해 주세요")
        action = action_plan.actions[0]
        self.assertEqual(action.action_id, "document.retrieve")
        self.assertEqual(action.slots.mineral, "구리")

    def test_unsupported_semantic_combination_falls_back_with_reason(self):
        llm = SemanticLLM(SemanticPlan(requirements=[SemanticRequirement(
            domain="trade", metric="concentration", flow="export", mineral="니켈", scope="KR",
        )]))
        result = parse_and_resolve("니켈 수출 집중도", llm)
        self.assertIsNotNone(result.semantic_plan)
        self.assertIsNone(result.action_plan)
        self.assertIn("trade concentration", result.reason or "")


if __name__ == "__main__":
    unittest.main()
