import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rag_core.ragkit.action_contract import ActionCall, ActionPlan, ActionSlots  # noqa: E402
from rag_core.ragkit.action_results import ActionResult, RetrievalResult  # noqa: E402
from rag_core.ragkit.answer_composer import AnswerComposer  # noqa: E402
from rag_core.ragkit.answer_contracts import matching_contracts  # noqa: E402


class AnswerContractsTest(unittest.TestCase):
    def test_registry_has_all_requested_formats(self):
        self.assertEqual(
            {item.contract_id for item in matching_contracts(["price.series", "forecast.price"])},
            {"OC01", "OC02", "OC03"},
        )
        self.assertEqual(
            {item.contract_id for item in matching_contracts(["price.series", "resource.yoy"])},
            {"OC09"},
        )
        self.assertEqual(
            {item.contract_id for item in matching_contracts(
                ["price.series", "document.retrieve"], "니켈 가격 크게 오른 날 관련 뉴스 있어?")},
            {"QA01"},
        )

    def test_composer_injects_contract_without_inventing_values(self):
        plan = ActionPlan(actions=[
            ActionCall(requirement_id="price", action_id="price.series", slots=ActionSlots(mineral="리튬")),
            ActionCall(requirement_id="forecast", action_id="forecast.price", slots=ActionSlots(mineral="리튬")),
        ])
        result = RetrievalResult(
            action_plan=plan,
            action_results=[
                ActionResult("price", "price.series", plan.actions[0].slots, "success"),
                ActionResult("forecast", "forecast.price", plan.actions[1].slots, "source_unavailable"),
            ],
        )
        instruction = AnswerComposer().instruction(result)
        self.assertIn("OC01", instruction)
        self.assertIn("OC02", instruction)
        self.assertIn("OC03", instruction)
        self.assertIn("근거에 없는 수치", instruction)


if __name__ == "__main__":
    unittest.main()
