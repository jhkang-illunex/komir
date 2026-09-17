# -*- coding: utf-8 -*-
"""광산자료 집계 파이프라인(rag_core/retrieval/mine_aggregate.py) 단위 테스트 —
DB·실제 LLM·실제 OKF/트리 파일 없이 순수 함수 + 가짜 LLM(rag_chat/tests/
smoke_page_recommend.py의 결정론적 더블 관례)만으로 검사한다.

PRD `documents/산출물/2026-W38_0914-0920/광산자료_집계질의_실시간계산파이프라인_
PRD_260917.md` §5-1 "단위 테스트: 추출 스키마 파싱, 집계 정렬(최대/순위/compare),
회계연도 불일치 처리, found=false 항목 제외 로직"의 구현.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.llm_client import LLMOutputError, LLMInvocation  # noqa: E402
from rag_core.retrieval import mine_aggregate as ma  # noqa: E402


class UnitConversionTest(unittest.TestCase):
    def test_plain_tonnes(self):
        self.assertEqual(ma.normalize_unit_to_tonnes(100, "t"), 100)
        self.assertEqual(ma.normalize_unit_to_tonnes(100, "tonnes"), 100)
        self.assertEqual(ma.normalize_unit_to_tonnes(100, "wmt"), 100)
        self.assertEqual(ma.normalize_unit_to_tonnes(100, "dmt"), 100)

    def test_prefixed(self):
        self.assertEqual(ma.normalize_unit_to_tonnes(5, "kt"), 5_000)
        self.assertEqual(ma.normalize_unit_to_tonnes(41.9, "Mwmt"), 41_900_000)
        self.assertEqual(ma.normalize_unit_to_tonnes(1, "Mt"), 1_000_000)

    def test_pounds_matches_prd_factors(self):
        # PRD §4.4-1: Mlb×453.592, klb×0.453592
        self.assertAlmostEqual(ma.normalize_unit_to_tonnes(1, "Mlb"), 453.592, places=3)
        self.assertAlmostEqual(ma.normalize_unit_to_tonnes(1, "klb"), 0.453592, places=6)

    def test_kton_and_thousands_notation(self):
        # 2026-09-17 실측(구리 라이브 재현) — 대소문자·재무제표 관행 표기 누락으로
        # Escondida·Chuquicamata 등 세계 최대 구리광산이 전부 "환산 불가"로
        # 잘못 빠졌던 회귀 케이스.
        self.assertEqual(ma.normalize_unit_to_tonnes(1, "KTON"), 1_000)
        self.assertEqual(ma.normalize_unit_to_tonnes(1, "kton"), 1_000)
        self.assertEqual(ma.normalize_unit_to_tonnes(1234, "'000 tonnes"), 1_234_000)
        self.assertEqual(ma.normalize_unit_to_tonnes(1234, "000 tonnes"), 1_234_000)

    def test_unconvertible_returns_none(self):
        self.assertIsNone(ma.normalize_unit_to_tonnes(10, "koz"))
        self.assertIsNone(ma.normalize_unit_to_tonnes(10, "oz"))
        self.assertIsNone(ma.normalize_unit_to_tonnes(10, "mt"))  # 소문자 mt는 혼동 위험 — 임의 환산 금지
        self.assertIsNone(ma.normalize_unit_to_tonnes(None, "t"))
        self.assertIsNone(ma.normalize_unit_to_tonnes(10, None))
        self.assertIsNone(ma.normalize_unit_to_tonnes(10, "furlong"))


class MineralFolderTest(unittest.TestCase):
    def test_aliases_resolve(self):
        for name in ("구리", "동", "동(구리)", "copper", "CU", "cu"):
            self.assertEqual(ma.resolve_mineral_folder(name), "동_구리", name)
        self.assertEqual(ma.resolve_mineral_folder("니켈"), "니켈")
        self.assertEqual(ma.resolve_mineral_folder("uranium"), "우라늄")
        self.assertEqual(ma.resolve_mineral_folder("철"), "철광석")

    def test_unknown_returns_none(self):
        self.assertIsNone(ma.resolve_mineral_folder("텅스텐"))
        self.assertIsNone(ma.resolve_mineral_folder(""))


class MetricTermsTest(unittest.TestCase):
    def test_known_metric_expands_keywords(self):
        terms = ma.metric_search_terms("생산량")
        self.assertIn("Production", terms)

    def test_unknown_metric_falls_back_to_itself(self):
        # PRD §5-4 "지표 확장" — 지표명을 하드코딩하지 않아 새 지표도 그대로 동작
        self.assertEqual(ma.metric_search_terms("지분율"), ("지분율",))

    def test_default_basis(self):
        self.assertEqual(ma.default_basis("생산량"), "metal")
        self.assertEqual(ma.default_basis("광석 채굴량"), "ore")


def _obs(mine, year, value_tonnes, basis="metal", company=None, okf="x.md"):
    return ma.Observation(
        mine_key=ma._normalize_mine_name(mine), mine_name=mine, company=company,
        year=year, value_raw=value_tonnes, unit_raw="t", basis=basis,
        value_tonnes=value_tonnes, source_okf_path=okf, source_resource=okf,
    )


class BuildObservationsTest(unittest.TestCase):
    def test_found_false_excluded(self):
        tree = {"okf_path": "a.md", "resource": "a.pdf"}
        extraction = ma.DocExtraction(found=False, mines=[ma.MineRecord(mine="Foo", values=[ma.MineYearValue(year=2025, value=1.0, unit="t")])])
        self.assertEqual(ma.build_observations([(tree, extraction)]), [])

    def test_null_value_excluded(self):
        tree = {"okf_path": "a.md", "resource": "a.pdf"}
        extraction = ma.DocExtraction(found=True, mines=[ma.MineRecord(mine="Foo", values=[ma.MineYearValue(year=2025, value=None)])])
        self.assertEqual(ma.build_observations([(tree, extraction)]), [])

    def test_generic_mine_names_excluded(self):
        # 2026-09-17 실측(구리 라이브 검증) — "BHP Group"(회사 전체 합계)·
        # "unknown"(광산 특정 실패)이 개별 광산인 것처럼 섞여 나온 회귀.
        tree = {"okf_path": "a.md", "resource": "a.pdf"}
        extraction = ma.DocExtraction(found=True, mines=[
            ma.MineRecord(mine="BHP Group", values=[ma.MineYearValue(year=2025, value=2.0, unit="Mt", basis="metal")]),
            ma.MineRecord(mine="unknown", values=[ma.MineYearValue(year=2025, value=153.0, unit="kt", basis="metal")]),
            ma.MineRecord(mine="Escondida", values=[ma.MineYearValue(year=2025, value=1305.0, unit="kt", basis="metal")]),
        ])
        obs = ma.build_observations([(tree, extraction)])
        self.assertEqual({o.mine_name for o in obs}, {"Escondida"})

    def test_multi_mine_multi_year(self):
        tree = {"okf_path": "glencore.md", "resource": "glencore.pdf"}
        extraction = ma.DocExtraction(found=True, mines=[
            ma.MineRecord(mine="KCC", company="Glencore", values=[
                ma.MineYearValue(year=2024, value=100.0, unit="kt", basis="metal"),
                ma.MineYearValue(year=2025, value=110.0, unit="kt", basis="metal"),
            ]),
            ma.MineRecord(mine="Mutanda", company="Glencore", values=[
                ma.MineYearValue(year=2025, value=50.0, unit="kt", basis="metal"),
            ]),
        ])
        obs = ma.build_observations([(tree, extraction)])
        self.assertEqual(len(obs), 3)
        self.assertEqual({o.mine_name for o in obs}, {"KCC", "Mutanda"})


class RankObservationsTest(unittest.TestCase):
    def test_max_picks_highest_within_basis(self):
        observations = [
            _obs("Collahuasi", 2025, 169_500, basis="metal"),
            _obs("Weda Bay", 2025, 41_900_000, basis="ore"),  # PRD 실측: metal 순위에서 제외돼야 함
            _obs("Morenci", 2025, 120_000, basis="metal"),
        ]
        result = ma.rank_observations(observations, agg="max", target_basis="metal")
        self.assertEqual(len(result.ranked), 1)
        self.assertEqual(result.ranked[0].mine_name, "Collahuasi")
        self.assertTrue(any("Weda Bay" in note and "ore" in note for note in result.excluded_notes))

    def test_min(self):
        observations = [_obs("A", 2025, 100), _obs("B", 2025, 50), _obs("C", 2025, 200)]
        result = ma.rank_observations(observations, agg="min", target_basis="metal")
        self.assertEqual(result.ranked[0].mine_name, "B")

    def test_rank_top5_default(self):
        observations = [_obs(f"M{i}", 2025, i * 10) for i in range(1, 8)]
        result = ma.rank_observations(observations, agg="rank", target_basis="metal")
        self.assertEqual(len(result.ranked), 5)
        self.assertEqual(result.ranked[0].mine_name, "M7")

    def test_compare_matches_targets_only(self):
        observations = [_obs("Collahuasi", 2025, 100), _obs("Morenci", 2025, 200), _obs("Other", 2025, 300)]
        result = ma.rank_observations(
            observations, agg="compare", target_basis="metal", targets=["Collahuasi", "Morenci"],
        )
        self.assertEqual({o.mine_name for o in result.ranked}, {"Collahuasi", "Morenci"})

    def test_compare_missing_target_noted(self):
        observations = [_obs("Collahuasi", 2025, 100)]
        result = ma.rank_observations(
            observations, agg="compare", target_basis="metal", targets=["Collahuasi", "NoSuchMine"],
        )
        self.assertTrue(any("NoSuchMine" in note for note in result.excluded_notes))

    def test_year_rule1_explicit_year_filters(self):
        observations = [_obs("A", 2024, 100), _obs("A", 2025, 150), _obs("B", 2025, 90)]
        result = ma.rank_observations(observations, agg="rank", target_basis="metal", year=2025)
        self.assertFalse(result.year_substituted)
        years = {o.mine_name: o.year for o in result.ranked}
        self.assertEqual(years["A"], 2025)
        self.assertEqual(years["B"], 2025)

    def test_year_rule1_excludes_mine_without_that_year(self):
        observations = [_obs("A", 2024, 100), _obs("A", 2025, 150), _obs("B", 2023, 90)]
        result = ma.rank_observations(observations, agg="rank", target_basis="metal", year=2025)
        self.assertNotIn("B", {o.mine_name for o in result.ranked})
        self.assertTrue(any("B" in note and "2025" in note for note in result.excluded_notes))

    def test_duplicate_mine_same_year_basis_prefers_larger_value(self):
        # 2026-09-17 실측(구리 라이브 검증) — Escondida가 BHP 자체 보고서(100%
        # 기준 1305kt)와 Rio Tinto 보고서(30% 지분 기준 381.7kt) 양쪽에 같은
        # 연도·basis로 등장 — 실행마다 다른 값이 뽑히던 회귀. 큰 값(완전
        # 생산량으로 추정)을 결정적으로 우선한다.
        observations = [
            _obs("Escondida", 2025, 381.7, okf="rio_tinto.md"),
            _obs("Escondida", 2025, 1305.0, okf="bhp.md"),
            _obs("El Teniente", 2025, 310.1, okf="codelco.md"),
        ]
        result = ma.rank_observations(observations, agg="max", target_basis="metal", year=2025)
        self.assertEqual(result.ranked[0].mine_name, "Escondida")
        self.assertEqual(result.ranked[0].value_tonnes, 1305.0)
        self.assertEqual(result.ranked[0].source_okf_path, "bhp.md")

    def test_year_rule2_no_year_uses_each_mines_latest(self):
        # 회계연도 불일치 — A는 2025까지, B는 2024까지만 있어도 각자 최신을 쓴다.
        observations = [_obs("A", 2024, 100), _obs("A", 2025, 150), _obs("B", 2024, 90)]
        result = ma.rank_observations(observations, agg="rank", target_basis="metal", year=None)
        by_name = {o.mine_name: o.year for o in result.ranked}
        self.assertEqual(by_name["A"], 2025)
        self.assertEqual(by_name["B"], 2024)

    def test_year_rule3_substitutes_when_year_absent_everywhere(self):
        observations = [_obs("A", 2023, 100), _obs("B", 2024, 90)]
        result = ma.rank_observations(observations, agg="max", target_basis="metal", year=2099)
        self.assertTrue(result.year_substituted)
        self.assertEqual(len(result.ranked), 1)  # 최신 연도로 대체해 계속 답한다

    def test_unconvertible_unit_excluded(self):
        obs = _obs("A", 2025, None, basis="metal")
        obs.value_tonnes = None
        result = ma.rank_observations([obs], agg="max", target_basis="metal")
        self.assertEqual(result.ranked, [])
        self.assertTrue(any("환산 불가" in note for note in result.excluded_notes))


class RenderEvidenceTest(unittest.TestCase):
    def test_ranked_produces_table(self):
        observations = [_obs("Collahuasi", 2025, 169_500, company="Anglo American")]
        result = ma.rank_observations(observations, agg="max", target_basis="metal")
        ev = ma.render_evidence(
            mineral_name="구리", folder="동_구리", metric="생산량", agg="max", year=None,
            result=result, total_docs=21, found_docs=2,
        )
        self.assertEqual(ev.kind, "aggregated")
        self.assertIn("Collahuasi", ev.text)
        self.assertIn("| 순위 |", ev.text)
        self.assertIn("169,500", ev.text)

    def test_empty_ranked_reports_no_value_found(self):
        result = ma.rank_observations([], agg="max", target_basis="metal")
        ev = ma.render_evidence(
            mineral_name="구리", folder="동_구리", metric="지분율", agg="max", year=None,
            result=result, total_docs=21, found_docs=0,
        )
        self.assertIn("찾지 못했습니다", ev.text)
        self.assertNotIn("| 순위 |", ev.text)


class _FakeLLM:
    """`_extract_from_tree`가 기대하는 `.invoke(...)` 프로토콜만 구현한 결정론적
    더블(rag_chat/tests/smoke_page_recommend.py의 관례와 동일)."""

    def __init__(self, output=None, raise_error: bool = False):
        self._output = output
        self._raise = raise_error
        self.calls = 0

    def invoke(self, *, task, instructions, payload, output_model, max_tokens):
        self.calls += 1
        if self._raise:
            raise LLMOutputError("boom", record={})
        return LLMInvocation(output=self._output, record={})


class ExtractFromTreeTest(unittest.TestCase):
    def test_llm_failure_falls_back_to_not_found(self):
        tree = {"okf_path": "a.md"}
        orig = ma._read_section_text
        ma._read_section_text = lambda *a, **k: "본문 발췌"
        try:
            out = ma._extract_from_tree(tree, "구리", "생산량", ("Production",), _FakeLLM(raise_error=True), max_chars=1000)
        finally:
            ma._read_section_text = orig
        self.assertFalse(out.found)

    def test_empty_excerpt_short_circuits_without_llm_call(self):
        tree = {"okf_path": "a.md"}
        orig = ma._read_section_text
        ma._read_section_text = lambda *a, **k: ""
        fake = _FakeLLM()
        try:
            out = ma._extract_from_tree(tree, "구리", "생산량", ("Production",), fake, max_chars=1000)
        finally:
            ma._read_section_text = orig
        self.assertFalse(out.found)
        self.assertEqual(fake.calls, 0)

    def test_valid_llm_output_passed_through(self):
        tree = {"okf_path": "a.md"}
        expected = ma.DocExtraction(found=True, mines=[ma.MineRecord(mine="Foo", values=[])])
        orig = ma._read_section_text
        ma._read_section_text = lambda *a, **k: "본문 발췌"
        try:
            out = ma._extract_from_tree(tree, "구리", "생산량", ("Production",), _FakeLLM(output=expected), max_chars=1000)
        finally:
            ma._read_section_text = orig
        self.assertTrue(out.found)
        self.assertEqual(out.mines[0].mine, "Foo")


if __name__ == "__main__":
    unittest.main()
