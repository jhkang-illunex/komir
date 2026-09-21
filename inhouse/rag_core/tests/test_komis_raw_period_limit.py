# -*- coding: utf-8 -*-
"""원천 조회의 명시 기간과 환경변수 기본 상한 회귀 검증."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common.komis_raw import RawDataset  # noqa: E402
from rag_core.ragkit import _mcp_tools_common as tools  # noqa: E402
from rag_core.ragkit import chatbot_graph as graph  # noqa: E402
from rag_core.ragkit import mcp_client  # noqa: E402


class _Registry:
    def __init__(self):
        self.functions = {}

    def tool(self):
        def register(func):
            self.functions[func.__name__] = func
            return func
        return register


class _Repository:
    requests = []

    @staticmethod
    def _dataset(request, count, complete=False):
        return [RawDataset(
            source_table="KO_MNRL_PRC", columns=["crtr_ymd", "price"], row_count=count,
            rows=[{"crtr_ymd": "20260908", "price": i} for i in range(count)],
            metadata={"period_range_complete": complete},
        )]

    def fetch(self, request):
        self.requests.append(("limited", request))
        return self._dataset(request, request.limit)

    def fetch_complete(self, request):
        self.requests.append(("complete", request))
        return self._dataset(request, 130, complete=True)

    def resolve_price_criterion_metadata(self, serial):
        return ("LME CASH", "PR001", "WT002")

    def price_criteria_have_dummy_rows(self, serials):
        return {int(serial): False for serial in serials}


class PeriodLimitTest(unittest.TestCase):
    def test_explicit_period_returns_every_row_and_no_period_uses_env_cap(self):
        registry = _Registry()
        _Repository.requests = []
        with patch.object(tools, "get_settings", return_value=SimpleNamespace(KOMIS_RAW_MAX_TIMESTAMPS=60)), \
             patch.object(tools, "KomisRawDataRepository", _Repository):
            tools.register_common_tools(registry)
            lookup = registry.functions["komis_raw_lookup"]
            no_period = lookup("price_base_metals", price_criterion_serial=502, limit=200)
            with_period = lookup("price_base_metals", price_criterion_serial=502,
                                 start_period="20250901", end_period="20260901")
            start_only = lookup("price_base_metals", price_criterion_serial=502,
                                start_period="20250901")

        self.assertEqual([kind for kind, _ in _Repository.requests],
                         ["limited", "complete", "complete"])
        self.assertEqual(_Repository.requests[0][1].limit, 60)
        self.assertEqual(len(no_period["evidence"][0]["text"].splitlines()) - 2, 60)
        self.assertEqual(len(with_period["evidence"][0]["text"].splitlines()) - 2, 130)
        self.assertEqual(len(start_only["evidence"][0]["text"].splitlines()) - 2, 130)
        self.assertIn("지정 기간 내 관측 130건 전체", with_period["evidence"][0]["as_of"])
        self.assertIn("최신순 60건만", no_period["evidence"][0]["as_of"])

    def test_question_period_repairs_missing_llm_route_field(self):
        route = graph.RetrievalRoute(resolved_query="니켈 최근 1년 가격 추이",
                                     use_structured=False, use_dense=False, use_pageindex=False,
                                     use_komis_raw=True, komis_topic="price",
                                     komis_mineral_name="니켈")
        fixed = graph._apply_aggregate_route({"question": route.resolved_query}, route)
        self.assertEqual(fixed.komis_relative_months, 12)
        self.assertIsNone(fixed.komis_start_period)
        self.assertIsNone(graph._apply_aggregate_route(
            {"question": "니켈 가격 추이"}, route).komis_relative_months)

    def test_client_does_not_override_env_default_with_five_rows(self):
        session = object.__new__(mcp_client._ProfileSession)
        with patch.object(mcp_client._ProfileSession, "_call",
                          return_value={"evidence": [], "warnings": []}) as call:
            session.call_komis_raw_lookup("price_base_metals")
        self.assertNotIn("limit", call.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
