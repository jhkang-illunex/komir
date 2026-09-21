"""광산 순위의 기간·국가·증가량 계약."""
from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from rag_core.ragkit.action_contract import ActionCall, ActionPlan, ActionSlots, Period, validate_action_plan
from rag_core.ragkit.chatbot_graph import _is_complete_mine_rank_increase, _route_from_action_call
from rag_core.retrieval import mine_aggregate
from rag_core.retrieval.evidence import Evidence
from rag_core.retrieval.mine_aggregate import DocExtraction, MineRecord, MineYearValue, Observation, rank_observations


def observation(name: str, year: int, value: float, *, country: str = "중국",
                mineral: str = "리튬", basis: str = "metal") -> Observation:
    return Observation(
        mine_key=name.lower(), mine_name=name, company=None, country=country,
        mineral=mineral, year=year, value_raw=value, unit_raw="t", basis=basis,
        value_tonnes=value, source_okf_path=f"{name}-{year}.md", source_resource="report.pdf",
    )


class MineRankingActionTest(unittest.TestCase):
    def test_recent_years_override_fabricated_range_for_mine_intent(self):
        from rag_core.ragkit.action_contract import IntentCall, IntentPlan, _normalize_mine_intent
        plan = IntentPlan(requirements=[IntentCall(requirement_id="m1", intent="mine_rank", role="data",
                                                 slots=ActionSlots(mine_metric="reserves",
                                                                   period=Period(kind="range", start="2019", end="2024")))])
        normalized = _normalize_mine_intent(plan, "최근 5년 이내 매장량이 가장 많은 광산 5개")
        slots = normalized.requirements[0].slots
        self.assertEqual((slots.period.kind, slots.period.trailing_months, slots.mine_order),
                         ("trailing_months", 60, "level"))

    def test_recent_reserves_use_latest_snapshot_and_exclude_old_years(self):
        current = date.today().year
        rows = [
            observation("A", current - 5, 1000),
            observation("A", current - 2, 90),
            observation("A", current - 1, 120),
            observation("B", current - 1, 110),
            observation("C", current - 6, 9000),
        ]
        result = rank_observations(rows, agg="rank", target_basis="metal",
                                   since_year=current - 4, top_n=5)
        self.assertEqual([(r.mine_name, r.value_tonnes) for r in result.ranked],
                         [("A", 120), ("B", 110)])

    def test_reserve_basis_and_known_mine_aliases(self):
        from rag_core.retrieval.mine_aggregate import _normalize_mine_name, default_basis
        self.assertEqual(default_basis("매장량"), "ore")
        self.assertEqual(_normalize_mine_name("Moblan Lithium Project"), _normalize_mine_name("Moblan"))
        self.assertEqual(_normalize_mine_name("NAL"), _normalize_mine_name("North American Lithium"))

    def test_three_year_increase_needs_two_observed_years_and_same_basis(self):
        current = date.today().year
        rows = [
            observation("A", current - 2, 10), observation("A", current - 1, 30),
            observation("B", current - 2, 30), observation("B", current - 1, 35),
            observation("C", current - 1, 100),
            observation("D", current - 2, 20, basis="ore"),
            observation("D", current - 1, 80, basis="ore"),
        ]
        result = rank_observations(rows, agg="rank", target_basis="metal",
                                   since_year=current - 2, order="increase", top_n=5)
        self.assertEqual([(r.mine_name, r.increase_tonnes) for r in result.ranked],
                         [("A", 20), ("B", 5)])
        self.assertEqual((result.ranked[0].start_year, result.ranked[0].year),
                         (current - 2, current - 1))

    def test_increase_uses_annual_values_not_quarter_and_annual_mixed_columns(self):
        rows = [
            Observation("oyu", "Oyu Tolgoi", None, "Mongolia", "구리", 2024,
                        43_800, "t", "metal", 43_800, "rio.md", "rio", period_kind="quarter"),
            Observation("oyu", "Oyu Tolgoi", None, "Mongolia", "구리", 2024,
                        141_900, "t", "metal", 141_900, "rio.md", "rio", period_kind="annual"),
            Observation("oyu", "Oyu Tolgoi", None, "Mongolia", "구리", 2025,
                        227_800, "t", "metal", 227_800, "rio.md", "rio", period_kind="annual"),
        ]
        result = rank_observations(rows, agg="rank", target_basis="metal", order="increase", top_n=5)
        self.assertEqual(len(result.ranked), 1)
        self.assertEqual((result.ranked[0].start_year, result.ranked[0].year,
                          result.ranked[0].increase_tonnes), (2024, 2025, 85_900))

    def test_collapsed_quarter_and_annual_header_is_excluded_from_increase(self):
        self.assertTrue(mine_aggregate._has_ambiguous_quarter_annual_header(
            "Q4 2024 Q1 2025 Q2 2025 Q3 2025 Q4 2025 2024 2025"
        ))
        self.assertFalse(mine_aggregate._has_ambiguous_quarter_annual_header(
            "2024 Annual production 141.9; 2025 Annual production 227.8"
        ))
        rio = Path(mine_aggregate.pageindex.OKF_DOCUMENTS_ROOT) / "광산자료/동_구리/Cu_Oyu_Tolgoi_Rio_Tinto.md"
        self.assertTrue(mine_aggregate._has_ambiguous_quarter_annual_header(
            "\n".join(rio.read_text(encoding="utf-8").splitlines()[891:914])
        ))

    def test_china_filter_does_not_use_company_nationality_or_unknown_country(self):
        current = date.today().year
        rows = [observation("A", current - 1, 5, country="China"),
                observation("B", current - 1, 90, country="Chile"),
                observation("C", current - 1, 100, country="")]
        result = rank_observations(rows, agg="max", target_basis="metal", country="중국")
        self.assertEqual([r.mine_name for r in result.ranked], ["A"])

    def test_action_projects_period_country_and_ranking_metric(self):
        call = ActionCall(
            requirement_id="mine_1", action_id="mine.rank",
            slots=ActionSlots(mineral="구리", mine_metric="production", mine_order="increase",
                              period=Period(kind="trailing_months", trailing_months=36),
                              country_scope="중국", top_n=5),
        )
        self.assertTrue(validate_action_plan(ActionPlan(actions=[call])).approved)
        route = _route_from_action_call(call, "중국 구리 광산 생산량 증가 순위")
        self.assertTrue(route.use_mine_aggregate)
        self.assertEqual((route.mine_metric, route.mine_order, route.mine_country, route.mine_top_n),
                         ("생산량", "increase", "중국", 5))
        self.assertEqual(route.mine_since_year, date.today().year - 2)

    def test_complete_annual_increase_table_bypasses_advisor_only_when_all_rows_are_valid(self):
        call = ActionCall(
            requirement_id="mine_1", action_id="mine.rank",
            slots=ActionSlots(mine_metric="production", mine_order="increase", top_n=2),
        )
        text = """기간 검증: 아래 증가 순위의 각 행은 원문에서 연간(annual/FY/Year/연간) 생산 실적으로 확인된 두 연도만 비교했습니다.
| 순위 | 광산 | 광종 | 국가 | 시작연도 | 시작값(t) | 끝연도 | 끝값(t) | 증가량(t) | basis | 출처 |
|---|---|---|---:|---:|---:|---:|---:|---:|---|---|
| 1 | Mine A | 구리 | Chile | 2024 | 100 | 2025 | 180 | 80 | metal | 광산자료/동_구리/a.md |
| 2 | Mine B | 구리 | Chile | 2024 | 200 | 2025 | 250 | 50 | metal | 광산자료/동_구리/b.md |
"""
        evidence = [Evidence(kind="aggregated", source="광산자료/동_구리", section="구리 생산량 rank", text=text, unit="t")]
        self.assertTrue(_is_complete_mine_rank_increase(evidence, call))
        invalid = Evidence(kind="aggregated", source="광산자료/동_구리", section="구리 생산량 rank",
                           text=text.replace("| 2 | Mine B", "| 3 | Mine B"), unit="t")
        self.assertFalse(_is_complete_mine_rank_increase([invalid], call))

    def test_aggregate_uses_country_and_reports_missing_source_without_empty_rank(self):
        year = date.today().year - 1
        tree = {"okf_path": "광산자료/리튬/test.md", "resource": "report.pdf"}
        extracted = DocExtraction(found=True, mines=[
            MineRecord(mine="Zabuye", country="China", values=[MineYearValue(year=year, value=12, unit="t", basis="metal")]),
            MineRecord(mine="Other", country="Chile", values=[MineYearValue(year=year, value=90, unit="t", basis="metal")]),
        ])
        with patch.object(mine_aggregate.pageindex, "load_trees", return_value=[tree]), \
             patch.object(mine_aggregate, "_run_extractions", return_value=[(tree, extracted)]), \
             patch.object(mine_aggregate, "get_settings") as settings:
            settings.return_value.LLM_CONCURRENCY = 1
            evidence, warnings = mine_aggregate.aggregate_mine_metric(
                "리튬", "생산량", "max", country="중국", since_year=year, llm=object(),
            )
            self.assertEqual(warnings, [])
            self.assertIn("Zabuye", evidence[0].text)
            self.assertNotIn("Other", evidence[0].text)
            missing, warnings = mine_aggregate.aggregate_mine_metric(
                "리튬", "생산량", "max", country="호주", since_year=year, llm=object(),
            )
            self.assertEqual(missing, [])
            self.assertTrue(warnings[0].startswith("source_unavailable:mine_no_comparable_values"))


if __name__ == "__main__":
    unittest.main()
