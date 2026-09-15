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
        # 2026-09-10 main-agent 지시 — 발주처 원본 업무지시서 §3.1 요구사항으로
        # price_* "주요 지표" 표를 다시 켠다(2026-09-09 오전 2차 피드백 결정
        # 번복). 이 fixture(관측치 2건)는 latest_price·period_high·period_low·
        # drawdown_from_period_high_pct만 계산되고 week/month/year_avg·
        # price_streak_length·recent_volatility_pct는 데이터 부족으로 생성되지
        # 않는다 — 표가 다시 켜졌다는 것과 9개 화이트리스트가 존재하는 지표만
        # 순서·라벨대로 골라낸다는 것 둘 다 검증한다.
        self.assertIn("## 주요 지표\n", rendered)
        self.assertIn("| 현재가격 | 110 | 달러/톤 |", rendered)
        self.assertIn("| 최고가 | 110 | 달러/톤 |", rendered)
        self.assertIn("| 최저가 | 100 | 달러/톤 |", rendered)
        self.assertIn("| 낙폭 | 0 | % |", rendered)
        # day_over_day_change_pct는 9개 화이트리스트에 없어 값 자체는 응답
        # key_metrics에 있어도 표에는 나오지 않아야 한다.
        self.assertNotIn("전일대비", rendered)
        self.assertNotIn("전주 대비", rendered)
        self.assertNotIn("전월 대비", rendered)
        self.assertNotIn("전년 대비", rendered)
        self.assertNotIn("연속 추세", rendered)
        self.assertNotIn("변동성", rendered)
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
        # 2026-09-10 발주처 피드백[4] — 메이저·희소·광물종합 지수를 한 문장에
        # 섞어 비교하던 weekly_subindex_comparison("현재 메이저금속지수는
        # ~포인트, 희소금속지수는 ~포인트이며...")을 지수별 자기완결 문장
        # 3개로 대체(`summary.py::_replace_composite_subindex_narrative`)
        # 하면서 "현재 " 접두어 없이 지수별로 따로 등장하도록 바뀌었다.
        report = render_markdown_report(response)
        # 2026-09-13 사용자 지시 — 소수점 2번째 자리가 0이면 생략(_number
        # 트림 규칙 신설)하면서 920.00/790.00포인트가 920/790포인트로 바뀜.
        self.assertIn("메이저금속지수는 920포인트", report)
        self.assertIn("희소금속지수는 790포인트", report)

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

    def test_map_korea_import_concentration_uses_cr3_wording(self):
        """2026-09-15 발주처 피드백(대상 3) — "상위 3개국 수입 비중은 …" 대신 발주처
        템플릿처럼 "상위 3개국의 수입 집중도(CR3)는 …"으로."""
        countries = [("중국", 500.0), ("칠레", 300.0), ("일본", 200.0), ("미국", 100.0), ("페루", 50.0), ("호주", 25.0)]
        response = AnalysisSummaryService().analyze(AnalysisSummaryRequest(
            page_id="map_korea", mineral="동", mineral_name="동",
            observations=[
                {"date": "2026-06-30", "country_code": f"C{i}", "country_name": name,
                 "import_amount": amount, "export_amount": 10.0}
                for i, (name, amount) in enumerate(countries)
            ],
        ))
        texts = [s.text for sec in ("core_diagnosis", "major_changes", "current_position") for s in getattr(response.summary, sec)]
        sentence = next(t for t in texts if "수입 집중도(CR3)" in t)
        self.assertEqual(
            sentence,
            "상위 3개국의 수입 집중도(CR3)는 85.11%이며, 상위 5개국까지 합산하면(CR5) 전체의 97.87%를 차지합니다.",
        )
        self.assertFalse(any("수입 비중은" in t for t in texts))

    def test_map_mineral_ranking_detail_and_major_changes(self):
        """2026-09-15 발주처 피드백(대상 5 광물지도-매장량) — 국가별 순위에 상위
        3개국 값+증감률·CR3, 주요 변화에 방향별 2개국+급변 구간, 1위 vs 기타
        총정리. 수치는 동 매장량 실데이터(2021~2025)를 1/100,000로 줄인 것."""
        rows = {
            "칠레": [2000, 1900, 1900, 1900, 1800], "호주": [930, 970, 1000, 1000, 1000],
            "페루": [770, 810, 1200, 1000, 850], "콩고민주공화국": [None, 310, 800, 800, 800],
            "러시아": [620, 620, 800, 800, 800], "인도네시아": [240, 240, 240, 210, 210],
        }
        observations = [
            {"year": 2021 + i, "country_code": name, "country_name": name, "value": value}
            for name, values in rows.items() for i, value in enumerate(values) if value is not None
        ]
        share = {"data": [
            {"ntnKornNm": "_ETC_", "ntnEngCd": "OT", "before1": "2,100", "rate": "21.43"},
            {"ntnKornNm": "_TOTAL_", "ntnEngCd": "SU", "before5": "8,800", "before4": "8,900",
             "before3": "9,900", "before2": "9,800", "before1": "9,800", "rate": "100.00"},
        ]}
        response = AnalysisSummaryService().analyze(AnalysisSummaryRequest(
            page_id="map_mineral", mineral="동", mineral_name="동", measure="reserves", unit="톤",
            observations=observations, komis_share_response=share,
        ))
        by_id = {s.evidence_ids[0]: s.text for sec in ("core_diagnosis", "major_changes") for s in getattr(response.summary, sec)}
        self.assertEqual(by_id["world_total_trend"], "연도별 세계 매장량 합계는 2021년 8,800톤 → 2022년 8,900톤 → 2023년 9,900톤 → 2024년 9,800톤 → 2025년 9,800톤입니다.")
        # 대상 6 — 마지막 변화(0%)가 보합, 2023→2024(-1.0%)도 보합, 2022→2023(+11.2%)에서 끊긴다.
        self.assertEqual(by_id["world_total_recent_trend"], "세계 매장량은 2023년 이후 9,800톤~9,900톤 수준에서 보합세를 유지하고 있습니다.")
        self.assertEqual(by_id["top3_period_change"], "조회기간(2021~2025년) 상위 3개국의 매장량 변화는 칠레 2,000톤→1,800톤(10% 감소, 1위 유지), 호주 930톤→1,000톤(7.53% 증가, 2위 유지), 페루 770톤→850톤(10.39% 증가, 3위 유지)입니다.")
        self.assertEqual(by_id["top3_concentration"], "상위 3개국의 매장량 집중도(CR3)는 37.24%로, 전체 매장량의 3분의 1 이상이 이 3개국에 집중돼 있습니다. 상위 5개국까지 합산하면(CR5) 전체의 53.57%를 차지합니다.")
        # 대상 6 — 오르내린 국가만 후보(칠레·인도네시아는 감소만, 호주·러시아는 증가만).
        self.assertEqual(by_id["volatility_country"], "페루는 2021년 770톤에서 2023년 1,200톤으로 증가했다가 2025년 850톤으로 감소하는 등 조회기간 매장량 변동폭이 가장 큰 국가(최대값 대비 최소값 차이 35.83%)입니다.")
        self.assertEqual(by_id["extreme_increase_1"], "조회기간 중 매장량이 가장 크게 증가한 국가는 콩고민주공화국으로, 2021년 0톤에서 2025년 800톤으로 800톤 (신규 집계) 증가했습니다. 특히 2022년 310톤에서 2023~2025년 800톤(세계 비중 8.16%)으로 급격히 상향돼 변화가 집중됐습니다.")
        self.assertEqual(by_id["extreme_increase_2"], "다음으로 러시아는 2021년 620톤에서 2025년 800톤으로 180톤 (29.03%) 증가했습니다. 특히 2021~2022년 620톤에서 2023~2025년 800톤(세계 비중 8.16%)으로 급격히 상향돼 변화가 집중됐습니다.")
        self.assertEqual(by_id["extreme_decrease_1"], "가장 크게 감소한 국가는 칠레로, 2021년 2,000톤에서 2025년 1,800톤으로 200톤 (10%) 감소했습니다. 연도별로는 2022~2024년 1,900톤에서 2025년 1,800톤(세계 비중 18.37%)으로 줄어든 구간의 변화 폭이 가장 컸습니다.")
        self.assertEqual(by_id["extreme_decrease_2"], "다음으로 인도네시아는 2021년 240톤에서 2025년 210톤으로 30톤 (12.5%) 감소했습니다. 연도별로는 2021~2023년 240톤에서 2024~2025년 210톤(세계 비중 2.14%)으로 줄어든 구간의 변화 폭이 가장 컸습니다.")
        self.assertEqual(by_id["top_country_vs_others"], "기타 국가 합산은 2025년 2,100톤(21.43%)으로, 단일 국가 기준 1위인 칠레(1,800톤, 18.37%)를 상회하고 있어 복수의 중소 매장국에도 상당한 매장량이 분포돼 있습니다.")
        report = render_markdown_report(response)
        ranking = report.split("## 국가별 순위 및 변화")[1].split("## 주요 변화")[0]
        changes = report.split("## 주요 변화")[1].split("## 주요 지표")[0]
        self.assertIn(by_id["top3_period_change"], ranking)
        self.assertIn(by_id["top3_concentration"], ranking)
        for key in ("extreme_increase_1", "extreme_increase_2", "extreme_decrease_1", "extreme_decrease_2", "volatility_country", "top_country_vs_others"):
            self.assertIn(by_id[key], changes)
            self.assertNotIn(by_id[key], ranking)
        metrics = {m.id: m.value for m in response.key_metrics}
        self.assertEqual((metrics["max_increase_country"], metrics["max_decrease_country"]), ("콩고민주공화국", "칠레"))

    def test_composite_period_average_and_weight_label(self):
        """2026-09-15 발주처 피드백(광물종합지수) — 조회기간 평균 지수 metric 추가,
        구성 광종 문장은 "구성 광종(가중치)은 …"으로. 1년 넘는 관측치를 주면
        전주·전월·전년 대비가 모두 나온다(프로즌 계산기 기존 동작 확인)."""
        from datetime import date, timedelta

        start = date(2025, 8, 1)
        observations = [
            {"date": (start + timedelta(days=7 * i)).isoformat(), "composite_index": 1000 + i,
             "major_metals_index": 900 + i, "minor_metals_index": 800 + i}
            for i in range(60)  # 2025-08-01 ~ 2026-09-18, 주간 60건
        ]
        response = AnalysisSummaryService().analyze(AnalysisSummaryRequest(
            page_id="indicator_composite", observations=observations,
        ))
        by_id = {m.id: m for m in response.key_metrics}
        for metric_id in ("weekly_composite_change", "monthly_composite_change", "yearly_composite_change"):
            self.assertIn(metric_id, by_id)
        average = by_id["period_average_composite_index"]
        self.assertEqual(average.label, "조회기간 평균 지수")
        self.assertEqual(average.unit, "포인트")
        self.assertAlmostEqual(average.value, 1000 + 59 / 2, places=6)
        report = render_markdown_report(response)
        self.assertIn("구성 광종(가중치)은 ", report)
        self.assertNotIn(" 구성 광종은 ", report)
        self.assertIn("| 조회기간 평균 지수 |", report)

    def test_relative_value_fact_uses_percent_and_spelled_out_pair(self):
        """2026-09-15 발주처 피드백 — 가격비율은 퍼센트(86.53%)로, 평균도 같은
        단위로, "동/니켈" 대신 "니켈 대비 동의"로 풀어 쓴다."""
        from app.analysis.komir_summary import _relative_value_fact

        # 20일 중 앞 19일은 비율 0.6, 마지막 날만 0.8 → 평균 0.61, 괴리 +31.15%
        primary = [SimpleNamespace(date=f"2026-01-{d:02d}", commerce_price=60.0) for d in range(1, 20)]
        primary.append(SimpleNamespace(date="2026-01-20", commerce_price=80.0))
        compare = [SimpleNamespace(date=f"2026-01-{d:02d}", commerce_price=100.0) for d in range(1, 21)]
        fact = _relative_value_fact("동", primary, "니켈", compare)
        self.assertEqual(
            fact,
            "니켈 대비 동의 가격비율은 현재 80%로, 조회기간 평균(61%) 대비 31.15% 높은 수준입니다.",
        )
        self.assertNotIn("동/니켈", fact)
        self.assertIsNone(_relative_value_fact("동", primary[:19], "니켈", compare[:19]))


if __name__ == "__main__":
    unittest.main()
