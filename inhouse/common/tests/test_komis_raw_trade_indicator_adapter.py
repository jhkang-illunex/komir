# -*- coding: utf-8 -*-
"""RCA/TII 세계 분모 provider 주입 경계 회귀 검사."""
import unittest

from common.komis_raw import KomisRawDataRepository, RawDataAccessError
from common.trade_indicators import RcaInputs, TiiInputs


class KomisRawTradeIndicatorAdapterTest(unittest.TestCase):
    @staticmethod
    def _request(metric: str, **overrides):
        values = {
            "trade_metric": metric,
            "hs_codes": ["2603000000"],
            "reporter_country": "한국",
            "partner_country": "중국",
            "calendar_year": 2025,
        }
        values.update(overrides)
        return values

    def test_no_provider_remains_fail_closed(self):
        with self.assertRaises(RawDataAccessError):
            KomisRawDataRepository().fetch_trade_indicator(**self._request("rca"))

    def test_injected_rca_inputs_calculate_and_preserve_metadata(self):
        received = {}

        def provider(**kwargs):
            received.update(kwargs)
            return RcaInputs(20, 100, 100, 1000)

        dataset = KomisRawDataRepository(provider).fetch_trade_indicator(**self._request("rca"))
        self.assertEqual(received, self._request("rca"))
        self.assertEqual(dataset.rows[0]["rca"], 2.0)
        self.assertEqual(dataset.source_table, "GLOBAL_TRADE_DENOMINATOR")
        self.assertEqual(dataset.unit, "무차원")
        self.assertEqual(dataset.metadata["formula"], "(기준국 품목 수출액/기준국 총수출액)/(세계 품목 수출액/세계 총수출액)")
        self.assertEqual(dataset.metadata["hs_codes"], ["2603000000"])

    def test_injected_tii_inputs_calculate_and_preserve_metadata(self):
        dataset = KomisRawDataRepository(
            lambda **_kwargs: TiiInputs(20, 100, 50, 1000),
        ).fetch_trade_indicator(**self._request("tii"))
        self.assertEqual(dataset.rows[0]["tii"], 4.0)
        self.assertEqual(dataset.unit, "무차원")
        self.assertEqual(dataset.metadata["trade_metric"], "tii")
        self.assertEqual(dataset.metadata["reporter_country"], "한국")

    def test_invalid_provider_type_and_exception_fail_closed(self):
        for provider in (lambda **_kwargs: RcaInputs(1, 1, 1, 1), lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("offline"))):
            with self.subTest(provider=provider), self.assertRaises(RawDataAccessError):
                KomisRawDataRepository(provider).fetch_trade_indicator(**self._request("tii"))

    def test_missing_provider_inputs_do_not_call_provider(self):
        calls = []

        def provider(**kwargs):
            calls.append(kwargs)
            return TiiInputs(20, 100, 50, 1000)

        with self.assertRaises(RawDataAccessError):
            KomisRawDataRepository(provider).fetch_trade_indicator(**self._request("tii", partner_country=None))
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
