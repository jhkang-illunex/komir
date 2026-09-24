# -*- coding: utf-8 -*-
"""등록되지 않은 메뉴를 추측 추천하지 않는 정책 회귀 테스트."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.intent import is_unverified_import_demand_forecast_menu  # noqa: E402
from app.page_recommend.renderer import render_not_found  # noqa: E402


class UnverifiedImportDemandForecastMenuTest(unittest.TestCase):
    def test_import_demand_forecast_uses_not_found_policy(self):
        self.assertTrue(is_unverified_import_demand_forecast_menu(
            "리튬 수입수요 예측은 어느 메뉴에서 볼 수 있습니까?"
        ))
        self.assertFalse(is_unverified_import_demand_forecast_menu(
            "리튬 수입수요 예측값을 알려줘"
        ))
        self.assertEqual(
            render_not_found(),
            "요청하신 메뉴 경로를 확인하지 못했습니다. 상단 전체메뉴에서 확인해 주십시오.",
        )

    def test_adjacent_registered_features_do_not_trigger_the_policy(self):
        self.assertFalse(is_unverified_import_demand_forecast_menu("리튬 가격예측은 어디서 보나요?"))
        self.assertFalse(is_unverified_import_demand_forecast_menu("리튬 수급동향지표를 보여줘"))


if __name__ == "__main__":
    unittest.main()
