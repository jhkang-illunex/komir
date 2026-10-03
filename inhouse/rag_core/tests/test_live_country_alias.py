"""Source alias ambiguity: one code across years is not multiple countries."""
import unittest
from inhouse.rag_core.tests.registered_step_helpers import execute_registered
from unittest.mock import patch

from inhouse.rag_core.ragkit import live_multihop as live
from inhouse.rag_core.ragkit.pipe_runtime import TypedResult, ResultStatus
from inhouse.rag_core.ragkit.semantic_ir import RequirementNode, Operator, ValueType


class CountryAliasTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.factory = live.LiveOperatorFactory(message="", session_id="fixture", profile="public", llm=None, history=[])
        self.rows = [
            {"country": "칠레", "country_code": "CL", "country_name_en": "Chile", "year": 2023, "value": 1},
            {"country": "칠레", "country_code": "CL", "country_name_en": "Chile", "year": 2024, "value": 2},
            {"country": "페루", "country_code": "PE", "country_name_en": "Peru", "year": 2024, "value": 3},
        ]

    def derive(self, rows, expected="Chile", operator="equals", field="country"):
        node = RequirementNode("filter", Operator.FILTER, args={"predicate": {"field": field, "operator": operator, "value": expected}})
        return execute_registered(self.factory, node, {"input": TypedResult.success(ValueType.FACT_SET, rows)})

    def test_same_country_multiple_years_and_all_namespaces(self):
        for alias in ("칠레", " CL ", "cHiLe"):
            with self.subTest(alias=alias):
                result = self.derive(self.rows, alias)
                self.assertEqual(result.status, ResultStatus.SUCCESS)
                self.assertEqual(result.value, self.rows[:2])
        self.assertEqual(self.derive(self.rows, "Chile", "not_equals").value, self.rows[2:])

    def test_ambiguous_alias_abstains_for_equals_and_not_equals(self):
        rows = self.rows + [{"country": "다른국가", "country_code": "XX", "country_name_en": "Chile"}]
        for operator in ("equals", "not_equals"):
            with self.subTest(operator=operator):
                result = self.derive(rows, operator=operator)
                self.assertEqual(result.status, ResultStatus.ABSTAINED)
                self.assertEqual(result.failure_reason, "country_alias_ambiguous")

    def test_cross_namespace_collision_also_abstains(self):
        rows = self.rows + [{"country": "CL", "country_code": "XX"}]
        self.assertEqual(self.derive(rows, "CL").failure_reason, "country_alias_ambiguous")
        self.assertEqual(self.derive(rows, "CL", field="country_code").value, self.rows[:2])

    def test_no_fuzzy_or_reporter_partner_alias_and_no_match(self):
        rows = self.rows + [{"reporter_country": "Chile", "partner_country": "Chile", "country_code": "XX"}]
        self.assertEqual(live._resolve_country_alias(rows, "Chile"), self.rows[:2])
        for value in ("Chi", "", "missing"):
            self.assertEqual(live._resolve_country_alias(rows, value), [])

    async def call_resource(self, rows, target):
        node = RequirementNode("retrieve", Operator.RETRIEVE, args={"domain": "production", "metric": "production_volume", "resource_country": target})
        source = TypedResult.success(ValueType.FACT_SET, rows)
        with patch.object(live, "retrieve_evidence", return_value=object()), patch.object(live, "_typed_from_retrieval", return_value=source):
            return await self.factory._call_action(node, "resource.rank", mineral="구리")

    async def test_resource_country_uses_same_resolution_and_keeps_years(self):
        result = await self.call_resource(self.rows, " CHILE ")
        self.assertEqual(result.status, ResultStatus.SUCCESS)
        self.assertEqual(result.value, self.rows[:2])

    async def test_resource_country_ambiguous_abstains_and_missing_is_empty(self):
        rows = self.rows + [{"country_code": "XX", "country_name_en": "Chile"}]
        result = await self.call_resource(rows, "Chile")
        self.assertEqual(result.status, ResultStatus.ABSTAINED)
        self.assertEqual(result.failure_reason, "country_alias_ambiguous")
        missing = await self.call_resource(self.rows, "missing")
        self.assertEqual(missing.status, ResultStatus.EMPTY)
        self.assertEqual(missing.failure_reason, "resource_country_unavailable")


if __name__ == "__main__":
    unittest.main()
