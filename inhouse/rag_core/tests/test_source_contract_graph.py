# -*- coding: utf-8 -*-
"""그래프가 미연결 결과형 요청에 검색 안전망을 열지 않는지 검사한다."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rag_core.ragkit import chatbot_graph as graph  # noqa: E402
from rag_core.retrieval.evidence import Evidence  # noqa: E402


class _NeverCalledLLM:
    def invoke(self, **kwargs):
        raise AssertionError("미연결 요청은 LLM 라우팅 이전에 차단되어야 합니다")


class SourceContractGraphTest(unittest.TestCase):
    def test_blocked_request_never_routes_to_dense_or_pageindex(self):
        question = "광종별 수급위기 위험 점수와 주요 원인을 알려줘"
        routed = graph._route_node({"question": question}, _NeverCalledLLM())
        route = routed["route"]
        self.assertFalse(route.use_dense)
        self.assertFalse(route.use_pageindex)
        self.assertFalse(route.use_komis_raw)
        self.assertTrue(any(w.startswith("source_unavailable:") for w in routed["warnings"]))

        with patch.object(graph.mcp_client, "public") as public:
            retrieved = graph._retrieve_node(
                {"question": question, "route": route, "warnings": routed["warnings"]},
                dense_k=1, pageindex_k=1,
            )
        self.assertEqual(retrieved["evidence"], [])
        public.assert_not_called()

    def test_generic_price_parser_has_no_fixed_mineral_list(self):
        self.assertEqual(
            graph._comparison_minerals_in_text("텅스텐과 주석 가격을 비교해줘"),
            ["텅스텐", "주석"],
        )

    def test_price_claim_verification_uses_same_aggregate_route_for_any_threshold(self):
        route = graph.RetrievalRoute(
            resolved_query="", use_structured=False, use_dense=False, use_pageindex=False,
            komis_mineral_name="텅스텐",
        )
        for question in (
            "2025년 텅스텐 가격이 300% 올랐다는 전제가 맞나?",
            "텅스텐 가격이 150% 올랐다는 전제가 데이터와 맞는지 검증해줘",
            "텅스텐 가격 400% 급등 주장을 원자료로 확인해줘",
        ):
            with self.subTest(question=question):
                result = graph._apply_aggregate_route({"question": question, "history": []}, route)
                self.assertTrue(result.use_komis_price_comparison)
                self.assertEqual(result.komis_compare_mineral_names, ["텅스텐"])

    def test_simple_price_trend_does_not_force_claim_comparison(self):
        route = graph.RetrievalRoute(
            resolved_query="", use_structured=False, use_dense=False, use_pageindex=False,
            komis_mineral_name="텅스텐",
        )
        result = graph._apply_aggregate_route({"question": "텅스텐 가격 추이를 보여줘", "history": []}, route)
        self.assertFalse(result.use_komis_price_comparison)

    def test_existing_route_minerals_are_not_polluted_by_sentence_fragments(self):
        route = graph.RetrievalRoute(
            resolved_query="", use_structured=False, use_dense=False, use_pageindex=False,
            komis_compare_mineral_names=["구리", "니켈", "코발트"],
        )
        result = graph._apply_aggregate_route(
            {"question": "구리, 니켈, 코발트의 최근 1년 가격 추이를 비교해줘", "history": []}, route)
        self.assertEqual(result.komis_compare_mineral_names, ["구리", "니켈", "코발트"])

    def test_supported_evidence_indices_remove_unrelated_dense_document(self):
        class _VerifyLLM:
            def invoke(self, **kwargs):
                return SimpleNamespace(output=graph.GroundingCheck(
                    sufficient=True, supported_evidence_indices=[1],
                ))

        price = Evidence(kind="structured", source="KOMIS 가격", section="니켈", text="니켈 가격")
        unrelated = Evidence(kind="dense", source="Vale 철광석", section="사업", text="iron ore")
        state = {
            "route": graph.RetrievalRoute(resolved_query="니켈 가격과 매장량", use_structured=False,
                                            use_dense=False, use_pageindex=False),
            "evidence": [price, unrelated], "warnings": [], "question": "니켈 가격과 매장량",
        }
        result = graph._verify_node(state, _VerifyLLM())
        self.assertTrue(result["sufficient"])
        self.assertEqual(result["evidence"], [price])

    def test_single_structured_price_request_prunes_dense_safety_net(self):
        price = Evidence(kind="structured", source="KOMIS 가격", section="니켈", text="니켈 가격")
        dense = Evidence(kind="dense", source="무관 문서", section="사업", text="사업 설명")
        result = graph._finalize_node({
            "question": "니켈 최근 1년 가격 추이를 보여줘", "attempt": 1,
            "sufficient": True, "evidence": [price, dense],
        })
        self.assertEqual(result["evidence"], [price])

    def test_single_structured_price_still_runs_advisor_without_dense_noise(self):
        class _ApprovingLLM:
            def invoke(self, **kwargs):
                self.payload = kwargs["payload"]
                return SimpleNamespace(output=graph.GroundingCheck(sufficient=True, supported_evidence_indices=[1]))

        price = Evidence(kind="structured", source="KOMIS 가격", section="니켈", text="니켈 가격")
        dense = Evidence(kind="dense", source="무관 문서", section="사업", text="사업 설명")
        state = {
            "question": "최근 1년간 니켈 가격 추이를 보여줘", "warnings": [],
            "route": graph.RetrievalRoute(resolved_query="니켈 가격", use_structured=False,
                                            use_dense=False, use_pageindex=False),
            "evidence": [price, dense],
        }
        llm = _ApprovingLLM()
        result = graph._verify_node(state, llm)
        self.assertTrue(result["sufficient"])
        self.assertEqual(result["evidence"], [price])
        self.assertEqual(len(llm.payload["evidence"]), 1)
        self.assertEqual(llm.payload["evidence"][0]["source"], "KOMIS 가격")


if __name__ == "__main__":
    unittest.main()
