import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.routers.chat import _unsupported_mineral_in_plan  # noqa: E402
from rag_core.ragkit.action_contract import ActionCall, ActionPlan, ActionSlots  # noqa: E402


class _Resolver:
    def __init__(self, code):
        self.code = code
        self.calls = []

    def call_komis_resolve_mineral(self, name):
        self.calls.append(name)
        return {"mineral_code": self.code, "warnings": ([] if self.code else [f"'{name}'을(를) KOMIS 광종 목록(ai_mnrl_mst)에서 찾지 못했습니다."])}


class SlotMineralValidationTest(unittest.TestCase):
    def test_rdb_action_stops_unsupported_mineral_before_retrieval(self):
        plan = ActionPlan(actions=[ActionCall(requirement_id="p", action_id="price.series", slots=ActionSlots(mineral="가상광물"))])
        resolver = _Resolver(None)
        self.assertEqual(_unsupported_mineral_in_plan(plan, "public", session=resolver), "가상광물")
        self.assertEqual(resolver.calls, ["가상광물"])

    def test_document_action_does_not_require_komis_registration(self):
        plan = ActionPlan(actions=[ActionCall(requirement_id="d", action_id="document.retrieve", slots=ActionSlots(topic="가상광물 보고서"))])
        resolver = _Resolver(None)
        self.assertIsNone(_unsupported_mineral_in_plan(plan, "public", session=resolver))
        self.assertEqual(resolver.calls, [])


if __name__ == "__main__":
    unittest.main()
