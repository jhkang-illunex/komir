"""광산 순위의 기간·국가·증가량 계약."""
from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from rag_core.ragkit.action_contract import ActionCall, ActionPlan, ActionSlots, Period, validate_action_plan
from rag_core.ragkit.chatbot_graph import _is_complete_mine_rank_increase, _is_complete_mine_rank_yoy, _route_from_action_call
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

    def test_level_top_n_supports_production_and_reserves(self):
        rows = [observation("A", 2025, 30), observation("B", 2025, 20),
                observation("C", 2025, 40, basis="ore")]
        production = rank_observations(rows, agg="rank", target_basis="metal", top_n=1)
        reserves = rank_observations(rows, agg="rank", target_basis="ore", top_n=1)
        self.assertEqual([row.mine_name for row in production.ranked], ["A"])
        self.assertEqual([row.mine_name for row in reserves.ranked], ["C"])

    def test_yoy_increase_and_decrease_require_consecutive_annual_years(self):
        rows = [
            observation("A", 2023, 10), observation("A", 2024, 20), observation("A", 2025, 18),
            observation("B", 2024, 30), observation("B", 2025, 5),
            observation("C", 2022, 1), observation("C", 2025, 100),
            observation("D", 2024, 10), observation("D", 2025, 15),
        ]
        increased = rank_observations(rows, agg="rank", target_basis="metal",
                                       order="yoy_increase", top_n=10)
        decreased = rank_observations(rows, agg="rank", target_basis="metal",
                                       order="yoy_decrease", top_n=10)
        self.assertEqual([(row.mine_name, row.start_year, row.year, row.increase_tonnes)
                          for row in increased.ranked], [("D", 2024, 2025, 5)])
        self.assertEqual([(row.mine_name, row.start_year, row.year, row.increase_tonnes)
                          for row in decreased.ranked],
                         [("B", 2024, 2025, -25), ("A", 2024, 2025, -2)])
        self.assertTrue(any("연속된 두 연도" in note for note in decreased.excluded_notes))

    def test_yoy_reserves_both_directions_and_requested_end_year(self):
        rows = [
            observation("A", 2023, 100, basis="ore"), observation("A", 2024, 150, basis="ore"),
            observation("A", 2025, 120, basis="ore"),
            observation("B", 2024, 90, basis="ore"), observation("B", 2025, 110, basis="ore"),
        ]
        increase = rank_observations(rows, agg="rank", target_basis="ore",
                                      order="yoy_increase", year=2024, top_n=5)
        decrease = rank_observations(rows, agg="rank", target_basis="ore",
                                      order="yoy_decrease", year=2025, top_n=5)
        self.assertEqual([(row.mine_name, row.increase_tonnes) for row in increase.ranked], [("A", 50)])
        self.assertEqual([(row.mine_name, row.increase_tonnes) for row in decrease.ranked], [("A", -30)])

    def test_yoy_intent_slots_and_route(self):
        from rag_core.ragkit.action_contract import IntentCall, IntentPlan, _normalize_mine_intent
        plan = IntentPlan(requirements=[IntentCall(
            requirement_id="m1", intent="mine_rank", role="data",
            slots=ActionSlots(mineral="구리", country_scope="중국", top_n=10),
        )])
        normalized = _normalize_mine_intent(plan, "최근 YoY 매장량 축소 Top 10")
        slots = normalized.requirements[0].slots
        self.assertEqual((slots.mine_metric, slots.mine_order, slots.top_n),
                         ("reserves", "yoy_decrease", 10))
        production_plan = IntentPlan(requirements=[IntentCall(
            requirement_id="m2", intent="mine_rank", role="data", slots=ActionSlots(),
        )])
        production_slots = _normalize_mine_intent(
            production_plan, "최근 YoY 산출량 증가 Top 7",
        ).requirements[0].slots
        self.assertEqual((production_slots.mine_metric, production_slots.mine_order,
                          production_slots.top_n), ("production", "yoy_increase", 7))
        action = ActionCall(requirement_id="m1", action_id="mine.rank", slots=slots)
        self.assertTrue(validate_action_plan(ActionPlan(actions=[action])).approved)
        route = _route_from_action_call(action, "최근 YoY 매장량 축소 Top 10")
        self.assertEqual((route.mine_metric, route.mine_order, route.mine_top_n),
                         ("매장량", "yoy_decrease", 10))

    def test_yoy_evidence_requires_consecutive_years_and_correct_direction(self):
        call = ActionCall(
            requirement_id="m1", action_id="mine.rank",
            slots=ActionSlots(mine_metric="reserves", mine_order="yoy_decrease", top_n=10),
        )
        text = """기간 검증: 아래 YoY 순위는 같은 기준의 연속된 두 연도 관측값만 비교했습니다.
| 순위 | 광산 | 광종 | 국가 | 시작연도 | 시작값(t) | 끝연도 | 끝값(t) | 감소량(t) | basis | 출처 |
|---|---|---|---|---:|---:|---:|---:|---:|---|---|
| 1 | Mine A | 구리 | Chile | 2024 | 150 | 2025 | 120 | 30 | ore | 광산자료/동_구리/a.md |
"""
        evidence = [Evidence(kind="aggregated", source="광산자료/동_구리",
                             section="구리 매장량 rank", text=text, unit="t")]
        self.assertTrue(_is_complete_mine_rank_yoy(evidence, call))
        evidence[0].text = text.replace("2024 | 150", "2023 | 150")
        self.assertFalse(_is_complete_mine_rank_yoy(evidence, call))
        evidence[0].text = text.replace("120 | 30", "160 | 30")
        self.assertFalse(_is_complete_mine_rank_yoy(evidence, call))

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
        rio_lines = rio.read_text(encoding="utf-8").splitlines()
        header_line = next(
            index for index, line in enumerate(rio_lines)
            if "Quarter Full Year" in line
        )
        self.assertTrue(mine_aggregate._has_ambiguous_quarter_annual_header(
            "\n".join(rio_lines[header_line:header_line + 20])
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
