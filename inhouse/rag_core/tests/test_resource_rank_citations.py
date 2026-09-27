# -*- coding: utf-8 -*-
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rag_core.ragkit.action_contract import ActionCall, ActionPlan, ActionSlots
from rag_core.ragkit.action_results import ActionResult, RetrievalResult
from rag_core.ragkit.chatbot import _citation_sources, _resource_rank_citation_indices, _successful_action_citation_indices
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

    def test_dummy_status_and_warning_are_separate_from_source_label(self):
        dummy = Evidence(kind="structured", source="public.KO_RSRC_PRDCTN_QUTY", section="생산량", text="x",
                         caveat="이 수치는 KOMIS 실제 표본이 아니라 개발용 더미(예시) 데이터입니다.")
        citation = _citation_sources({1}, [dummy])[0]
        self.assertNotIn("DEV_DUMMY", citation["source"])
        self.assertEqual(citation["data_status"], "DEV_DUMMY")
        self.assertEqual(citation["warnings"], [dummy.caveat])


if __name__ == "__main__":
    unittest.main()
