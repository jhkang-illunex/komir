# -*- coding: utf-8 -*-
"""라우터 JSON 장애의 결정적 안전망 회귀 테스트.

실제 LLM·DB·MCP를 호출하지 않는다. 고정질문에 필요한 좁은 폴백과 광종별
광물종합지수의 검색 차단만 검사한다.
"""
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import call, patch

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
    def setUp(self):
        # MCP transport 직전만 격리한다. 실제 정책·요청 직렬화·Evidence 변환은 실행한다.
        contexts = ExitStack()
        self.addCleanup(contexts.close)
        self.public_call = contexts.enter_context(patch.object(
            graph.mcp_client.public, "_call", autospec=True,
            side_effect=AssertionError("예상하지 않은 public MCP 호출"),
        ))
        self.private_call = contexts.enter_context(patch.object(
            graph.mcp_client.private, "_call", autospec=True,
            side_effect=AssertionError("접근 제한 테스트의 private MCP 호출"),
        ))

    def tearDown(self):
        self.private_call.assert_not_called()

    def test_composite_index_is_publicly_allowed(self):
        # 합성 fixture이며 실제 index/DB 값 또는 MCP E2E 검증이 아니다.
        fixture_evidence = {
            "kind": "structured", "source": "public.KO_MNRL_SNTHS_INDX",
            "section": "synthetic composite index fixture",
            "text": "| indx_se_cd | crtr_ymd | indx |\n| HI001 | 20250101 | 123.0 |",
            "as_of": "2025-01-01", "unit": "index",
            "menu_page_id": "indicator_composite",
        }
        responses = {
            "komis_raw_lookup": {"evidence": [fixture_evidence], "warnings": []},
            "hybrid_search": {"evidence": []},
            "pageindex_lookup": {"nodes": []},
        }
        self.public_call.side_effect = lambda tool, arguments: responses[tool]
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
        self.assertTrue(result["evidence"])
        self.assertEqual(result["evidence"], [graph.Evidence(
            **fixture_evidence, requirement_id="req_1", action_id="indicator.series",
            source_id=fixture_evidence["source"], observed_period=fixture_evidence["as_of"],
        )])
        self.assertEqual(result["warnings"], [
            "source_audit:rdb:queried:1", "source_audit:vector:queried:0",
            "source_audit:pageindex:queried:0", "source_audit:okf:unavailable:0",
        ])
        self.assertEqual(self.public_call.call_count, 3)
        self.public_call.assert_has_calls([
            call("komis_raw_lookup", {
                "page_id": "indicator_composite", "mineral_code": None,
                "hs_code": None, "index_type_code": None,
                "price_criterion_serial": None, "criterion_mode": "REPRESENTATIVE",
                "start_period": None,
                "end_period": None,
            }),
            call("hybrid_search", {"query": route.resolved_query, "k": 1}),
            call("pageindex_lookup", {
                "query": route.resolved_query, "doc": None, "node_limit": 1,
                "with_text": True, "body_fallback": False, "body_query": None,
            }),
        ], any_order=True)
        self.assertNotIn(graph._PRIVATE_ONLY_PROFILE_WARNING, result["warnings"])
        self.assertNotIn("access_denied", result["warnings"])
        self.assertEqual(graph._route_after_verify({"warnings": result["warnings"]}), "done")

    def test_restricted_market_and_supply_indicators_stop_for_all_profiles(self):
        for page_id, question in (
            ("indicator_market", "리튬 시장동향지표 알려줘"),
            ("indicator_supply", "리튬 수급동향지표 알려줘"),
        ):
            route = graph.RetrievalRoute(
                resolved_query=question, use_structured=False, use_dense=True,
                use_pageindex=True, use_komis_indicator_ranking=True,
                komis_indicator_ranking_page=page_id,
            )
            for profile in ("public", "private"):
                result = graph._retrieve_node(
                    {"route": route, "profile": profile, "warnings": [],
                     "source_assessment": SourceAssessment(),
                     "action_assessment": _action_assessment(
                         "indicator.series", indicator=(
                             "market_outlook" if page_id == "indicator_market"
                             else "supply_stability"
                         ),
                     )},
                    dense_k=1, pageindex_k=1,
                )
                self.assertEqual(result["evidence"], [])
                self.assertIn("access_denied", result["warnings"])
                self.assertEqual(graph._route_after_verify({"warnings": result["warnings"]}), "done")
                reason, text = chatbot._resolve_abstain(question, result["warnings"], None)
                self.assertEqual(reason, "access_denied")
                self.assertEqual(text, "접근 권한이 없어 조회할 수 없습니다.")
        self.public_call.assert_not_called()

    def test_restricted_indicator_without_mineral_cannot_fall_back_to_documents(self):
        route = graph.RetrievalRoute(
            resolved_query="시장동향지표 알려줘", use_structured=False,
            use_dense=True, use_pageindex=True, use_komis_raw=True,
            komis_topic="market_outlook",
        )
        result = graph._retrieve_node(
            {"route": route, "profile": "public", "warnings": [],
             "source_assessment": SourceAssessment()}, dense_k=1, pageindex_k=1,
        )
        self.assertEqual(result["evidence"], [])
        self.assertIn("access_denied", result["warnings"])
        self.public_call.assert_not_called()

    def test_restricted_indicator_is_rejected_before_action_llm_or_retrieval(self):
        class MustNotRun:
            def invoke(self, **kwargs):
                raise AssertionError("접근 제한 지표는 Action/검색 LLM을 호출하면 안 됨")

        result = graph.retrieve_evidence(
            "수급동향지표와 가격을 같이 보여줘",
            llm=MustNotRun(), include_action_results=True,
        )
        self.assertEqual(result.evidence, [])
        self.assertEqual(result.warnings, ["access_denied"])
        self.public_call.assert_not_called()


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
