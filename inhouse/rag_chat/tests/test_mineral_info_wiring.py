# -*- coding: utf-8 -*-
"""광물정보 YAML adapter의 문형·원천 회귀 테스트."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag_core.ragkit.action_contract import extract_action_plan  # noqa: E402
from rag_core.ragkit.chatbot_graph import _route_from_action_call  # noqa: E402
from rag_core.ragkit.renderers.mineral_info import render_mineral_info  # noqa: E402
from rag_core.retrieval.mineral_info import fetch_mineral_info_evidence  # noqa: E402


class MineralInfoWiringTest(unittest.TestCase):
    def _plan(self, question):
        plan = extract_action_plan(question, llm=None)
        self.assertEqual(len(plan.actions), 1)
        self.assertEqual(plan.actions[0].requirement_id, "mineral_info")
        return plan

    def test_copper_and_nickel_basic_property_questions_route_to_adapter(self):
        for question, mineral in (("구리는 어떤 광물인가요?", "구리"), ("니켈은 어떤 특성이 있나요?", "니켈")):
            with self.subTest(question=question):
                plan = self._plan(question)
                self.assertEqual(plan.actions[0].slots.mineral, mineral)
                self.assertTrue(_route_from_action_call(plan.actions[0], question).use_mineral_info)

    def test_manganese_yaml_has_uses_properties_and_ores(self):
        evidence, warnings = fetch_mineral_info_evidence("망간")
        self.assertEqual(warnings, [])
        self.assertEqual(len(evidence), 1)
        self.assertIn("major_ores", evidence[0].text)

    def test_manganese_ore_uses_dedicated_output_contract(self):
        plan = self._plan("망간 주요 광석 종류는?")
        self.assertTrue(_route_from_action_call(plan.actions[0], "망간 주요 광석 종류는?").use_mineral_info)
        evidence, warnings = fetch_mineral_info_evidence("망간")
        self.assertEqual(warnings, [])
        # graph는 adapter 결과에 현재 Action 식별자를 부여한 뒤 renderer를 호출한다.
        evidence[0].action_id = plan.actions[0].action_id
        rendered = render_mineral_info(evidence, plan)
        self.assertIsNotNone(rendered)
        answer, _ = rendered
        self.assertEqual(answer, "망간의 주요 광석은 파이롤루사이트(pyrolusite, MnO₂), 로도크로사이트(rhodochrosite, MnCO₃)입니다.")

    def test_basic_property_renderer_uses_correct_korean_topic_particle(self):
        plan = self._plan("구리는 어떤 광물인가요?")
        evidence, warnings = fetch_mineral_info_evidence("구리")
        self.assertEqual(warnings, [])
        evidence[0].action_id = plan.actions[0].action_id
        answer, _ = render_mineral_info(evidence, plan)
        self.assertTrue(answer.startswith("구리는 원소기호 Cu"))


if __name__ == "__main__":
    unittest.main()
