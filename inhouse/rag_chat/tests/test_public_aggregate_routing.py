# -*- coding: utf-8 -*-
"""공개 원천 집계 질문이 미리보기·광산 경로로 새지 않는지 확인한다."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rag_core.ragkit import chatbot_graph as graph  # noqa: E402


def _base(**kwargs):
    return graph.RetrievalRoute(
        resolved_query="", use_structured=False, use_dense=True, use_pageindex=False,
        **kwargs,
    )


class PublicAggregateRouteTest(unittest.TestCase):
    def test_monthly_trade_uses_full_population_aggregate(self):
        route = _base(komis_mineral_name="코발트", use_mine_aggregate=True, use_komis_raw=True,
                      komis_topic="domestic_trade")
        result = graph._apply_aggregate_route(
            {"question": "한국의 코발트 수입액과 수입중량의 최근 12개월 추이", "history": []}, route)
        self.assertTrue(result.use_komis_monthly_trade)
        self.assertFalse(result.use_komis_raw)
        self.assertFalse(result.use_mine_aggregate)

    def test_explicit_hs_never_uses_mineral_mapping(self):
        route = _base(use_komis_raw=True, komis_topic="domestic_trade")
        result = graph._apply_aggregate_route(
            {"question": "HS코드 2603000000의 품목명과 한국 수입 현황", "history": []}, route)
        self.assertTrue(result.use_komis_explicit_hs_summary)
        self.assertEqual(result.komis_hs_code, "2603000000")
        self.assertFalse(result.use_komis_raw)

    def test_production_and_import_shares_use_both_populations(self):
        route = _base(komis_mineral_name="구리")
        result = graph._apply_aggregate_route(
            {"question": "구리의 세계 생산국 비중과 한국의 수입국 비중을 비교", "history": []}, route)
        self.assertTrue(result.use_komis_mineral_ranking)
        self.assertTrue(result.use_komis_ranking)
        self.assertEqual(result.komis_mineral_ranking_metrics, ["production"])
        self.assertEqual(result.komis_ranking_page, "map_korea")

    def test_price_window_comparison_keeps_all_windows(self):
        route = _base(komis_mineral_name="리튬")
        result = graph._apply_aggregate_route(
            {"question": "리튬 가격의 최근 3개월, 6개월, 1년 변화를 비교", "history": []}, route)
        self.assertTrue(result.use_komis_price_comparison)
        self.assertEqual(result.komis_compare_mineral_names, ["리튬"])
        self.assertEqual(result.komis_price_windows_months, [3, 6, 12])

    def test_recent_volatility_rank_overrides_generic_price_comparison_action(self):
        # Action planner가 price.compare로 투영한 경우에도 변동성은 절댓값
        # 변동률 랭킹 도구와 최근 3개월 기본 창으로 보정해야 한다.
        route = _base(use_komis_price_comparison=True,
                      komis_compare_mineral_names=["니켈", "리튬"])
        result = graph._apply_aggregate_route(
            {"question": "니켈과 리튬 중 최근 변동성이 큰 광물은?", "history": []}, route)
        self.assertTrue(result.use_komis_price_volatility_ranking)
        self.assertFalse(result.use_komis_price_comparison)
        self.assertEqual(result.komis_compare_mineral_names, ["니켈", "리튬"])
        self.assertEqual(result.komis_relative_months, 3)

    def test_price_followup_uses_previous_actual_period(self):
        route = _base(komis_mineral_name="코발트", komis_compare_mineral_names=["코발트"])
        history = [
            {"role": "user", "content": "니켈 가격 추이 좀 보여줘."},
            {"role": "assistant", "content": "니켈 가격 추이 (실제 조회기간: 2026-09-02\\~2026-09-08)"},
        ]
        result = graph._apply_aggregate_route(
            {"question": "그럼 같은 기간 코발트와 비교해줘", "history": history}, route)
        self.assertEqual(set(result.komis_compare_mineral_names or []), {"니켈", "코발트"})
        self.assertEqual((result.komis_start_period, result.komis_end_period),
                         ("20260902", "20260908"))
        self.assertFalse(result.use_mine_aggregate)

    def test_aggregate_incomplete_stops_search_retry(self):
        route = _base(use_komis_monthly_trade=True)
        state = {"route": route, "sufficient": False, "attempt": 1,
                 "warnings": ["aggregate_incomplete:komis_monthly_trade"]}
        self.assertEqual(graph._route_after_verify(state), "done")
        self.assertTrue(graph._has_deterministic_abstain_signal(state["warnings"]))

    def test_annual_trade_comparison_clears_unrelated_price_route(self):
        route = _base(komis_mineral_name="리튬", use_komis_price_comparison=True,
                      use_komis_concentration=True)
        result = graph._apply_aggregate_route(
            {"question": "2026년 1월부터 12월까지 리튬 수입액을 2025년 연간 수입액과 비교", "history": []}, route)
        self.assertTrue(result.use_komis_monthly_trade)
        self.assertFalse(result.use_komis_price_comparison)
        self.assertFalse(result.use_komis_concentration)


if __name__ == "__main__":
    unittest.main()
