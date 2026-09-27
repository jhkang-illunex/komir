# -*- coding: utf-8 -*-
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rag_core.ragkit.data_source_policy import (  # noqa: E402
    DataSourcePolicy,
    allows_result,
    is_allowed_dummy,
    policy_for_data_source,
)


class DataSourcePolicyTest(unittest.TestCase):
    def test_komis_sample_is_allowed_without_dummy_status(self):
        self.assertEqual(policy_for_data_source("KOMIS_SAMPLE"), DataSourcePolicy.ALLOW)
        self.assertTrue(allows_result("KOMIS_SAMPLE"))
        self.assertFalse(is_allowed_dummy("KOMIS_SAMPLE"))

    def test_dev_dummy_has_explicit_allow_dummy_policy(self):
        self.assertEqual(policy_for_data_source("DEV_DUMMY"), DataSourcePolicy.ALLOW_DUMMY)
        self.assertTrue(allows_result("DEV_DUMMY"))
        self.assertTrue(is_allowed_dummy("DEV_DUMMY"))

    def test_missing_or_unknown_source_is_not_implicitly_allowed(self):
        for source in (None, "", "UNVERIFIED", "OTHER_SOURCE"):
            with self.subTest(source=source):
                self.assertEqual(policy_for_data_source(source), DataSourcePolicy.SOURCE_UNAVAILABLE)
                self.assertFalse(allows_result(source))
                self.assertFalse(is_allowed_dummy(source))
