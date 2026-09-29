# -*- coding: utf-8 -*-
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rag_core.ragkit.action_contract import ActionCall, ActionPlan, ActionSlots, Period
from rag_core.ragkit.action_results import ActionResult, RetrievalResult
from rag_core.ragkit.chatbot import (
    _citation_sources, _clean_korea_import_rank_answer, _country_rank_summary,
    _is_single_korea_import_rank, _resource_rank_citation_indices,
    _successful_action_citation_indices,
)
from common.komis_raw import RawDataset
from rag_core.retrieval.evidence import from_komis_ranking
from rag_core.retrieval.evidence import Evidence


class ResourceRankCitationTest(unittest.TestCase):
    def test_combined_production_and_reserves_includes_both_sources(self):
        evidence = [
            SimpleNamespace(
                source="public.KO_RSRC_PRDCTN_QUTY",
                section="희토류 생산량 상위",
                text="| 국가 | 생산량합계(톤) |\n| --- | --- |\n| 중국 | 1 |",
            ),
            SimpleNamespace(
                source="public.KO_RSRC_BURUDG_QUTY",
                section="희토류 매장량 상위",
                text="| 국가 | 매장량합계(톤) |\n| --- | --- |\n| 중국 | 2 |",
            ),
        ]
        self.assertEqual(
            _resource_rank_citation_indices(evidence, "희토류 생산량과 매장량 상위 국가를 알려줘"),
            {1, 2},
        )

    def test_single_metric_does_not_force_unrelated_sources(self):
        evidence = [SimpleNamespace(source="public.KO_RSRC_PRDCTN_QUTY", section="", text="")]
        self.assertEqual(_resource_rank_citation_indices(evidence, "희토류 생산량 상위 국가는?"), set())

    def test_composite_success_citations_do_not_depend_on_llm_inline_marks(self):
        evidence = [
            Evidence(kind="structured", source="public.KO_RSRC_PRDCTN_QUTY", section="생산량", text="x",
                     requirement_id="production", action_id="resource.rank"),
            Evidence(kind="structured", source="public.KO_RSRC_BURUDG_QUTY", section="매장량", text="y",
                     requirement_id="reserves", action_id="resource.rank"),
        ]
        result = RetrievalResult(
            action_plan=ActionPlan(actions=[ActionCall(
                requirement_id="production", action_id="resource.rank",
                slots=ActionSlots(mineral="희토류", metric="production"),
            )]), evidence=evidence,
            action_results=[
                ActionResult("production", "resource.rank", ActionSlots(metric="production"), "success"),
                ActionResult("reserves", "resource.rank", ActionSlots(metric="reserves"), "success"),
            ],
        )
        self.assertEqual(_successful_action_citation_indices(result, evidence, set()), {1, 2})

    def test_composite_citation_keeps_llm_selection_and_adds_one_missing_requirement(self):
        evidence = [
            Evidence(kind="pageindex", source="a", section="used", text="x", requirement_id="a"),
            Evidence(kind="pageindex", source="a", section="unused", text="y", requirement_id="a"),
            Evidence(kind="pageindex", source="b", section="representative", text="z", requirement_id="b"),
        ]
        result = RetrievalResult(
            action_plan=ActionPlan(actions=[ActionCall(
                requirement_id="a", action_id="document.retrieve", slots=ActionSlots(topic="a"),
            )]), evidence=evidence,
            action_results=[
                ActionResult("a", "document.retrieve", ActionSlots(topic="a"), "success"),
                ActionResult("b", "document.retrieve", ActionSlots(topic="b"), "success"),
            ],
        )
        self.assertEqual(_successful_action_citation_indices(result, evidence, {1}), {3})

    def test_single_korea_import_rank_keeps_structured_citation_without_inline_marker(self):
        evidence = [Evidence(
            kind="structured", source="public.KO_CSTM_CMMRC", section="수입 순위", text="표",
            requirement_id="imports", action_id="trade.country_rank",
        )]
        result = RetrievalResult(
            action_plan=ActionPlan(actions=[ActionCall(
                requirement_id="imports", action_id="trade.country_rank",
                slots=ActionSlots(mineral="리튬", metric="import_amount", flow="import",
                                  trade_scope="korea"),
            )]),
            evidence=evidence,
            action_results=[ActionResult(
                "imports", "trade.country_rank", ActionSlots(metric="import_amount"), "success",
            )],
        )

        self.assertEqual(_successful_action_citation_indices(result, evidence, set()), {1})

    def test_dummy_status_and_warning_are_hidden_from_source_label(self):
        dummy = Evidence(kind="structured", source="public.KO_RSRC_PRDCTN_QUTY", section="생산량", text="x",
                         caveat="이 수치는 KOMIS 실제 표본이 아니라 개발용 더미(예시) 데이터입니다.")
        citation = _citation_sources({1}, [dummy])[0]
        self.assertNotIn("DEV_DUMMY", citation["source"])
        self.assertIsNone(citation["data_status"])
        self.assertEqual(citation["warnings"], [])

    def test_resource_rank_does_not_receive_trade_rank_summary(self):
        plan = ActionPlan(actions=[ActionCall(
            requirement_id="production", action_id="resource.rank",
            slots=ActionSlots(mineral="희토류", metric="production"),
        )])
        evidence = [Evidence(
            kind="structured", source="public.KO_RSRC_PRDCTN_QUTY", section="생산량", text=(
                "| country | share_pct |\n| --- | --- |\n| 중국 | 36.36 |"
            ), requirement_id="production", action_id="resource.rank",
        )]
        self.assertEqual(_country_rank_summary(evidence, plan, "희토류 생산량 상위 국가"), "")

    def test_resource_rank_evidence_explains_world_total_denominator(self):
        evidence = from_komis_ranking(RawDataset(
            source_table="KO_RSRC_PRDCTN_QUTY", columns=["rank", "country", "share_pct"],
            column_labels={"rank": "순위", "country": "국가", "share_pct": "비중(%)"},
            row_count=1, rows=[{"rank": 1, "country": "중국", "share_pct": 60.5}],
            unit="톤", metadata={"grand_total": 1000, "share_denominator": "world_total_su"},
        ), metric_label="생산량")
        self.assertIn("분모는 공식 세계 합계 1000 톤입니다", evidence[0].text)
        self.assertNotIn("같은 기간·조건의 전체 국가 합계", evidence[0].text)

    def test_trade_summary_uses_matching_requirement_and_observed_range(self):
        plan = ActionPlan(actions=[ActionCall(
            requirement_id="lithium_imports", action_id="trade.country_rank",
            slots=ActionSlots(mineral="리튬", period=Period(kind="trailing_months", trailing_months=12)),
        )])
        evidence = [
            Evidence(kind="structured", source="KOMIS", section="생산 순위",
                     text="| country | share_pct |\n|---|---|\n| 중국 | 99 |",
                     requirement_id="production", action_id="resource.rank"),
            Evidence(kind="structured", source="KOMIS", section="수입 순위",
                     text="| country | share_pct |\n|---|---|\n| 호주 | 37.6 |",
                     requirement_id="lithium_imports", action_id="trade.country_rank",
                     observed_period="2026-06-01~2026-09-09"),
        ]
        summary = _country_rank_summary(evidence, plan, "리튬 수입 상위국 알려줘")
        self.assertIn("집계 기간 2026-06-01~2026-09-09", summary)
        self.assertIn("한국 리튬 수입금액(USD) 기준 상위 1개국은 1위 호주(37.6%)", summary)
        self.assertIn("조회 대상 리튬 HS 품목의 한국 수입금액(USD) 합계", summary)
        self.assertNotIn("[1]", summary)
        self.assertNotIn("중국", summary)
        self.assertNotIn("최근 1년", summary)

    def test_korea_import_rank_hides_visible_not_structured_citations(self):
        korea_plan = ActionPlan(actions=[ActionCall(
            requirement_id="imports", action_id="trade.country_rank",
            slots=ActionSlots(mineral="리튬", metric="import_amount", flow="import",
                              trade_scope="korea"),
        )])
        global_plan = ActionPlan(actions=[ActionCall(
            requirement_id="imports", action_id="trade.country_rank",
            slots=ActionSlots(mineral="리튬", metric="import_amount", flow="import",
                              trade_scope="global"),
        )])
        self.assertTrue(_is_single_korea_import_rank(korea_plan))
        self.assertFalse(_is_single_korea_import_rank(global_plan))
        cleaned = _clean_korea_import_rank_answer(
            "호주 37.6% [1] ⚠ 이 수치는 KOMIS 실제 표본이 아니라 개발용 더미(예시) 데이터입니다. "
            "출처: [1] KOMIS 공식 데이터 · KO_CSTM_CMMRC"
        )
        self.assertEqual(cleaned, "호주 37.6%")


if __name__ == "__main__":
    unittest.main()
