# -*- coding: utf-8 -*-
"""라우터 JSON 장애의 결정적 안전망 회귀 테스트.

실제 LLM·DB·MCP를 호출하지 않는다. 고정질문에 필요한 좁은 폴백과 광종별
광물종합지수의 검색 차단만 검사한다.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.llm_client import LLMOutputError  # noqa: E402
from rag_core.ragkit import chatbot  # noqa: E402
from rag_core.ragkit import chatbot_graph as graph  # noqa: E402
from rag_core.ragkit.action_contract import ActionCall, ActionPlan, ActionSlots, validate_action_plan  # noqa: E402
from rag_core.ragkit.source_contract import SourceAssessment  # noqa: E402


def _action_assessment(action_id, **slots):
    plan = ActionPlan(actions=[ActionCall(requirement_id="req_1", action_id=action_id, slots=ActionSlots(**slots))])
    return validate_action_plan(plan)


class _InvalidJsonLLM:
    def invoke(self, **kwargs):
        raise LLMOutputError("route JSON truncated")


class SafeFallbackTest(unittest.TestCase):
    def test_route_budget_is_large_enough_for_full_schema(self):
        self.assertGreaterEqual(graph.RETRIEVAL_ROUTE_MAX_TOKENS, 1024)
        self.assertLessEqual(graph.RETRIEVAL_ROUTE_MAX_TOKENS, 1536)

    def test_invalid_route_fails_closed_without_valid_action_plan(self):
        result = graph._route_node({"question": "니켈 최근 1년 가격 추이를 보여줘"}, _InvalidJsonLLM())
        route = result["route"]
        self.assertFalse(route.use_komis_raw)
        self.assertFalse(route.use_dense)
        self.assertFalse(route.use_pageindex)
        self.assertIn("source_unavailable:invalid_plan", result["warnings"])

    def test_invalid_route_recovers_single_mineral_country_rankings(self):
        trade = graph._safe_route_fallback("리튬 수입 상위 5개국과 비중을 알려줘")
        self.assertIsNotNone(trade)
        assert trade is not None
        self.assertTrue(trade.use_komis_ranking)
        self.assertEqual(trade.komis_ranking_metric, "import_amount")
        self.assertEqual(trade.komis_ranking_top_n, 5)

        mineral = graph._safe_route_fallback("희토류 생산량과 매장량 상위 국가를 알려줘")
        self.assertIsNotNone(mineral)
        assert mineral is not None
        self.assertTrue(mineral.use_komis_mineral_ranking)
        self.assertEqual(mineral.komis_mineral_ranking_metrics, ["production", "reserves"])

    def test_fallback_does_not_overinterpret_multiple_minerals_or_mines(self):
        self.assertIsNone(graph._safe_route_fallback("니켈과 리튬 중 생산량 1위 국가는 어디야?"))
        self.assertIsNone(graph._safe_route_fallback("니켈 광산 중 생산량 1위는 어디야?"))
        self.assertIsNone(graph._safe_route_fallback("니켈 데이터 보여줘"))


class MineralSpecificCompositeIndexTest(unittest.TestCase):
    def test_specific_composite_index_is_abstained_before_retrieval_or_retry(self):
        route = graph._safe_route_fallback("코발트 광물종합지표의 최근 12개월 변화를 보여줘")
        self.assertIsNotNone(route)
        assert route is not None
        self.assertTrue(route.is_mineral_specific_composite_index)

        result = graph._retrieve_node(
            {"route": route, "warnings": [], "action_assessment": _action_assessment(
                "indicator.series", mineral="코발트", indicator="composite_index")}, dense_k=1, pageindex_k=1,
        )
        self.assertEqual(result["evidence"], [])
        self.assertIn("action_plan_failed:source_unavailable", result["warnings"])
        self.assertEqual(graph._route_after_verify({"warnings": result["warnings"]}), "done")
        reason, text = chatbot._resolve_abstain("코발트 광물종합지표", result["warnings"], None)
        self.assertEqual(reason, "source_unavailable")

    def test_non_specific_composite_index_remains_available_to_normal_route(self):
        route = graph.RetrievalRoute(
            resolved_query="광물종합지수 최근 12개월 변화를 보여줘",
            use_structured=False, use_dense=False, use_pageindex=False,
            use_komis_raw=True, komis_topic="composite_index",
        )
        self.assertFalse(graph._is_mineral_specific_composite_index(route.resolved_query, route))


class PublicPrivateBoundaryTest(unittest.TestCase):
    def test_public_private_only_indicator_stops_before_fallback_search(self):
        route = graph.RetrievalRoute(
            resolved_query="광물종합지수 알려줘",
            use_structured=False, use_dense=True, use_pageindex=True,
            use_komis_raw=True, komis_topic="composite_index",
        )
        result = graph._retrieve_node(
            {"route": route, "profile": "public", "warnings": [],
             "source_assessment": SourceAssessment(),
             "action_assessment": _action_assessment("indicator.series", indicator="composite_index")}, dense_k=1, pageindex_k=1,
        )
        self.assertEqual(result["evidence"], [])
        self.assertIn(graph._PRIVATE_ONLY_PROFILE_WARNING, result["warnings"])
        self.assertEqual(graph._route_after_verify({"warnings": result["warnings"]}), "done")
        reason, text = chatbot._resolve_abstain("광물종합지수 알려줘", result["warnings"], None)
        self.assertEqual(reason, "private_only_profile_access")
        self.assertIn("private 프로필 전용", text)


class ExplicitHsCodeTest(unittest.TestCase):
    def test_explicit_hs_code_reaches_raw_lookup_without_mineral_remap(self):
        calls = []

        class _PublicSession:
            def call_komis_raw_lookup(self, page_id, **kwargs):
                calls.append((page_id, kwargs))
                return [], []

        route = graph.RetrievalRoute(
            resolved_query="HS코드 2603000000의 한국 수입 현황",
            use_structured=False, use_dense=False, use_pageindex=False,
            use_komis_raw=True, komis_topic="domestic_trade", komis_hs_code="2603000000",
        )
        with patch.object(graph.mcp_client, "public", _PublicSession()):
            result = graph._retrieve_node(
                {"route": route, "profile": "public", "warnings": [],
                 "source_assessment": SourceAssessment(),
                 "action_assessment": _action_assessment("trade.hs_summary", hs_code="2603000000")}, dense_k=1, pageindex_k=1,
            )
        self.assertEqual(result["evidence"], [])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "map_korea")
        self.assertEqual(calls[0][1]["hs_code"], "2603000000")
        self.assertIsNone(calls[0][1]["mineral_code"])


class CountryConcentrationTest(unittest.TestCase):
    def test_hhi_fallback_uses_dedicated_full_population_tool(self):
        route = graph._safe_route_fallback("니켈 수입국 집중도를 HHI로 계산해줘")
        self.assertIsNotNone(route)
        assert route is not None
        self.assertTrue(route.use_komis_concentration)
        self.assertFalse(route.use_komis_ranking)

    def test_concentration_route_calls_only_concentration_tool(self):
        calls = []

        class _PublicSession:
            def call_komis_resolve_mineral(self, name):
                if name != "니켈":
                    raise AssertionError(name)
                return {"mineral_code": "MNRL-NI", "warnings": []}

            def call_komis_country_concentration(self, mineral_code, **kwargs):
                calls.append((mineral_code, kwargs))
                return [], []

        route = graph.RetrievalRoute(
            resolved_query="니켈 수입국 집중도를 HHI로 계산해줘",
            use_structured=False, use_dense=False, use_pageindex=False,
            komis_mineral_name="니켈", use_komis_concentration=True,
        )
        with patch.object(graph.mcp_client, "public", _PublicSession()):
            result = graph._retrieve_node(
                {"route": route, "profile": "public", "warnings": [],
                 "source_assessment": SourceAssessment(),
                 "action_assessment": _action_assessment("trade.concentration", mineral="니켈")}, dense_k=1, pageindex_k=1,
            )
        self.assertEqual(result["evidence"], [])
        self.assertEqual(calls, [("MNRL-NI", {"start_period": None, "end_period": None})])


if __name__ == "__main__":
    unittest.main()
