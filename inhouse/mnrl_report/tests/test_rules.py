# -*- coding: utf-8 -*-
"""규칙 문장 단위 테스트 — DB 없이 facts 고정값으로 rules/·writer SQL 조립을 검사한다.
    cd inhouse && python -m unittest mnrl_report/tests/test_rules.py
"""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mnrl_report.config import get_config, latest_monday, month_week_label, week_meta  # noqa: E402
from mnrl_report.policy import KEYS, POLICIES, columns_of  # noqa: E402
from mnrl_report.rules import fmt, mnrl, overall  # noqa: E402

BASE = date(2026, 6, 15)  # 월요일
CFG = get_config()

CUSTOMS = {
    "latest_ym": "202607",
    "month": {"ton": 24_000.0, "usd": 1.9e8}, "month_prev_year": {"ton": 22_000.0, "usd": 1.76e8},
    "ytd": {"ton": 231_000.0, "usd": 2.13e9}, "ytd_prev_year": {"ton": 210_000.0, "usd": 1.99e9},
    "year_tot": {"2021": {"ton": 8_147.8, "usd": 335_293_000}, "2025": {"ton": 6_507.7, "usd": 303_112_000}},
    "prev_year": "2025", "base_year": "2021", "cagr_pct": -2.49,  # 2021→2025 4년
    "shares_year": "2025", "shares": [("중국", 63.0), ("일본", 16.4), ("미국", 4.7), ("베트남", 4.3), ("독일", 2.5)],
    "hhi": 4295.0,
}
PROD = {"year": "2025", "world_ton": 85_000.0, "top": [("중국", 67_000.0, 78.8), ("베트남", 3_000.0, 3.5), ("카자흐스탄", 2_400.0, 2.8)], "cr3_pct": 85.2}
RESV = {"year": "2025", "world_ton": 4_700_000.0, "top": [("중국", 2_500_000.0, 53.2), ("호주", 570_000.0, 12.1), ("러시아", 400_000.0, 8.5)], "cr3_pct": 73.8}
PRICE = {"as_of": "20260615", "price": 13698.0, "wow_pct": 1.06, "mom_pct": 5.9, "yoy_pct": 40.2}
DIAG = {"score": 63.2, "grade": "CAUTION", "score_wow": 2.3, "score_mom": 4.7, "streak_wk": 5}


class FmtTest(unittest.TestCase):
    def test_units(self):
        self.assertEqual(fmt.kton(24_000), "24천톤")
        self.assertEqual(fmt.kton(4_700_000), "4.7백만톤")
        self.assertEqual(fmt.eok_usd(1.9e8), "1.9억달러")
        self.assertEqual(fmt.k_usd(386_379_000), "386,379천달러")
        self.assertEqual(fmt.k_usd_u(86_537_000), "U$86,537천")
        self.assertEqual(fmt.pct(63.0), "63%")
        self.assertEqual(fmt.points(2.3), "2.3p")
        self.assertEqual(fmt.signed_dir(-1.0), "하락")
        self.assertEqual(fmt.yy(2026), "`26년")

    def test_week(self):
        self.assertEqual(latest_monday(date(2026, 9, 17)), date(2026, 9, 14))
        self.assertEqual(week_meta(BASE)["rpt_week_no"], 25)
        self.assertEqual(month_week_label(BASE), "6월 3주차")


class MnrlRuleTest(unittest.TestCase):
    def test_full_row(self):
        facts = {"name": "텅스텐", "price": PRICE, "diag": DIAG, "customs": CUSTOMS, "production": PROD, "reserve": RESV}
        row = mnrl.build("MNRL0018", facts, BASE, CFG)
        self.assertEqual(row["title"], "텅스텐 수급위기 진단결과 보고서")
        self.assertEqual(row["grade_nm"], "주의")
        self.assertIn("6월 3주차 수급 위험지수는 63.2로 전주 대비 2.3p 상승하였습니다.", row["smry_quant_txt"])
        self.assertIn("주간 평균가격도 전주 대비 1.06%의 상승세", row["smry_quant_txt"])
        self.assertEqual(row["diag_result_txt"], '(수급 주의) 63.2 (전월 대비 4.7p 상승), 5주 연속 "주의"')
        self.assertTrue(row["import_month_txt"].startswith("텅스텐의 `26년 7월 수입량은 24천톤, 수입액은 1.9억달러(전년 대비 8% 증가)이며"))
        self.assertIn("1~7월 누적 수입량은 231천톤, 수입액은 21.3억달러(전년 대비 7% 증가)입니다.", row["import_month_txt"])
        self.assertEqual(row["import_cagr_txt"], "`25년 텅스텐의 수입액은 303,112천달러로 연평균 증가율(CAGR)은 -2.5%를 기록하였습니다.")
        self.assertEqual(row["import_ntn_txt"], "주로 중국(63%), 일본(16.4%), 미국(4.7%) 등에서 수입하며, 독점도를 평가하는 HHI(허시만-허핀달 지수)는 4,295을 기록하였습니다.")
        self.assertEqual(row["import_struct_txt"], "편중도가 높은 수준으로 수급리스크를 확대시키는 요인입니다.")
        self.assertEqual(row["production_txt"], "(생산량) 세계 생산량은 약 85천톤(금속기준), 상위 3개국 점유율은 85.2%입니다. * 중국(67천톤, 78.8%), 베트남(3천톤, 3.5%), 카자흐스탄(2.4천톤, 2.8%)")
        self.assertTrue(row["reserve_txt"].startswith("(매장량) 세계 매장량은 약 4.7백만톤(금속기준), 상위 3개국 점유율은 73.8%입니다."))
        self.assertIn("주요 3국이 `25년 글로벌 생산량의 85.2%를 점유", row["risk_quant_txt"])
        self.assertIsNone(row.get("price_signal_cd"))  # 산식 미확정 → 계산 안 함

    def test_missing_sources_leave_null(self):
        row = mnrl.build("MNRL0001", {"name": "리튬", "price": None, "diag": None, "customs": None, "production": None, "reserve": None}, BASE, CFG)
        for c in ("smry_quant_txt", "diag_result_txt", "import_month_txt", "reserve_txt", "production_txt", "risk_quant_txt", "price_foot_txt"):
            self.assertIsNone(row.get(c), c)
        self.assertEqual(row["title"], "리튬 수급위기 진단결과 보고서")


class OverallRuleTest(unittest.TestCase):
    def test_without_diag_uses_price_movers(self):
        facts = {"overall": None, "minerals": {
            "MNRL0008": {"name": "동", "price": PRICE, "diag": None, "customs": None, "production": PROD},
            "MNRL0002": {"name": "니켈", "price": {"as_of": "20260615", "price": 17720.0, "wow_pct": -0.14, "mom_pct": None, "yoy_pct": None}, "diag": None, "customs": CUSTOMS, "production": None},
        }}
        row = overall.build(facts, BASE, CFG)
        self.assertEqual(row["focus_mnrl_cds"], "MNRL0008,MNRL0002")
        self.assertIsNone(row.get("overall_score"))
        self.assertIsNone(row.get("idx_anal_txt"))
        self.assertIn("USGS에 따르면, 동의 세계 생산량은 `25년 기준 85,000톤으로 국가별 비중은 중국 78.8%", row["risk2_quant_txt"])
        # 방향 혼재(동 +1.06%, 니켈 -0.14%): 광종마다 방향어, 첫 항목 방향을 일괄 적용하지 않는다
        self.assertEqual(row["smry_quant_txt"], "6월 3주차 주간 평균가격은 전주 대비 동 1.06% 상승, 니켈 0.14% 하락을 나타내었습니다.")
        self.assertIn("6월 3주차 동의 가격은 13,698달러로 전주 대비 1.06%, 전월 대비 5.9%, 전년 대비 40.2%의 상승률을 기록하였습니다.", row["risk2_quant_txt"])
        self.assertIn("6월 3주차 니켈의 가격은 17,720달러로 전주 대비 0.14%의 하락률을 기록하였습니다.", row["risk2_quant_txt"])
        self.assertIn("한국의 니켈 수입금액은 `25년 기준 U$303,112천으로", row["risk4_quant_txt"])

    def test_mixed_period_directions(self):
        facts = {"overall": None, "minerals": {
            "MNRL0016": {"name": "주석", "price": {"as_of": "20260615", "price": 54900.0, "wow_pct": -4.61, "mom_pct": 3.2, "yoy_pct": 69.8}, "diag": None, "customs": None, "production": None}}}
        row = overall.build(facts, BASE, CFG)
        self.assertEqual(row["smry_quant_txt"], "6월 3주차 주석의 주간 평균가격은 전주 대비 4.61%의 하락세를 나타내었습니다.")
        self.assertEqual(row["risk2_quant_txt"], "6월 3주차 주석의 가격은 54,900달러로 전주 대비 4.61% 하락, 전월 대비 3.2% 상승, 전년 대비 69.8% 상승을 기록하였습니다.")

    def test_with_diag(self):
        facts = {"overall": {"overall_score": 63.2, "overall_wow": 2.3}, "minerals": {
            "MNRL0008": {"name": "동", "price": PRICE, "diag": DIAG, "customs": None, "production": None},
            "MNRL0002": {"name": "니켈", "price": None, "diag": {"score": 40.0, "grade": "WATCH", "score_wow": -1.0, "score_mom": None, "streak_wk": 3}, "customs": None, "production": None},
        }}
        row = overall.build(facts, BASE, CFG)
        self.assertEqual(row["overall_level_txt"], "높은")
        self.assertIn("전체 평균 수급 위기지수는 63.2로 전주 대비 2.3p 상승하였으며, 특히 동, 니켈의 수급 리스크가 심화되고 있습니다.", row["smry_quant_txt"])
        self.assertEqual(row["diag_grade_cd"], "CAUTION")
        self.assertEqual(row["diag_tbl_title_txt"], '(위기진단) 동 등 총 1개 광종 "주의" 단계')
        self.assertIn("핵심광물 2종 中 1종 수급 이상징후 확인", row["idx_anal_txt"])
        self.assertIn('(동) 위기진단지표 63.2 (전주 대비 2.3p↑), 위기등급 "주의" (5주 연속)', row["judge_quant_txt"])


class ConfigTest(unittest.TestCase):
    def test_default_targets_are_the_five(self):
        import os
        from mnrl_report.config import TARGET_MINERALS
        saved = os.environ.pop("MNRL_REPORT_MINERALS", None)
        try:
            self.assertEqual(get_config().minerals, ["MNRL0008", "MNRL0002", "MNRL0003", "MNRL0001", "MNRL1001"])
            self.assertEqual(len(TARGET_MINERALS), 5)
            os.environ["MNRL_REPORT_MINERALS"] = "all"
            self.assertIsNone(get_config().minerals)
            os.environ["MNRL_REPORT_MINERALS"] = "MNRL0018, MNRL0008"
            self.assertEqual(get_config().minerals, ["MNRL0018", "MNRL0008"])
        finally:
            os.environ.pop("MNRL_REPORT_MINERALS", None)
            if saved is not None:
                os.environ["MNRL_REPORT_MINERALS"] = saved


class PolicyTest(unittest.TestCase):
    def test_policy_covers_all_columns(self):
        self.assertEqual(len(POLICIES["ai_rpt_overall"]), 45)
        self.assertEqual(len(POLICIES["ai_rpt_mnrl"]), 42)
        self.assertEqual(KEYS["ai_rpt_mnrl"], ["mnrknd_unq_cd", "base_ymd"])
        self.assertIn("domestic_prod_txt", columns_of("ai_rpt_mnrl", "MANUAL"))
        self.assertNotIn("domestic_prod_txt", columns_of("ai_rpt_mnrl", "RULE"))


if __name__ == "__main__":
    unittest.main()
