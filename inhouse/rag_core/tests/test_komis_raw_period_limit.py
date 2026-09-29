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
from rag_core.retrieval.access import PRIVATE_ONLY_KOMIS_PAGES  # noqa: E402


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
    def test_composite_index_is_public_but_market_and_supply_indicators_remain_private(self):
        self.assertNotIn("indicator_composite", PRIVATE_ONLY_KOMIS_PAGES)
        self.assertEqual(PRIVATE_ONLY_KOMIS_PAGES, {"indicator_market", "indicator_supply"})

    def test_verified_public_composite_index_evidence_matches_requested_variant(self):
        call = graph.ActionCall(
            requirement_id="index", action_id="indicator.series",
            slots=graph.ActionSlots(indicator="composite_index", indicator_variant="composite"),
        )
        evidence = graph.Evidence(
            kind="structured", source="public.KO_MNRL_SNTHS_INDX", section="KOMIS 원천",
            menu_page_id="indicator_composite", caveat=None,
            text="| indx_se_cd | crtr_ymd | indx |\n|---|---|---:|\n| HI001 | 2026-09-08 | 3651.45 |",
        )

        self.assertTrue(graph._is_verified_composite_index_evidence([evidence], call))
        self.assertFalse(graph._is_verified_composite_index_evidence(
            [graph.Evidence(**{**evidence.__dict__, "text": evidence.text.replace("HI001", "HI002")})], call,
        ))

    def test_hhi_number_is_hidden_below_import_amount_floor(self):
        below = tools._concentration_metric_label("import_amount", 999_999.99, 2333.77, "formula")
        at_floor = tools._concentration_metric_label("import_amount", 1_000_000, 2333.77, "formula")
        missing_total = tools._concentration_metric_label("import_amount", None, 2333.77, "formula")
        self.assertNotIn("2333.77", below)
        self.assertIn("기준 미달", below)
        self.assertIn("HHI=2333.77", at_floor)
        self.assertNotIn("2333.77", missing_total)

    def test_composite_trust_requires_exact_table_columns_and_codes(self):
        registry = _Registry()

        class CompositeRepository:
            def fetch(self, _request):
                return [RawDataset(
                    source_table="KO_MNRL_SNTHS_INDX",
                    columns=["indx_se_cd", "crtr_ymd", "indx"], row_count=1,
                    rows=[{"indx_se_cd": "HI001", "crtr_ymd": "20260905", "indx": 3651.45}],
                )]

        with patch.object(tools, "KomisRawDataRepository", CompositeRepository):
            tools.register_common_tools(
                registry, private_only_pages=PRIVATE_ONLY_KOMIS_PAGES,
                trusted_komis_pages=frozenset({"indicator_composite"}),
            )
            result = registry.functions["komis_raw_lookup"](
                "indicator_composite", index_type_code="HI001",
            )
        self.assertEqual(result["warnings"], [])
        self.assertIsNone(result["evidence"][0]["caveat"])

        blocked = registry.functions["komis_raw_lookup"]("indicator_market")
        self.assertEqual(blocked["evidence"], [])
        self.assertIn("private 전용", blocked["warnings"][0])

    def test_empty_composite_query_reports_hi001_available_period(self):
        registry = _Registry()

        class EmptyCompositeRepository:
            seen_bounds_filters = []

            def fetch(self, _request):
                return [RawDataset(
                    source_table="KO_MNRL_SNTHS_INDX",
                    columns=["indx_se_cd", "crtr_ymd", "indx"], row_count=0, rows=[],
                )]

            def fetch_complete(self, request):
                return self.fetch(request)

            def resolve_period_bounds(self, page_id, *, index_type_code=None, **_kwargs):
                self.seen_bounds_filters.append((page_id, index_type_code))
                return "20110103", "20260925", "day"

        with patch.object(tools, "KomisRawDataRepository", EmptyCompositeRepository):
            tools.register_common_tools(
                registry, trusted_komis_pages=frozenset({"indicator_composite"}),
            )
            for index_code in ("HI001", "HI002", "HI003"):
                result = registry.functions["komis_raw_lookup"](
                    "indicator_composite", index_type_code=index_code,
                    start_period="20100101", end_period="20101231",
                )
                self.assertEqual(result["evidence"], [])
                self.assertEqual(
                    result["warnings"],
                    ["지표 산출 가능 기간은 2011.01.03~2026.09.25입니다."],
                )

        self.assertEqual(
            EmptyCompositeRepository.seen_bounds_filters,
            [("indicator_composite", code) for code in ("HI001", "HI002", "HI003")],
        )

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

    def test_strategic_overview_hides_price_when_provenance_lookup_fails(self):
        """원천 상태를 증명할 수 없는 가격을 실제/더미 값으로 노출하지 않는다."""
        class ProvenanceUnavailableRepository:
            def fetch_strategic_price_overview(self, *, members, as_of_date):
                return RawDataset(
                    source_table="KO_MNRL_PRC", columns=["mineral", "price"], row_count=1,
                    rows=[{
                        "strategic_group": "strategic_six", "mineral": "니켈",
                        "price_criterion_serial": 502, "price_date": "20260908", "price": 15000,
                        "price_criterion": "LME CASH", "price_currency_code": "PR001",
                        "weight_unit_code": "WT002", "source_menu": "price_base_metals",
                        "row_status": "available",
                    }], metadata={"missing_minerals": []},
                )

            def price_criteria_have_dummy_rows(self, _serials):
                raise tools.RawDataAccessError("fixture provenance unavailable")

        registry = _Registry()
        members = [SimpleNamespace(group="strategic_six", group_label="6대 전략광종",
                                   label="니켈", price_mineral="니켈")]
        with patch.object(tools, "KomisRawDataRepository", ProvenanceUnavailableRepository), \
             patch.object(tools, "load_strategic_price_members", return_value=members):
            tools.register_common_tools(registry)
            result = registry.functions["komis_strategic_price_overview"](["strategic_six"])

        self.assertEqual(result["warnings"], ["source_unavailable:strategic_price_provenance_unverified"])
        self.assertEqual(result["evidence"], [])


if __name__ == "__main__":
    unittest.main()
