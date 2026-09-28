import unittest

from rag_core.ragkit.action_contract import _latest_inventory_plan
from rag_core.ragkit.renderers.inventory import render_latest_inventory
from rag_core.retrieval.evidence import Evidence


class InventoryContractTests(unittest.TestCase):
    def test_lme_inventory_is_not_price_series(self):
        plan = _latest_inventory_plan("니켈 LME 재고량 알려줘")
        self.assertIsNotNone(plan)
        self.assertEqual(plan.actions[0].action_id, "inventory.latest")
        self.assertEqual(plan.actions[0].slots.mineral, "니켈")
        self.assertEqual(plan.actions[0].slots.price_basis, "LME")

    def test_renderer_preserves_inventory_type_and_value(self):
        plan = _latest_inventory_plan("니켈 LME 재고량 알려줘")
        evidence = Evidence(
            kind="structured", source="public.ko_mnrl_prc + public.ko_mnrl_prc_crtr",
            section="KOMIS 재고량 · 니켈", as_of="20260908", unit="재고기준=LME CASH",
            text="| 기준일 | 광종 | 재고 종류 | 재고량 |\n|---|---|---|---:|\n| 20260908 | 니켈 | LME CASH | 272380 |",
            action_id="inventory.latest",
        )
        answer = render_latest_inventory([evidence], plan)
        self.assertIsNotNone(answer)
        self.assertIn("LME CASH", answer[0])
        self.assertIn("272380", answer[0])
