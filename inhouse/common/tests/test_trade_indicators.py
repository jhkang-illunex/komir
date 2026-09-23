import unittest

from common.trade_indicators import RcaInputs, TiiInputs, TradeIndicatorInputError, calculate_rca, calculate_tii


class TradeIndicatorFormulaTest(unittest.TestCase):
    def test_rca_formula_is_ready_for_global_source_wiring(self):
        self.assertEqual(calculate_rca(RcaInputs(20, 100, 100, 1000)), 2.0)

    def test_tii_formula_is_ready_for_global_source_wiring(self):
        self.assertEqual(calculate_tii(TiiInputs(20, 100, 50, 1000)), 4.0)

    def test_zero_denominator_is_not_calculated(self):
        with self.assertRaises(TradeIndicatorInputError):
            calculate_rca(RcaInputs(1, 0, 1, 1))


if __name__ == "__main__":
    unittest.main()
