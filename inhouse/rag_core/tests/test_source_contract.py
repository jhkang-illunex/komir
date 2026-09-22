# -*- coding: utf-8 -*-
"""문서 동향과 미연결 예측 수치 원천의 사전 차단 경계를 검사한다."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rag_core.ragkit.source_contract import (  # noqa: E402
    RequestRequirement, RequirementPlan, assess_requirement_plan,
)


class SourceContractTest(unittest.TestCase):
    def test_documented_demand_trend_is_not_blocked_as_demand_forecast(self):
        assessment = assess_requirement_plan(RequirementPlan(requirements=[
            RequestRequirement(
                clause="6개월 이내 리튬 수요 관련 이슈", intent="document_content",
                source_domain="unavailable_demand_forecast", mineral="리튬",
            ),
        ]))
        self.assertFalse(assessment.blocked)

    def test_numeric_demand_forecast_remains_blocked(self):
        assessment = assess_requirement_plan(RequirementPlan(requirements=[
            RequestRequirement(
                clause="리튬 수요 예측", intent="numeric_result",
                source_domain="unavailable_demand_forecast", mineral="리튬",
            ),
        ]))
        self.assertTrue(assessment.blocked)
        self.assertEqual(assessment.unavailable_domains, ("unavailable_demand_forecast",))


if __name__ == "__main__":
    unittest.main()
