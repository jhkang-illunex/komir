import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


RUNNER = Path(__file__).with_name("run_acceptance_suite.py")
SPEC = importlib.util.spec_from_file_location("acceptance_runner", RUNNER)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class AcceptanceSuiteDefinitionTest(unittest.TestCase):
    def test_case_definition_has_48_unique_cases_and_supported_layers(self):
        _, cases = runner.load_cases(Path(__file__).with_name("chatbot_acceptance_cases.yml"))
        self.assertEqual(len(cases), 48)
        self.assertEqual(len({case["id"] for case in cases}), 48)
        self.assertEqual({"live", "module", "integration"}, {case["layer"] for case in cases})

    def test_integration_fixture_contract_has_required_document_samples(self):
        from rag_chat.tests.acceptance_integrations import fixture
        for case_id in ("AC28", "AC29", "AC30"):
            sample = fixture(case_id)
            self.assertTrue(sample.get("resource"))
            self.assertTrue(sample.get("query"))
            self.assertTrue(sample.get("okf_fact"))

    def test_sse_parser_keeps_only_data_events(self):
        events = runner.parse_sse(b"event: delta\ndata: {\"delta\": \"ok\"}\n\nevent: done\ndata: {\"done\": true}\n")
        self.assertEqual(events, [{"delta": "ok"}, {"done": True}])

    def test_sse_parser_rejects_malformed_and_non_object_payload(self):
        with self.assertRaises(ValueError):
            runner.parse_sse(b"data: {broken}\n")
        with self.assertRaises(ValueError):
            runner.parse_sse(b"data: []\n")

    def test_terminal_contract_rejects_done_followed_by_another_event(self):
        errors = runner.terminal_errors(
            [{"session_id": "s1"}, {"done": True}, {"delta": "late"}], "s1",
        )
        self.assertIn("done 뒤에 추가 SSE 결과가 있음", errors)

    def test_explicit_case_overrides_default_layer(self):
        _, cases = runner.load_cases(Path(__file__).with_name("chatbot_acceptance_cases.yml"))
        selected = runner.select_cases(cases, {"AC21"}, {"module", "integration"})
        self.assertEqual([case["id"] for case in selected], ["AC21"])

    def test_module_required_checks_are_mapped_to_executable_targets(self):
        _, cases = runner.load_cases(Path(__file__).with_name("chatbot_acceptance_cases.yml"))
        ac42 = next(case for case in cases if case["id"] == "AC42")
        self.assertIn("AC42", runner.REQUIRED_CHECKS_BY_CASE)
        self.assertTrue(runner.REQUIRED_CHECKS_BY_CASE["AC42"])

    def test_ac22_without_independent_calculation_cannot_pass(self):
        _, cases = runner.load_cases(Path(__file__).with_name("chatbot_acceptance_cases.yml"))
        ac22 = next(case for case in cases if case["id"] == "AC22")
        first = [
            {"session_id": "same-session"},
            {"delta": "국가와 기간이 필요합니다."},
            {"done": True, "needs_clarification": True,
             "clarification": {"action_id": "trade.indicator", "slots": ["reporter_country", "period"]}},
        ]
        second = [
            {"session_id": "same-session"},
            {"delta": "TSI는 0.2입니다."},
            {"done": True, "citations": [{"source": "public.KO_CSTM_CMMRC", "action_id": "trade.indicator"}]},
        ]
        with patch.object(runner.uuid, "uuid4", return_value="same-session"), \
                patch.object(runner, "ask_live", side_effect=[first, second]) as ask:
            status, errors, detail = runner.verify_live(ac22, "http://test", 1)
        self.assertEqual(status, "FAIL")
        self.assertIn("AC22 슬롯 보존·변경 거절 및 독립 계산 정답 대조 미구현", errors)
        self.assertEqual(ask.call_args_list[0].args[2], "same-session")
        self.assertEqual(ask.call_args_list[1].args[2], "same-session")
        self.assertIn("followup_done", detail)

    def test_terminal_failure_wins_over_source_unavailable(self):
        case = {"question": "q", "expected_outcome": "answer", "expected_actions": [], "expected_sources": []}
        events = [
            {"session_id": "s"}, {"delta": "설명"},
            {"done": True, "abstained": True, "abstain_reason": "source_unavailable"},
            {"delta": "done 뒤 이벤트"},
        ]
        with patch.object(runner.uuid, "uuid4", return_value="s"), \
                patch.object(runner, "ask_live", return_value=events):
            status, errors, _ = runner.verify_live(case, "http://test", 1)
        self.assertEqual(status, "FAIL")
        self.assertIn("done 뒤에 추가 SSE 결과가 있음", errors)

    def test_abstention_requires_explanation_and_message_key(self):
        case = {
            "question": "q", "expected_outcome": "abstain", "expected_actions": [], "expected_sources": [],
            "expected_abstain_reasons": ["unsupported_commodity"], "expected_message_key": "unsupported_commodity",
        }
        events = [{"session_id": "s"}, {"done": True, "abstained": True,
                   "abstain_reason": "unsupported_commodity"}]
        with patch.object(runner.uuid, "uuid4", return_value="s"), \
                patch.object(runner, "ask_live", return_value=events):
            status, errors, _ = runner.verify_live(case, "http://test", 1)
        self.assertEqual(status, "FAIL")
        self.assertIn("기권 설명 본문이 비어 있음", errors)
        self.assertTrue(any("메시지 키 불일치" in error for error in errors))

    def test_public_menu_login_required_is_rejected(self):
        case = {
            "question": "q", "expected_outcome": "answer", "expected_actions": ["menu.navigate"], "expected_sources": [],
            "expected_page_id": "map_korea", "sse_contracts": ["terminal", "page"],
        }
        events = [{"session_id": "s"}, {"delta": "메뉴 안내"}, {"done": True, "mode": "page",
                   "recommendations": [{"page_id": "map_korea", "login_required": True}]}]
        with patch.object(runner.uuid, "uuid4", return_value="s"), \
                patch.object(runner, "ask_live", return_value=events):
            status, errors, _ = runner.verify_live(case, "http://test", 1)
        self.assertEqual(status, "FAIL")
        self.assertIn("public 메뉴 응답에 login_required 페이지가 포함됨", errors)

    def test_normal_answer_cannot_pass_as_page_mode(self):
        _, cases = runner.load_cases(Path(__file__).with_name("chatbot_acceptance_cases.yml"))
        ac01 = next(case for case in cases if case["id"] == "AC01")
        events = [{"session_id": "s"}, {"delta": "가격 답변"}, {
            "done": True, "mode": "page", "recommendations": [],
            "citations": [{"source": "public.KO_MNRL_PRC", "action_id": "price.series"}],
        }]
        with patch.object(runner.uuid, "uuid4", return_value="s"), \
                patch.object(runner, "ask_live", return_value=events):
            status, errors, _ = runner.verify_live(ac01, "http://test", 1)
        self.assertEqual(status, "FAIL")
        self.assertIn("일반 답변이 page mode로 반환됨", errors)

    def test_page_case_rejects_login_required_on_any_recommendation(self):
        case = {
            "question": "q", "expected_outcome": "answer", "expected_actions": ["menu.navigate"],
            "expected_sources": [], "expected_page_id": "map_korea", "sse_contracts": ["terminal", "page"],
        }
        events = [{"session_id": "s"}, {"delta": "메뉴 안내"}, {"done": True, "mode": "page",
                   "recommendations": [
                       {"page_id": "map_korea", "login_required": False},
                       {"page_id": "private_indicator", "login_required": True},
                   ]}]
        with patch.object(runner.uuid, "uuid4", return_value="s"), \
                patch.object(runner, "ask_live", return_value=events):
            status, errors, _ = runner.verify_live(case, "http://test", 1)
        self.assertEqual(status, "FAIL")
        self.assertIn("public 메뉴 응답에 login_required 페이지가 포함됨", errors)


if __name__ == "__main__":
    unittest.main()

class AcceptanceIntegrationFixtureTest(unittest.TestCase):
    def test_fixed_fixtures_pin_full_indexer_identity_and_raw_format_facts(self):
        from rag_chat.tests.acceptance_integrations import fixture
        for case_id in ("AC29", "AC30", "AC39", "AC40"):
            sample = fixture(case_id)
            self.assertTrue(sample.get("resource"))
            self.assertTrue(sample.get("doc_id"))
            self.assertTrue(sample.get("okf_path"))
        self.assertEqual(fixture("AC30")["sheet"], "산출결과")
        self.assertEqual(len(fixture("AC30")["values"]), 2)
        self.assertEqual(len(fixture("AC29")["original_facts"]), 2)
        for document in fixture("AC41")["documents"]:
            self.assertTrue(document["resource"])
            self.assertTrue(document["doc_id"])
            self.assertTrue(document["body_sha256"])
            self.assertLessEqual(document["line_start"], document["line_end"])

    def test_dense_fixture_rejects_prefix_doc_or_source_path_guessing_and_disables_fallback(self):
        from types import SimpleNamespace
        from tempfile import TemporaryDirectory
        from rag_chat.tests import acceptance_integrations as integration
        with TemporaryDirectory() as directory:
            root = Path(directory)
            okf = root / "생산매장량_USGS" / "USGS_2026.md"
            okf.parent.mkdir()
            okf.write_text(integration.fixture("AC39")["okf_fact"], encoding="utf-8")
            spec = integration.fixture("AC39")
            tree = {"doc_id": spec["doc_id"], "resource": spec["resource"], "okf_path": spec["okf_path"]}
            hit = SimpleNamespace(doc_id=spec["doc_id"][:12], source_path=spec["resource"], text=spec["okf_fact"])
            with patch("rag_core.retrieval.dense_pg.dense_search_pg", return_value=[hit]) as dense:
                status, _, _ = integration.verify_dense_fixture("AC39", tree=tree, okf_root=root)
        self.assertEqual(status, "FAIL")
        self.assertFalse(dense.call_args.kwargs["_allow_fallback"])
