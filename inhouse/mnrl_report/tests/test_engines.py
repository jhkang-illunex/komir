# -*- coding: utf-8 -*-
"""엔진 계층 테스트 — DB·LLM 없이 버전 계산, 규칙 엔진 필터, 생성형 엔진 검증/폐기 규칙.
    cd inhouse && python -m unittest mnrl_report/tests/test_engines.py
"""
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mnrl_report.config import get_config  # noqa: E402
from mnrl_report.engines import EngineResult, GenEngine, RuleEngine  # noqa: E402
from mnrl_report.engines.base import compute_version  # noqa: E402
from mnrl_report.engines.gen_engine import PROMPT_DIR, evidence_text, load_prompts, unwrap, validate  # noqa: E402
from mnrl_report.engines.rule_engine import RULE_FILES  # noqa: E402
from mnrl_report.policy import LLM, POLICIES, RULE, columns_of  # noqa: E402
from mnrl_report.tests.test_rules import BASE, CUSTOMS, DIAG, PRICE, PROD, RESV  # noqa: E402

CFG = get_config()
VER_RE = re.compile(r"^\d{6}-[0-9a-f]{8}$")


class VersionTest(unittest.TestCase):
    def test_format_and_determinism(self):
        v1 = compute_version("rule", RULE_FILES)
        v2 = compute_version("rule", RULE_FILES)
        self.assertRegex(v1.ver, VER_RE)
        self.assertEqual(v1.ver, v2.ver)
        self.assertEqual(len(v1.files), len(RULE_FILES))
        self.assertLessEqual(len(v1.ver), 30)  # ai_rpt_*.rule_ver varchar(30)

    def test_content_change_changes_sha_and_date(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a" / "b" / "rule.py"
            p.parent.mkdir(parents=True)
            p.write_text("x = 1\n")
            os.utime(p, (0, time.mktime((2026, 1, 2, 0, 0, 0, 0, 0, -1))))
            v1 = compute_version("t", [p])
            self.assertEqual(v1.ver_date, "260102")
            p.write_text("x = 2\n")
            os.utime(p, (0, time.mktime((2026, 3, 4, 0, 0, 0, 0, 0, -1))))
            v2 = compute_version("t", [p])
            self.assertNotEqual(v1.sha, v2.sha)
            self.assertEqual(v2.ver_date, "260304")

    def test_extra_changes_sha(self):
        a = compute_version("gen", RULE_FILES, extra="openai_compat:model-a")
        b = compute_version("gen", RULE_FILES, extra="openai_compat:model-b")
        self.assertNotEqual(a.sha, b.sha)
        self.assertEqual(a.ver_date, b.ver_date)


class RuleEngineTest(unittest.TestCase):
    def test_generate_only_rule_columns(self):
        eng = RuleEngine(CFG)
        self.assertEqual(eng.engine_type, "RULE")
        self.assertRegex(eng.version.ver, VER_RE)
        facts = {"name": "텅스텐", "price": PRICE, "diag": DIAG, "customs": CUSTOMS, "production": PROD, "reserve": RESV}
        res = eng.generate("ai_rpt_mnrl", {"base": BASE, "code": "MNRL0018", "facts": facts})
        self.assertIsInstance(res, EngineResult)
        self.assertTrue(set(res.columns) <= set(columns_of("ai_rpt_mnrl", "RULE")))
        self.assertEqual(res.columns["grade_nm"], "주의")
        self.assertGreater(res.filled, 15)
        self.assertIn("customs", res.evidence)
        for c in columns_of("ai_rpt_mnrl", "LLM") + columns_of("ai_rpt_mnrl", "MANUAL"):
            self.assertNotIn(c, res.columns)

    def test_overall(self):
        eng = RuleEngine(CFG)
        facts = {"overall": {"overall_score": 63.2, "overall_wow": 2.3}, "gscpi": None, "minerals": {
            "MNRL0008": {"name": "동", "price": PRICE, "diag": DIAG, "customs": None, "production": PROD}}}
        res = eng.generate("ai_rpt_overall", {"base": BASE, "code": None, "facts": facts})
        self.assertEqual(res.columns["diag_grade_cd"], "CAUTION")
        self.assertTrue(set(res.columns) <= set(columns_of("ai_rpt_overall", "RULE")))


class _FakeOut:
    def __init__(self, text):
        self.text = text


class _FakeChat:
    """컬럼명별로 정해진 답을 돌려주는 가짜 LLM."""
    def __init__(self, answers: dict):
        self.answers, self.calls = answers, []

    def complete(self, system, user, **kw):
        col = user.split("\n", 1)[0].replace("[항목] ", "")
        self.calls.append((col, system, user))
        return _FakeOut(self.answers.get(col, "(없음)"))


class GenEngineTest(unittest.TestCase):
    def test_prompts_match_policy(self):
        for table in ("ai_rpt_mnrl", "ai_rpt_overall"):
            system, cols, needs = load_prompts(table)
            self.assertTrue(system)
            llm_cols = set(columns_of(table, "LLM"))
            self.assertEqual(set(cols), llm_cols, f"{table} 프롬프트 절 ≠ LLM 정책 컬럼")
            self.assertEqual(set(needs), llm_cols)
        _, _, needs = load_prompts("ai_rpt_mnrl")
        self.assertEqual(needs["smry_cause_txt"], {"news"})
        self.assertEqual(needs["risk_narr_txt"], set())

    def test_version_includes_prompts_and_model(self):
        eng = GenEngine(CFG, chat=_FakeChat({}))
        self.assertEqual(eng.engine_type, "GEN")
        self.assertRegex(eng.version.ver, VER_RE)
        names = {Path(f).name for f in eng.version.files}
        self.assertIn("gen_engine.py", names)
        for p in PROMPT_DIR.glob("*.md"):
            self.assertIn(p.name, names)
        self.assertIn(eng.model_nm or "", eng.version.extra)

    def test_validate(self):
        ev = "- production_txt: 세계 생산량은 약 85천톤, 상위 3개국 점유율은 85.2%"
        self.assertIsNone(validate("risk_narr_txt", "중국이 85.2%를 점유해 `25년 편중이 큽니다.", ev))
        self.assertEqual(validate("risk_narr_txt", "", ev), "empty")
        self.assertEqual(validate("risk_narr_txt", "반드시 오릅니다.", ev), "forbidden_phrase")
        self.assertTrue(validate("risk_narr_txt", "점유율 92%로 높습니다.", ev).startswith("number_not_in_evidence"))
        self.assertTrue(validate("risk1_title", "가" * 61, ev).startswith("too_long"))
        self.assertEqual(validate("risk_narr_txt", "산업 수요 배경에 대한 정보가 없습니다.", ev), "meta_no_info_sentence")
        self.assertEqual(validate("smry_cause_txt", "공급측면에서 가 주요 원인으로 분석됩니다.", ev), "empty_placeholder")
        self.assertEqual(validate("diag_key_txt", "주석 가격 상승 [원인 ]", ev), "empty_placeholder")
        self.assertEqual(validate("diag_key_txt", "아연 가격 상승 []", ev), "empty_placeholder")
        self.assertEqual(validate("risk2_narr_txt", "가격 변동성을 심화시킬 수 있는 원인은 입니다.", ev), "empty_placeholder")
        self.assertIsNone(validate("risk2_narr_txt", "가격 변동성을 심화시킬 수 있는 원인은 수출통제입니다.", ev))
        self.assertEqual(validate("risk2_narr_txt", "원인에 대한 정보는 .", ev), "empty_placeholder")
        self.assertIsNone(validate("risk_narr_txt", "이 경우 85.2%의 편중은 리스크를 키웁니다.", ev))
        ev2 = "- smry_quant_txt: 주간 평균가격은 전주 대비 알루미늄 4.8% 하락, 주석 4.61% 상승을 나타내었습니다."
        self.assertEqual(validate("risk2_narr_txt", "알루미늄과 주석이 각각 4.8%, 4.61% 하락하였습니다.", ev2), "direction_mismatch(4.61)")
        self.assertIsNone(validate("risk2_narr_txt", "알루미늄은 4.8% 하락, 주석은 4.61% 상승하였습니다.", ev2))

    def test_unwrap(self):
        self.assertEqual(unwrap('{ "risk1_title": "중국 의존도 심화" }'), "중국 의존도 심화")
        self.assertEqual(unwrap('{ "(없음)": "(없음)"}'), "")
        self.assertEqual(unwrap('{ "(없음)'), "")
        self.assertEqual(unwrap('{\t"diag_key_txt": "수입액 감소"}'), "수입액 감소")
        self.assertEqual(unwrap('```json\n{"a": "문장입니다."}\n```'), "문장입니다.")
        self.assertEqual(unwrap('"따옴표 문장"'), "따옴표 문장")
        self.assertEqual(unwrap("점유율이 높습니다. (없음)"), "")  # 섞어 쓰면 통째로 비움
        self.assertEqual(unwrap("(없음)"), "")
        self.assertEqual(unwrap("{   }"), "")

    def test_generate_drops_and_fills(self):
        rule = RuleEngine(CFG)
        facts = {"name": "텅스텐", "price": PRICE, "diag": DIAG, "customs": CUSTOMS, "production": PROD, "reserve": RESV}
        rule_res = rule.generate("ai_rpt_mnrl", {"base": BASE, "code": "MNRL0018", "facts": facts})
        chat = _FakeChat({
            "risk_narr_txt": "상위 3개국이 세계 생산량의 85.2%를 점유하고 있어 공급 편중이 높은 상황입니다.",
            "response_txt": '{"response_txt": "비축 확대와 수입선 다변화가 필요합니다."}',  # JSON 껍데기 → 언랩
            "price_bg_recent_txt": "가격이 99% 급등했습니다.",   # 근거 밖 숫자 → 폐기
            "diag_key_txt": "(주요 내용) 반드시 상승",            # 금지어 → 폐기
        })
        eng = GenEngine(CFG, chat=chat)
        res = eng.generate("ai_rpt_mnrl", {"base": BASE, "code": "MNRL0018", "facts": facts, "rule": rule_res, "news": []})
        self.assertEqual(set(res.columns), {"risk_narr_txt", "response_txt"})
        self.assertEqual(res.columns["response_txt"], "비축 확대와 수입선 다변화가 필요합니다.")
        # 뉴스 근거 없음 → needs:news 컬럼 3개는 호출 없이 폐기
        for c in ("smry_cause_txt", "price_bg_recent_txt", "diag_key_txt"):
            self.assertEqual(res.dropped[c], "no_news_evidence")
        self.assertEqual({c for c, _, _ in chat.calls}, {"risk_narr_txt", "response_txt"})
        # 뉴스 근거가 있으면 호출되고 검증 규칙이 적용된다
        res2 = eng.generate("ai_rpt_mnrl", {"base": BASE, "code": "MNRL0018", "facts": facts, "rule": rule_res,
                                            "news": ["중국, 텅스텐 수출통제 강화"]})
        self.assertEqual(res2.dropped["smry_cause_txt"], "empty")  # "(없음)"
        self.assertTrue(res2.dropped["price_bg_recent_txt"].startswith("number_not_in_evidence"))
        self.assertEqual(res2.dropped["diag_key_txt"], "forbidden_phrase")
        self.assertEqual({c for c, _, _ in chat.calls}, set(columns_of("ai_rpt_mnrl", "LLM")))
        self.assertIn("중국, 텅스텐 수출통제 강화", chat.calls[-1][2])
        # 근거에는 RULE 문장만 들어가고 LLM/MANUAL 컬럼은 없다
        ev = evidence_text(rule_res, [])
        for c, v in rule_res.columns.items():
            if POLICIES["ai_rpt_mnrl"][c] == RULE and v:
                self.assertIn(f"- {c}:", ev)
        self.assertNotIn("domestic_prod_txt", ev)

    def test_no_evidence_skips_llm(self):
        chat = _FakeChat({"response_txt": "무엇이든"})
        eng = GenEngine(CFG, chat=chat)
        empty = EngineResult(table="ai_rpt_mnrl")
        res = eng.generate("ai_rpt_mnrl", {"rule": empty, "news": []})
        self.assertEqual(res.columns, {})
        self.assertEqual(chat.calls, [])
        self.assertTrue(res.notes)

    def test_llm_policy_unchanged(self):
        self.assertEqual(POLICIES["ai_rpt_mnrl"]["risk_narr_txt"], LLM)


if __name__ == "__main__":
    unittest.main()
