# -*- coding: utf-8 -*-
"""가격 원천 내부 코드가 본문과 인용 메타데이터로 새지 않는지 검사한다."""
import unittest
from types import SimpleNamespace

from rag_core.ragkit import chatbot
from rag_core.ragkit.action_contract import ActionCall, ActionPlan, ActionSlots
from rag_core.retrieval.evidence import Evidence


class PriceUnitDisclosureTest(unittest.TestCase):
    def test_compound_raw_unit_keeps_criterion_and_hides_opaque_codes(self):
        unit = "가격기준=LME CASH; 통화코드=PR001; 중량단위코드=WT002"
        evidence = Evidence(
            kind="aggregated", source="public.KO_MNRL_PRC", section="가격 시계열", text="표",
            unit=unit, observed_period="2025-01-01~2025-12-31", action_id="price.series",
        )
        plan = ActionPlan(actions=[ActionCall(
            requirement_id="price", action_id="price.series", slots=ActionSlots(),
        )])

        disclosure = chatbot._price_unit_disclosure(
            f"가격 흐름입니다. 단위는 {unit}입니다. [1]", [evidence],
        )
        scope = chatbot._price_series_scope_answer([evidence], plan)
        citations = chatbot._citation_sources({1}, [evidence])

        self.assertIn("가격기준=LME CASH", disclosure)
        self.assertNotIn("PR001", disclosure)
        self.assertNotIn("WT002", disclosure)
        assert scope is not None
        self.assertIn("가격 기준은 LME CASH, 통화 코드는 PR001, 단위 코드는 WT002입니다.", scope[0])
        self.assertNotIn("관측 기간", scope[0])
        self.assertNotIn("PR001;", scope[0])
        self.assertNotIn("WT002;", scope[0])
        self.assertEqual(citations[0]["unit"], "가격기준=LME CASH")

    def test_verified_human_units_are_preserved(self):
        unit = "가격기준=LME CASH; 통화=USD; 중량=톤"
        evidence = SimpleNamespace(
            kind="aggregated", source="price", section="series", as_of=None, unit=unit,
            requirement_id=None, action_id="price.series", source_id=None, observed_period=None,
            menu_page_id=None,
        )
        disclosure = chatbot._price_unit_disclosure("가격 흐름입니다. [1]", [evidence])
        citations = chatbot._citation_sources({1}, [evidence])

        self.assertIn(unit, disclosure)
        self.assertEqual(citations[0]["unit"], unit)


if __name__ == "__main__":
    unittest.main()
