import unittest
from unittest.mock import patch

from rag_core.ragkit.action_contract import _latest_inventory_plan
from rag_core.ragkit.renderers.inventory import render_latest_inventory
from rag_core.retrieval.evidence import Evidence
from rag_core.retrieval.inventory import _monthly_last_rows, _period_bounds, fetch_inventory_evidence


class InventoryContractTests(unittest.TestCase):
    def test_period_bounds_are_typed_and_deterministic(self):
        start, end, is_series = _period_bounds({"kind": "trailing_months", "trailing_months": 12})
        self.assertTrue(is_series)
        self.assertRegex(start or "", r"^\d{8}$")
        self.assertRegex(end or "", r"^\d{8}$")

    def test_inventory_series_keeps_all_observations(self):
        class Cursor:
            def execute(self, query, params):
                self.query, self.params = query, params

            def fetchall(self):
                return [
                    ("20251001", "100", "LME CASH", "WT002", "니켈"),
                    ("20261001", "120", "LME CASH", "WT002", "니켈"),
                ]

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        class Connection:
            def __init__(self):
                self.cursor_obj = Cursor()

            def cursor(self):
                return self.cursor_obj

            def close(self):
                pass

        connection = Connection()
        with patch("rag_core.retrieval.inventory.pg_connect", return_value=connection):
            evidence, warnings = fetch_inventory_evidence(
                "니켈", period={"kind": "trailing_months", "trailing_months": 12},
                action_id="inventory.series",
            )
        self.assertEqual(warnings, [])
        self.assertEqual(len(evidence), 1)
        self.assertIn("2025-10", evidence[0].text)
        self.assertIn("2026-10", evidence[0].text)
        self.assertEqual(evidence[0].action_id, "inventory.series")

    def test_inventory_series_requires_bounded_period(self):
        evidence, warnings = fetch_inventory_evidence("니켈", action_id="inventory.series")
        self.assertEqual(evidence, [])
        self.assertEqual(warnings, ["inventory_series_period_required"])

    def test_inventory_series_uses_last_level_per_month_not_sum(self):
        rows = [
            ("20261001", "100", "LME CASH", "WT002", "니켈"),
            ("20261002", "120", "LME CASH", "WT002", "니켈"),
            ("20261008", "130", "LME CASH", "WT002", "니켈"),
        ]
        monthly = _monthly_last_rows(rows)
        self.assertEqual([row[0] for row in monthly], ["2026-10"])
        self.assertEqual([row[1] for row in monthly], ["130"])

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
        coded = Evidence(
            kind="structured", source="KOMIS", section="inventory", as_of="20260908",
            unit="재고기준=LME CASH",
            text=("| 기준일 | 광종 | 재고 종류 | 재고량 | 원시 단위 코드 |\n"
                  "|---|---|---|---:|---|\n| 20260908 | 니켈 | LME CASH | 272380 | WT002 |"),
            action_id="inventory.latest",
        )
        safe = render_latest_inventory([coded], plan)
        self.assertIn("2026-09-08 기준 니켈 LME CASH 재고량은 272380 톤입니다.", safe[0])
        self.assertNotIn("WT002", safe[0])
