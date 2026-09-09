"""출력 계약, LLM 폴백, 프롬프트 새로고침의 오프라인 회귀 검사.

python3 -m unittest discover -s inhouse/report_gen/tests -v
"""
from pathlib import Path
import sys
import logging
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Semaphore
from types import SimpleNamespace
from copy import deepcopy
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.analysis import prompt_store, prompts
from app.analysis.additional_summary import EvidenceClaim
from app.analysis.errors import DataSourceError
from app.analysis.models import AnalysisSummaryRequest, SummaryNarrative
from app.analysis.report_render import render_markdown_report
from app.analysis.summary import AnalysisSummaryService
from app.routers import _common


ROUTES = {
    "indicators/market": "indicator_market",
    "indicators/supply": "indicator_supply",
    "indicators/composite-index": "indicator_composite",
    "maps/mineral": "map_mineral",
    "prices/base-metals": "price_base_metals",
    "prices/minor-metals": "price_minor_metals",
    "prices/iron-energy": "price_iron_energy",
    "prices/other": "price_other",
    "maps/domestic-trade": "map_korea",
    "maps/global-trade": "map_global",
}


def price_request():
    return AnalysisSummaryRequest(
        page_id="price_base_metals", mineral="CU", mineral_name="동",
        observations=[
            {"date": "2026-08-01", "commerce_price": 100},
            {"date": "2026-08-02", "commerce_price": 110},
        ], price_unit="달러/톤",
    )


def claims_and_narrative():
    claims = [EvidenceClaim("current_state", "core_diagnosis", "가격은 110입니다."),
              EvidenceClaim("change", "major_changes", "10% 상승했습니다."),
              EvidenceClaim("position", "current_position", "최저가는 100입니다.")]
    narrative = SummaryNarrative(**{
        claim.section: [{"text": claim.fact, "evidence_ids": [claim.id]}] for claim in claims
    })
    return claims, narrative


class ReportContractTests(unittest.TestCase):
    def setUp(self):
        previous_level = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, previous_level)
        self.cache_patch = patch.object(prompt_store, "_cache", {})
        self.cache_patch.start()
        self.addCleanup(self.cache_patch.stop)
        self.response = AnalysisSummaryService().analyze(price_request())

    def test_ten_routes_preserve_http_and_markdown(self):
        service = Mock(uses_llm=False)
        service.analyze.return_value = self.response
        with patch.object(app.state, "analysis_summary_service", service, create=True), \
             patch.object(app.state, "analysis_lock", Semaphore(8), create=True):
            client = TestClient(app)
            for route, page in ROUTES.items():
                payload = {} if page == "indicator_composite" else {"mineral": "CU"}
                if page == "map_mineral":
                    payload["measure"] = "reserves"
                with self.subTest(page=page):
                    result = client.post("/api/v1/analysis/" + route, json=payload)
                    self.assertEqual(result.status_code, 200)
                    self.assertEqual(result.json(), {"status": "ok", "report": render_markdown_report(self.response)})
                    self.assertEqual(service.analyze.call_args.args[0].page_id, page)
                    invalid = client.post("/api/v1/analysis/" + route, json={"unknown": True})
                    self.assertEqual(invalid.status_code, 200)
                    self.assertEqual(invalid.json(), {"status": "NO_DATA", "report": None})

    def test_error_status_contract(self):
        service = Mock(uses_llm=False)
        with patch.object(app.state, "analysis_summary_service", service, create=True), \
             patch.object(app.state, "analysis_lock", Semaphore(8), create=True):
            client = TestClient(app)
            for error, status in [(DataSourceError("empty"), "NO_DATA"),
                                  (RuntimeError("broken"), "INTERNAL_ERROR"),
                                  (_common.FutureTimeoutError(), "TIMEOUT")]:
                service.analyze.side_effect = error
                result = client.post("/api/v1/analysis/prices/base-metals", json={"mineral": "CU"})
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json(), {"status": status, "report": None})

    def test_llm_success_keeps_render_format(self):
        claims, narrative = claims_and_narrative()
        llm = Mock()
        llm.invoke.return_value = SimpleNamespace(output=narrative)
        result = AnalysisSummaryService(llm=llm)._refine_with_llm(self.response, claims)
        self.assertTrue(result.llm_refined)
        self.assertEqual(result.summary, narrative)
        rendered = render_markdown_report(result)
        self.assertIn("## 가격 요약\n", rendered)
        self.assertIn("## 최근 변화\n", rendered)
        self.assertIn("## 변동 구간\n", rendered)
        self.assertNotIn("## 주요 지표", rendered)
        self.assertEqual(llm.invoke.call_count, 1)

    def test_llm_invalid_output_retries_then_preserves_fallback(self):
        claims, narrative = claims_and_narrative()
        narrative.core_diagnosis[0].evidence_ids = ["nonexistent"]
        llm = Mock()
        llm.invoke.return_value = SimpleNamespace(output=narrative)
        result = AnalysisSummaryService(llm=llm)._refine_with_llm(self.response, claims)
        self.assertEqual(llm.invoke.call_count, 2)
        self.assertFalse(result.llm_refined)
        self.assertEqual(render_markdown_report(result), render_markdown_report(self.response))
        self.assertIn("previous_validation_error", llm.invoke.call_args.kwargs["payload"])

    def test_llm_causal_factor_wording_is_rejected_and_retried(self):
        claims, valid = claims_and_narrative()
        invalid = deepcopy(valid)
        invalid.core_diagnosis[0].text = "가격은 110이며 변동함에 따라 확인됩니다."
        llm = Mock()
        llm.invoke.side_effect = [SimpleNamespace(output=invalid), SimpleNamespace(output=valid)]
        result = AnalysisSummaryService(llm=llm)._refine_with_llm(self.response, claims)
        self.assertEqual(llm.invoke.call_count, 2)
        self.assertTrue(result.llm_refined)

    def test_indicator_directive_wording_and_sections(self):
        service = AnalysisSummaryService()
        common = {
            "mineral": "GA",
            "mineral_name": "갈륨",
            "observations": [
                {"month": "2026-06", "score": 34.04, "price": 100},
                {"month": "2026-07", "score": 30.38, "price": 104.42},
            ],
        }
        market = render_markdown_report(service.analyze(AnalysisSummaryRequest(
            page_id="indicator_market", **common,
        )))
        self.assertIn("3.66점 하락", market)
        self.assertNotIn("10.75% 하락", market)
        self.assertIn("## 주요 변동 특징\n", market)

        supply = render_markdown_report(service.analyze(AnalysisSummaryRequest(
            page_id="indicator_supply", **common,
            supply_auxiliary={
                "domestic_imports": [
                    {"year": 2025, "import_weight_ton": 100, "import_amount_million_usd": 10},
                    {"year": 2026, "import_weight_ton": 80, "import_amount_million_usd": 9},
                ]
            },
        )))
        self.assertIn("3.66점 하락", supply)
        self.assertIn("## 구성요소 변화\n", supply)
        self.assertIn("국내 수입량", supply.split("## 구성요소 변화\n", 1)[1])

    def test_composite_body_includes_current_subindex_values(self):
        response = AnalysisSummaryService().analyze(AnalysisSummaryRequest(
            page_id="indicator_composite",
            observations=[
                {"date": "2026-07-01", "composite_index": 1000,
                 "major_metals_index": 900, "minor_metals_index": 800},
                {"date": "2026-07-08", "composite_index": 1010,
                 "major_metals_index": 920, "minor_metals_index": 790},
            ],
        ))
        report = render_markdown_report(response)
        self.assertIn("현재 메이저금속지수는 920.00포인트", report)
        self.assertIn("희소금속지수는 790.00포인트", report)

    def test_llm_failure_preserves_fallback(self):
        llm = Mock()
        llm.invoke.side_effect = OSError("offline")
        result = AnalysisSummaryService(llm=llm)._refine_with_llm(self.response, claims_and_narrative()[0])
        self.assertEqual(render_markdown_report(result), render_markdown_report(self.response))
        self.assertFalse(result.llm_refined)

    def test_deadline_skips_llm(self):
        llm = Mock()
        result = AnalysisSummaryService(llm=llm).analyze(price_request(), deadline=time.monotonic())
        llm.invoke.assert_not_called()
        self.assertEqual(render_markdown_report(result), render_markdown_report(self.response))

    def test_request_scope_survives_reload_and_restores_after_exception(self):
        page = "price_base_metals"
        old = prompt_store.PromptRow(page, "old instructions", page_name="old name")
        new = prompt_store.PromptRow(page, "new instructions", page_name="new name")
        prompt_store._cache = {page: old}
        with self.assertRaisesRegex(ValueError, "stop"):
            with prompts.page_prompt_scope(page):
                cfg = prompts.resolve_page_config(page)
                instructions = prompts.summary_instructions(page)
                with patch.object(prompt_store, "ensure_schema"), patch.object(prompt_store, "_fetch_all", return_value={page: new}):
                    self.assertTrue(prompt_store.reload().ok)
                self.assertIs(prompts.resolve_page_config(page), cfg)
                self.assertEqual(prompts.summary_instructions(page), instructions)
                raise ValueError("stop")
        self.assertEqual(prompts.resolve_page_config(page).name, "new name")
        self.assertTrue(prompts.summary_instructions(page).endswith("new instructions"))

    def test_concurrent_page_scopes_are_isolated(self):
        def read(page):
            with prompts.page_prompt_scope(page):
                return prompts.resolve_page_config(page).page_id, prompts.summary_instructions(page)
        pages = list(ROUTES.values())
        with ThreadPoolExecutor(max_workers=8) as pool:
            for page, (actual, text) in zip(pages, pool.map(read, pages)):
                self.assertEqual(page, actual)
                self.assertEqual(text, prompts.summary_instructions(page))

    def test_invalid_db_contract_uses_code_defaults(self):
        page = "price_base_metals"
        baseline = prompts.code_page_config(page)
        prompt_store._cache = {page: prompt_store.PromptRow(
            page, "custom", page_name="  ", analysis_constraints="bad",
            output_contract={"section_sentence_ranges": {"core_diagnosis": [1, 999]},
                             "max_evidence_ids_per_sentence": 999},
        )}
        self.assertEqual(prompts.resolve_page_config(page), baseline)

    def test_reload_failure_retains_current_settings(self):
        before = prompts.summary_instructions("price_base_metals")
        with patch.object(prompt_store, "ensure_schema", side_effect=RuntimeError("offline")):
            self.assertFalse(prompt_store.reload().ok)
        self.assertEqual(prompts.summary_instructions("price_base_metals"), before)

    def test_legacy_error_import_has_same_identity(self):
        from app.analysis.data_sources import DataSourceError as legacy_error
        self.assertIs(legacy_error, DataSourceError)


if __name__ == "__main__":
    unittest.main()
