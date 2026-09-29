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

from rag_core.ragkit.action_contract import ActionPlan, extract_action_plan  # noqa: E402
from rag_core.ragkit.semantic_intent import (  # noqa: E402
    SemanticPlan,
    SemanticRequirement,
    canonical_signature,
    parse_and_resolve,
    resolve_semantic_plan,
)


class SemanticLLM:
    def __init__(self, plan: SemanticPlan):
        self.plan = plan
        self.tasks: list[str] = []

    def invoke(self, **kwargs):
        self.tasks.append(kwargs["task"])
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

    def test_enabled_mode_uses_semantic_parser_after_legacy_shortcut_miss(self):
        llm = SemanticLLM(_concentration_plan())
        with patch.dict(os.environ, {"SEMANTIC_INTENT_MODE": "enabled"}, clear=False):
            plan = extract_action_plan("니켈 수입선이 편중되어 있어?", llm)
        self.assertIsInstance(plan, ActionPlan)
        self.assertEqual(plan.actions[0].action_id, "trade.concentration")
        self.assertEqual(plan.actions[0].requirement_id, "import_concentration")
        self.assertEqual(llm.tasks, ["semantic_intent"])

    def test_enabled_mode_preserves_deterministic_legacy_shortcut(self):
        llm = SemanticLLM(_concentration_plan())
        with patch.dict(os.environ, {"SEMANTIC_INTENT_MODE": "enabled"}, clear=False):
            plan = extract_action_plan("니켈 수입 집중도를 알려줘", llm)
        self.assertEqual(plan.actions[0].action_id, "trade.concentration")
        self.assertEqual(llm.tasks, [])

    def test_shadow_mode_records_semantic_call_but_returns_legacy_plan(self):
        llm = SemanticLLM(_concentration_plan())
        with self.assertLogs("rag_core.ragkit.semantic_intent", level="INFO") as logs:
            with patch.dict(os.environ, {"SEMANTIC_INTENT_MODE": "shadow"}, clear=False):
                plan = extract_action_plan("니켈 수입 집중도를 알려줘", llm)
        self.assertEqual(plan.actions[0].requirement_id, "import_concentration")
        self.assertEqual(llm.tasks, ["semantic_intent"])
        self.assertIn("semantic_canonical_signature", "\n".join(logs.output))
        self.assertIn("semantic_resolved_action_plan", "\n".join(logs.output))
        self.assertIn("semantic_fallback_reason", "\n".join(logs.output))

    def test_first_order_inventory_capability_resolves_to_existing_action(self):
        plan = SemanticPlan(requirements=[SemanticRequirement(
            domain="inventory", metric="latest", mineral="니켈", scope="KR",
        )])
        _, action_plan = resolve_semantic_plan(plan, "니켈 재고 알려줘")
        self.assertEqual(action_plan.actions[0].action_id, "inventory.latest")

    def test_price_forecast_resolves_to_existing_forecast_action(self):
        plan = SemanticPlan(requirements=[SemanticRequirement(
            domain="price", metric="price_forecast", mineral="니켈",
            period={"kind": "future_horizon", "future_horizon": 1},
        )])
        _, action_plan = resolve_semantic_plan(plan, "니켈 다음달 가격 전망 알려줘")
        action = action_plan.actions[0]
        self.assertEqual(action.action_id, "forecast.price")
        self.assertEqual(action.slots.forecast_operation, "next_month_value")

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
