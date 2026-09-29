import unittest

from rag_core.ragkit.action_contract import ActionCall, ActionPlan, ActionSlots, Period
from rag_core.ragkit.renderers.trade import render_import_dependency_high
from rag_core.retrieval.evidence import Evidence


class ImportDependencyRendererTest(unittest.TestCase):
    def test_uses_strictly_greater_than_configured_threshold(self):
        plan = ActionPlan(actions=[
            ActionCall(requirement_id="import_dependency_니켈", action_id="trade.country_rank",
                       slots=ActionSlots(mineral="니켈", metric="import_amount", top_n=1,
                                         period=Period(kind="trailing_months", trailing_months=12))),
            ActionCall(requirement_id="import_dependency_리튬", action_id="trade.country_rank",
                       slots=ActionSlots(mineral="리튬", metric="import_amount", top_n=1,
                                         period=Period(kind="trailing_months", trailing_months=12))),
        ])
        evidence = [
            Evidence(kind="aggregated", source="KOMIS", section="수입", requirement_id="import_dependency_니켈",
                     text="| country | share_pct |\n| --- | --- |\n| 인도네시아 | 27.00 |"),
            Evidence(kind="aggregated", source="KOMIS", section="수입", requirement_id="import_dependency_리튬",
                     text="| country | share_pct |\n| --- | --- |\n| 중국 | 27.01 |"),
        ]
        result = render_import_dependency_high(evidence, plan)
        assert result is not None
        self.assertNotIn("니켈(인도네시아", result[0])
        self.assertIn("리튬(중국 27.01%)", result[0])
        self.assertIn("확인된 수입 자료 기준", result[0])
        self.assertNotIn("최근 12개월", result[0])
        self.assertIn("가격 전망 원천", result[0])


if __name__ == "__main__":
    unittest.main()
