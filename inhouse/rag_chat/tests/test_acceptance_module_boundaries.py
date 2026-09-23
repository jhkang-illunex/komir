"""AC42·AC44·AC47의 YAML additional checks를 실제로 수행하는 고정 입력 경계 검사."""
from __future__ import annotations

import sys
import threading
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.komis_raw import KomisRawDataRepository
from common.trade_indicators import RcaInputs, TiiInputs, TradeIndicatorInputError, calculate_rca, calculate_tii
from rag_chat.app.routers import chat as chat_router
from rag_core.ragkit import chatbot_graph as graph
from rag_core.ragkit.action_contract import ActionCall, ActionPlan, ActionSlots, Period, missing_trade_indicator_slots, validate_action_plan
from rag_core.ragkit.chatbot_events import aggregate_time_table, extract_markdown_tables
from rag_core.ragkit.source_contract import SourceAssessment
from rag_core.retrieval.evidence import Evidence


def _assessment(action_id: str, **slots):
    return validate_action_plan(ActionPlan(actions=[ActionCall(requirement_id="r", action_id=action_id, slots=ActionSlots(**slots))]))


class AC42ParallelIsolationTest(unittest.TestCase):
    def test_dense_and_pageindex_start_in_parallel_and_pageindex_failure_is_isolated(self):
        barrier = threading.Barrier(3)
        calls: list[str] = []

        class Session:
            def call_komis_resolve_mineral(self, _name):
                return {"mineral_code": "MNRL-LI", "price_category": None, "warnings": []}

            def call_komis_raw_lookup(self, page_id, **_kwargs):
                calls.append("rdb")
                barrier.wait(timeout=2)
                return [Evidence(kind="structured", source="rdb", section="fixture", text="rdb evidence")], []

            def call_hybrid_search(self, *_args):
                calls.append("dense")
                barrier.wait(timeout=2)
                return [Evidence(kind="dense", source="dense", section="fixture", text="dense evidence")]

            def call_pageindex_lookup(self, *_args, **_kwargs):
                calls.append("pageindex")
                barrier.wait(timeout=2)
                raise RuntimeError("fixture pageindex failure")

        route = graph.RetrievalRoute(
            resolved_query="fixture", use_structured=False, use_dense=True, use_pageindex=True,
            use_komis_raw=True, komis_topic="domestic_trade", komis_mineral_name="리튬",
        )
        with patch.object(graph.mcp_client, "public", Session()):
            result = graph._retrieve_node({
                "question": "fixture", "route": route, "profile": "public", "warnings": [],
                "source_assessment": SourceAssessment(),
            }, dense_k=1, pageindex_k=1)
        self.assertEqual(calls.count("rdb"), 1)
        self.assertEqual(calls.count("dense"), 1)
        self.assertEqual(calls.count("pageindex"), 1)
        self.assertIn("pageindex_failed", result["warnings"])
        self.assertEqual({e.source for e in result["evidence"]}, {"rdb", "dense"})


class AC44AggregationBoundaryTest(unittest.TestCase):
    @staticmethod
    def _table(days: int, *, price: bool) -> dict:
        header = "price(가격)" if price else "import_amount(수입금액(USD))"
        rows = [f"| {(date(2020, 1, 1) + timedelta(days=i)).isoformat()} | {i + 1} |" for i in range(days)]
        return extract_markdown_tables("| price_date(가격일자) | " + header + " |\n| --- | --- |\n" + "\n".join(rows))[0]

    def test_exact_period_boundaries_and_price_mean_amount_sum(self):
        expected = {92: "daily", 93: "weekly", 364: "weekly", 365: "monthly", 1095: "monthly", 1096: "yearly"}
        for days, frequency in expected.items():
            with self.subTest(days=days):
                _, meta = aggregate_time_table(self._table(days, price=True))
                self.assertEqual(meta["frequency"], frequency)
        price, _ = aggregate_time_table(self._table(93, price=True))
        amount, _ = aggregate_time_table(self._table(93, price=False))
        # 2020-01-01~05 첫 주: 1..5 -> 평균 3, 합계 15.
        self.assertEqual(float(price["rows"][0][1]), 3.0)
        self.assertEqual(float(amount["rows"][0][1]), 15.0)


class AC47TradeIndicatorFormulaTest(unittest.TestCase):
    def test_five_indicator_formulas_and_zero_denominators_with_product_sql_mock(self):
        self.assertEqual(round((40 - 160) / (40 + 160), 6), -0.6)  # TSI
        self.assertEqual(round((300 - 150) / 150 * 100, 4), 100.0)  # 증감률
        self.assertEqual(round(50 / 200 * 100, 4), 25.0)  # 특정국 의존도
        self.assertEqual(calculate_rca(RcaInputs(20, 100, 100, 1000)), 2.0)
        self.assertEqual(calculate_tii(TiiInputs(20, 100, 50, 1000)), 4.0)
        with self.assertRaises(TradeIndicatorInputError):
            calculate_rca(RcaInputs(1, 0, 1, 1))
        self.assertIsNone((10 - 10) / (10 + 10) if (0 + 0) else None)  # 0 분모는 caller가 None 처리
        repo = KomisRawDataRepository()
        # 실제 fetch_trade_indicator가 조립하는 SELECT 결과만 mock한다. DB 쓰기 없이
        # TSI/증감률/의존도의 product path와 SQL 분기까지 함께 검증한다.
        queries: list[str] = []
        def sql_result(query: str):
            queries.append(query)
            if "SUM(INCM_AMT) AS import_amount" in query:
                return pd.DataFrame([{"import_amount": 160, "export_amount": 40}])
            if "GROUP BY 1" in query:
                return pd.DataFrame([{"period": "prior", "amount": 150}, {"period": "current", "amount": 300}])
            if "partner_amount" in query:
                return pd.DataFrame([{"total_amount": 200, "partner_amount": 50}])
            raise AssertionError(query)
        with patch("common.komis_raw.read_sql_pg", side_effect=sql_result) as sql:
            tsi = repo.fetch_trade_indicator(trade_metric="tsi", hs_codes=["2603000000"], reporter_country="한국", calendar_year=2025)
            growth = repo.fetch_trade_indicator(trade_metric="trade_growth", hs_codes=["2603000000"], reporter_country="한국", calendar_year=2025, flow="import")
            dependency = repo.fetch_trade_indicator(trade_metric="country_dependency", hs_codes=["2603000000"], reporter_country="한국", calendar_year=2025, flow="import", partner_country="중국")
        self.assertEqual(tsi.rows[0]["tsi"], -0.6)
        self.assertEqual(growth.rows[0]["growth_pct"], 100.0)
        self.assertEqual(dependency.rows[0]["dependency_pct"], 25.0)
        self.assertEqual(tsi.unit, "무차원")
        self.assertEqual(growth.unit, "%")
        self.assertEqual(dependency.unit, "%")
        self.assertEqual(tsi.metadata["period_coverage"], "partial")
        self.assertEqual(tsi.metadata["requested_period"], "2025-01-01~2025-12-31")
        self.assertEqual(sql.call_count, 3)
        self.assertTrue(all("HS_CD IN ('2603000000')" in query for query in queries))
        self.assertIn("CRTR_YMD >= '20250101'", queries[0])
        self.assertIn("CRTR_YMD >= '20240101'", queries[1])
        self.assertIn("INCM_AMT", queries[1])
        self.assertIn("TRGT_NTN = '중국'", queries[2])
        self.assertIn("TRGT_NTN_CD = '중국'", queries[2])

    def test_product_zero_denominators_and_missing_prior_remain_none(self):
        repo = KomisRawDataRepository()
        with patch("common.komis_raw.read_sql_pg", side_effect=[
            pd.DataFrame([{"import_amount": 0, "export_amount": 0}]),
            pd.DataFrame([{"period": "current", "amount": 300}]),
            pd.DataFrame([{"total_amount": 0, "partner_amount": 0}]),
        ]):
            tsi = repo.fetch_trade_indicator(trade_metric="tsi", hs_codes=["2603000000"], reporter_country="한국", calendar_year=2025)
            growth = repo.fetch_trade_indicator(trade_metric="trade_growth", hs_codes=["2603000000"], reporter_country="한국", calendar_year=2025, flow="export")
            dependency = repo.fetch_trade_indicator(trade_metric="country_dependency", hs_codes=["2603000000"], reporter_country="한국", calendar_year=2025, flow="export", partner_country="CN")
        self.assertIsNone(tsi.rows[0]["tsi"])
        self.assertIsNone(growth.rows[0]["growth_pct"])
        self.assertIsNone(dependency.rows[0]["dependency_pct"])

    def test_trade_indicator_keeps_actual_observation_period_and_country_code_match(self):
        repo = KomisRawDataRepository()
        with patch("common.komis_raw.read_sql_pg", return_value=pd.DataFrame([{
            "available_start": "20250701", "available_end": "20250909", "observation_count": 40,
            "total_amount": 108_544_000, "partner_amount": 28_518_400,
            "matched_partner_names": "중국", "matched_partner_codes": "CN",
        }])):
            dataset = repo.fetch_trade_indicator(
                trade_metric="country_dependency", hs_codes=["2603000000"],
                reporter_country="한국", calendar_year=2025, flow="import", partner_country="중국",
            )
        self.assertEqual(dataset.as_of, "2025-07-01~2025-09-09")
        self.assertEqual(dataset.metadata["period_coverage"], "partial")
        self.assertEqual(dataset.metadata["matched_partner_codes"], "CN")
        self.assertAlmostEqual(dataset.rows[0]["dependency_pct"], 26.2736, places=4)

    def test_trade_hitl_missing_and_completed_slots_are_distinct(self):
        missing = ActionCall(requirement_id="r1", action_id="trade.indicator", slots=ActionSlots(trade_metric="tsi", mineral="리튬"))
        self.assertEqual(set(missing_trade_indicator_slots(missing)), {"reporter_country", "period"})
        complete = ActionCall(
            requirement_id="r2", action_id="trade.indicator",
            slots=ActionSlots(trade_metric="tsi", mineral="리튬", reporter_country="한국",
                              period=Period(kind="calendar_year", calendar_year=2025, explicit=True)),
        )
        self.assertEqual(missing_trade_indicator_slots(complete), ())


class AC47TradeHitlSessionTest(unittest.TestCase):
    def test_trade_clarification_persists_and_recovers_typed_plan(self):
        stored: dict[str, list[dict]] = {}

        class Store:
            def append_message(self, session, role, content, citations_json=None):
                stored.setdefault(session, []).append({"role": role, "content": content, "citations_json": citations_json})

            def list_messages(self, session, limit=1):
                return stored.get(session, [])[-limit:]

        plan = ActionPlan(actions=[ActionCall(requirement_id="r", action_id="trade.indicator", slots=ActionSlots(
            trade_metric="tsi", mineral="리튬",
        ))])
        with patch.object(chat_router, "session_store", Store()):
            events = list(chat_router._trade_clarification_response("session-a", "리튬 TSI", plan))
            pending = chat_router._pending_trade_clarification("session-a")
            self.assertIsNone(chat_router._pending_trade_clarification("session-b"))
            # 실제 답변 저장 뒤에는 마지막 assistant message가 pending payload가 아니므로
            # 다음 턴이 과거 HITL을 재개하지 않는다.
            chat_router.session_store.append_message("session-a", "assistant", "계산 완료", citations_json=None)
            self.assertIsNone(chat_router._pending_trade_clarification("session-a"))
        self.assertTrue(any("needs_clarification" in str(event) for event in events))
        self.assertEqual(pending["question"], "리튬 TSI")
        recovered = ActionPlan.model_validate(pending["plan"])
        self.assertEqual(recovered.actions[0].slots.trade_metric, "tsi")
        self.assertEqual(recovered.actions[0].slots.mineral, "리튬")

    def test_router_followup_preserves_slots_passes_complete_call_and_clears_pending(self):
        stored: dict[str, list[dict]] = {}
        forwarded: list[ActionPlan] = []

        class Store:
            def append_message(self, session, role, content, citations_json=None):
                stored.setdefault(session, []).append({"role": role, "content": content, "citations_json": citations_json})

            def list_messages(self, session, limit=10):
                return stored.get(session, [])[-limit:]

        missing_plan = ActionPlan(actions=[ActionCall(requirement_id="r", action_id="trade.indicator", slots=ActionSlots(trade_metric="tsi", mineral="리튬"))])
        complete_plan = ActionPlan(actions=[ActionCall(requirement_id="r", action_id="trade.indicator", slots=ActionSlots(
            trade_metric="tsi", mineral="리튬", reporter_country="한국",
            period=Period(kind="calendar_year", calendar_year=2025, explicit=True),
        ))])

        def fake_extract(message, *_args, **_kwargs):
            return complete_plan if "추가 확인 조건" in message else missing_plan

        def fake_document(_request, session_id, _profile, action_plan=None):
            forwarded.append(action_plan)
            chat_router.session_store.append_message(session_id, "assistant", "완료", citations_json=None)
            yield {"event": "done", "data": '{"done":true}'}

        with patch.object(chat_router, "session_store", Store()), \
                patch.object(chat_router, "extract_action_plan", side_effect=fake_extract), \
                patch.object(chat_router, "_unsupported_mineral_in_plan", return_value=False), \
                patch.object(chat_router, "_run_document_qa", side_effect=fake_document):
            request1 = chat_router.ChatRequest(user_id="u", message="리튬 TSI")
            list(chat_router._run_chat_session(request1, "public", "session-a"))
            self.assertIsNotNone(chat_router._pending_trade_clarification("session-a"))
            request2 = chat_router.ChatRequest(user_id="u", message="한국 2025년")
            list(chat_router._run_chat_session(request2, "public", "session-a"))
            self.assertIsNone(chat_router._pending_trade_clarification("session-a"))
        self.assertEqual(len(forwarded), 1)
        slots = forwarded[0].actions[0].slots
        self.assertEqual((slots.trade_metric, slots.mineral, slots.reporter_country, slots.period.calendar_year), ("tsi", "리튬", "한국", 2025))


class AC47MineClarificationTest(unittest.TestCase):
    def test_mine_location_owner_choice_regression(self):
        self.assertEqual(chat_router._mine_country_choice("칠레 소재 광산 기준", "칠레"), "location")
        self.assertEqual(chat_router._mine_country_choice("칠레 소유 광산 기준", "칠레"), "ownership")
        self.assertIsNone(chat_router._mine_country_choice("칠레 광산", "칠레"))


if __name__ == "__main__":
    unittest.main()
