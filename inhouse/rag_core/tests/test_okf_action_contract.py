# -*- coding: utf-8 -*-
"""명시 OKF/단건 광산 action의 closed contract와 MCP 경계를 검사한다."""
import sys
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rag_core.ragkit.action_contract import (
    ActionCall, ActionPlan, ActionSlots, IntentCall, IntentPlan,
    action_plan_from_intent, validate_action_plan,
)
from rag_core.ragkit import chatbot_graph as graph
from rag_core.ragkit.mcp_client import _ProfileSession
from rag_core.retrieval.evidence import Evidence
from rag_core.retrieval import pageindex
from rag_core.retrieval.access import PRIVATE_ONLY_SOURCE_GROUPS


class OkfActionContractTest(unittest.TestCase):
    def test_document_lookup_preserves_original_query_and_restricts_document(self):
        call = ActionCall(requirement_id="doc", action_id="document.lookup", slots=ActionSlots(
            topic="Kazatomprom 우라늄 광산 정리자료 JV Inkai"))
        self.assertTrue(validate_action_plan(ActionPlan(actions=[call])).approved)
        route = graph._route_from_action_call(
            call, "Kazatomprom 우라늄 광산 정리자료의 JV Inkai 위치는?",
        )
        self.assertEqual(route.resolved_query, "Kazatomprom 우라늄 광산 정리자료의 JV Inkai 위치는?")
        self.assertEqual(route.pageindex_doc, call.slots.topic)
        self.assertTrue(route.use_pageindex)
        self.assertFalse(route.use_dense)

    def test_mine_profile_is_not_mine_rank_and_uses_both_document_tools(self):
        call = ActionCall(requirement_id="mine", action_id="mine.profile", slots=ActionSlots(
            mine_name="Escondida", topic="BHP 보고서"))
        self.assertTrue(validate_action_plan(ActionPlan(actions=[call])).approved)
        route = graph._route_from_action_call(call, "BHP 보고서에서 Escondida 광산은 어느 나라에 있나?")
        self.assertTrue(route.use_dense)
        self.assertTrue(route.use_pageindex)
        self.assertEqual(route.resolved_query, "Escondida BHP 보고서")
        self.assertEqual(route.pageindex_doc, "BHP 보고서")
        self.assertTrue(route.pageindex_body_fallback)
        self.assertEqual(route.pageindex_body_query, "Escondida")
        self.assertFalse(route.use_mine_aggregate)

    def test_mine_profile_uses_original_document_descriptor_when_topic_is_missing(self):
        question = "Kazatomprom 우라늄 광산 정리자료의 JV Inkai 위치는?"
        call = ActionCall(requirement_id="mine", action_id="mine.profile", slots=ActionSlots(mine_name="JV Inkai"))
        route = graph._route_from_action_call(call, question)
        self.assertEqual(route.pageindex_doc, question)
        result = pageindex.lookup(
            route.resolved_query, doc=route.pageindex_doc, node_limit=3, with_text=True,
            body_fallback=route.pageindex_body_fallback, body_query=route.pageindex_body_query,
        )
        self.assertTrue(result["nodes"])
        self.assertIn("JV Inkai LLP", result["nodes"][0]["text"])

    def test_explicit_document_lookup_absorbs_same_mine_profile(self):
        intents = IntentPlan(requirements=[
            IntentCall(requirement_id="profile", intent="mine_profile", role="data",
                             slots=ActionSlots(mine_name="Escondida", topic="BHP 보고서")),
            IntentCall(requirement_id="original", intent="okf_lookup", role="content",
                             slots=ActionSlots(mine_name="Escondida", topic="BHP 보고서")),
        ])
        plan = action_plan_from_intent(intents)
        self.assertEqual([action.action_id for action in plan.actions], ["document.lookup"])
        self.assertTrue(validate_action_plan(plan).approved)

    def test_explicit_mine_document_absorbs_mine_scoped_trade_monthly(self):
        intents = IntentPlan(requirements=[
            IntentCall(requirement_id="document", intent="okf_lookup", role="content", slots=ActionSlots(
                mineral="우라늄", mine_name="JV Inkai", topic="Kazatomprom 우라늄 광산 정리자료")),
            IntentCall(requirement_id="trade", intent="trade_monthly", role="data", slots=ActionSlots(
                mineral="우라늄", mine_name="JV Inkai", flow="import",
                period={"kind": "future_horizon", "future_horizon": 1, "explicit": True})),
        ])
        plan = action_plan_from_intent(intents)
        self.assertEqual([action.action_id for action in plan.actions], ["document.lookup"])
        self.assertTrue(validate_action_plan(plan).approved)

    def test_rank_result_name_does_not_create_nameless_mine_profile(self):
        intents = IntentPlan(requirements=[
            IntentCall(requirement_id="rank", intent="mine_rank", role="data", slots=ActionSlots(
                country_scope="중국", mine_metric="production", mine_order="level")),
            IntentCall(requirement_id="name", intent="mine_profile", role="content", slots=ActionSlots(
                country_scope="중국")),
        ])
        plan = action_plan_from_intent(intents)
        self.assertEqual([action.action_id for action in plan.actions], ["mine.rank"])
        self.assertTrue(validate_action_plan(plan).approved)

    def test_mcp_pageindex_doc_argument_is_forwarded(self):
        session = object.__new__(_ProfileSession)
        with patch.object(_ProfileSession, "_call", return_value={"nodes": []}) as call:
            self.assertEqual(_ProfileSession.call_pageindex_lookup(
                session, "JV Inkai 위치", doc="Kazatomprom", node_limit=3,
            ), [])
        self.assertEqual(call.call_args.args[0], "pageindex_lookup")
        self.assertEqual(call.call_args.args[1]["doc"], "Kazatomprom")

    def test_single_public_candidate_allows_mine_profile_body_fallback(self):
        result = pageindex.lookup(
            "JV Inkai Kazatomprom 우라늄 광산 정리자료", doc="Kazatomprom 우라늄 광산 정리자료", node_limit=3, with_text=True,
            body_fallback=True, body_query="JV Inkai",
        )
        self.assertEqual(len(result["documents"]), 1)
        self.assertEqual(len(result["nodes"]), 1)
        self.assertIn("JV Inkai LLP", result["nodes"][0]["text"])

    def test_explicit_document_body_fallback_returns_matched_okf_row(self):
        result = pageindex.lookup(
            "JV Inkai 위치", doc="Kazatomprom 우라늄 광산 정리자료",
            node_limit=3, with_text=True, body_fallback=True,
        )
        self.assertEqual(len(result["nodes"]), 1)
        text = result["nodes"][0]["text"]
        self.assertIn("JV Inkai LLP", text)
        self.assertIn("45.281", text)
        self.assertIn("67.536", text)

    def test_explicit_document_fallback_keeps_public_source_group_filter(self):
        result = pageindex.lookup(
            "copper price", doc="Argus_비철금속_일일/Argus_Non-Ferrous_Markets_2025-10-29.md",
            node_limit=5, with_text=True, body_fallback=True,
            exclude_source_groups=PRIVATE_ONLY_SOURCE_GROUPS,
        )
        self.assertEqual(result["documents"], [])
        self.assertEqual(result["nodes"], [])

    def test_candidate_without_pageindex_body_is_source_unavailable(self):
        action = ActionCall(requirement_id="mine", action_id="mine.profile", slots=ActionSlots(mine_name="Unknown"))
        dense_only = [Evidence(kind="dense", source="candidate.md", section="제목", text="후보 제목")]
        self.assertFalse(any(ev.kind == "pageindex" and ev.text.strip() for ev in dense_only))
        self.assertTrue(validate_action_plan(ActionPlan(actions=[action])).approved)

    def test_mine_profile_rejects_other_mine_pageindex_body(self):
        other = [Evidence(kind="pageindex", source="U_Cigar Lake", section="본문", text="Cigar Lake 운영사")]
        matching = [Evidence(kind="pageindex", source="Kazatomprom", section="본문", text="JV Inkai LLP | 45.281 | 67.536")]
        self.assertFalse(graph._okf_body_matches_profile(other, "JV Inkai"))
        self.assertTrue(graph._okf_body_matches_profile(matching, "JV Inkai"))
        mixed = matching + [Evidence(kind="dense", source="U_Cigar Lake", section="다른 문서", text="운영사")]
        verified_sources = [ev.source for ev in mixed if ev.kind == "pageindex" and ev.text.strip()]
        self.assertEqual(verified_sources, ["Kazatomprom"])

    def test_all_dummy_trade_concentration_is_not_an_observed_hhi(self):
        action = ActionCall(requirement_id="hhi", action_id="trade.concentration", slots=ActionSlots(mineral="니켈"))
        dummy = [Evidence(kind="aggregated", source="public.KO_CSTM_CMMRC", section="HHI", text="HHI=2327.98",
                          caveat="개발용 더미")]
        real = [Evidence(kind="aggregated", source="public.KO_CSTM_CMMRC", section="HHI", text="HHI=2327.98")]
        self.assertTrue(validate_action_plan(ActionPlan(actions=[action])).approved)
        self.assertTrue(all("개발용 더미" in (ev.caveat or "") for ev in dummy))
        self.assertFalse(all("개발용 더미" in (ev.caveat or "") for ev in real))

    def test_table_distinct_mine_count_only_marks_company_level_lookup_ambiguous(self):
        cases = (
            ("Kazatomprom", None, "Kazatomprom", 17),
            ("JV Inkai", "Kazatomprom 우라늄 광산 정리자료", "JV Inkai", 1),
            ("Escondida", "BHP 보고서", "Escondida", 1),
        )
        for query, doc, body_query, expected_count in cases:
            with self.subTest(query=query):
                result = pageindex.lookup(
                    query, doc=doc, node_limit=3, with_text=True,
                    body_fallback=True, body_query=body_query,
                )
                self.assertTrue(result["nodes"])
                matched = re.search(r"동일 식별자 행 (\d+)개", result["nodes"][0]["node_path"])
                self.assertIsNotNone(matched)
                self.assertEqual(int(matched.group(1)), expected_count)

    def test_table_location_explanation_does_not_append_non_numeric_next_column(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "sample.md").write_text(
                "| 광산 | 위치 | 운영사 |\n| --- | --- | --- |\n| Example Mine | Chile | BHP |\n",
                encoding="utf-8",
            )
            hit = pageindex._document_body_fallback(
                "Example Mine", {"okf_path": "sample.md", "title": "Example mines"}, okf_root=root,
            )
        self.assertIsNotNone(hit)
        self.assertIn("Example Mine의 위치 열 값은 Chile으로 기재되어 있다.", hit["text"])
        self.assertNotIn("위치 열 값은 Chile, BHP", hit["text"])

    def test_unbounded_price_compare_mixed_with_document_is_source_unavailable(self):
        document = ActionCall(
            requirement_id="mechanism", action_id="document.retrieve", role="content",
            slots=ActionSlots(topic="수요 변화가 광종에 미치는 영향의 메커니즘"),
        )
        unbounded_compare = ActionCall(
            requirement_id="data", action_id="price.compare", role="data",
            slots=ActionSlots(minerals=["리튬", "니켈", "코발트"]),
        )
        self.assertEqual(
            validate_action_plan(ActionPlan(actions=[document, unbounded_compare])).failure_reason,
            "source_unavailable",
        )
        bounded_compare = ActionCall(
            requirement_id="data", action_id="price.compare", role="data",
            slots=ActionSlots(minerals=["리튬", "니켈", "코발트"], windows=[3, 6, 12]),
        )
        self.assertEqual(
            validate_action_plan(ActionPlan(actions=[document, bounded_compare])).failure_reason,
            "unsupported_combination",
        )

    def test_complete_explicit_hs_summary_bypasses_transient_advisor_output(self):
        action = ActionCall(
            requirement_id="hs", action_id="trade.hs_summary",
            slots=ActionSlots(hs_code="2603000000"),
        )
        common = dict(kind="structured", source="public.KO_CSTM_CMMRC",
                      source_id="public.KO_CSTM_CMMRC", requirement_id="hs",
                      action_id="trade.hs_summary", observed_period="2014-01-01~2026-07-01")
        evidence = [
            Evidence(**common, section="HS 2603000000 수입금액 현황", unit="USD",
                     text="| month | import_amount |\n| --- | --- |\n| 2026-07 | 1 |"),
            Evidence(**common, section="HS 2603000000 수입중량 현황", unit="kg",
                     text="| month | import_weight |\n| --- | --- |\n| 2026-07 | 1 |"),
        ]
        class UnexpectedAdvisor:
            def invoke(self, **kwargs):
                raise AssertionError("완전한 명시 HS 집계에는 Advisor를 호출하면 안 됨")
        result = graph._verify_node({
            "evidence": evidence, "warnings": [], "action_call": action,
            "route": graph.RetrievalRoute(resolved_query="HS 현황", use_structured=False,
                                             use_dense=False, use_pageindex=False),
            "history": [],
        }, UnexpectedAdvisor())
        self.assertTrue(result["sufficient"])
        self.assertEqual(result["evidence"], evidence)
