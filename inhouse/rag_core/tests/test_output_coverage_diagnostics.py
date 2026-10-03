"""Exact output diagnostics and existing semantic-wrapper boundaries; no execution."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from inhouse.rag_core.ragkit.output_coverage import (
    OutputCoverageDiagnostic, diagnose_output_coverage,
)
from inhouse.rag_core.ragkit.semantic_capabilities import (
    CAPABILITY_ARGUMENTS, produced_outputs, validate_requested_outputs,
)
from inhouse.rag_core.ragkit.semantic_intent import (
    SemanticPlan, SemanticRequirement, SemanticResolutionError,
    parse_and_resolve, resolve_semantic_plan,
)
from inhouse.rag_core.ragkit.semantic_ir import ValueType
from inhouse.rag_core.ragkit.semantic_v2 import (
    RequestedOutput, SemanticRequirementPlanV2, validate_output_coverage,
)


@pytest.mark.parametrize("required,produced,covered,missing,status", [
    ([], [], set(), (), "COMPLETE"),
    ([], ["extra"], set(), (), "COMPLETE"),
    (["a"], ["a"], {"a"}, (), "COMPLETE"),
    (["a"], ["a", "extra"], {"a"}, (), "COMPLETE"),
    (["b", "a", "b"], ["a", "a"], {"a"}, ("b",), "PARTIAL"),
    (["b", "a"], [], set(), ("a", "b"), "MISSING"),
    (["b", "a"], ["other"], set(), ("a", "b"), "MISSING"),
    ([""], [""], {""}, (), "COMPLETE"),
    ([""], [], set(), ("",), "MISSING"),
])
def test_exact_set_coverage(required, produced, covered, missing, status):
    result = diagnose_output_coverage(required, produced)
    assert isinstance(result, OutputCoverageDiagnostic)
    assert result.required == frozenset(required)
    assert result.produced == frozenset(produced)
    assert result.covered == frozenset(covered)
    assert all(isinstance(value, frozenset) for value in
               (result.required, result.produced, result.covered))
    assert result.missing == missing
    assert result.status == status
    assert result.known_providers == ()


@pytest.mark.parametrize("required,produced", [
    ("CountryShare", "countryshare"),
    ("CountryShare", "CountryShare "),
    (" CountryShare", "CountryShare"),
    ("CountryShare", "country_share"),
    ("current_price", "latest_price"),
    ("usage_info", "usage"),
    ("CountryShare", ValueType.FACT_SET.value),
    ("CountryShare", "share_percentage"),
])
def test_core_has_no_alias_case_whitespace_or_runtime_type_equivalence(required, produced):
    result = diagnose_output_coverage([required], [produced])
    assert result.missing == (required,)
    assert result.covered == frozenset()
    assert result.status == "MISSING"


def test_one_shot_iterables_are_snapshotted_and_diagnostic_is_frozen():
    result = diagnose_output_coverage(iter(["b", "a", "b"]), (x for x in ["a"]))
    assert result.required == frozenset({"a", "b"})
    assert result.produced == result.covered == frozenset({"a"})
    assert result.missing == ("b",)
    for name, value in (("required", frozenset()), ("produced", frozenset()),
                        ("missing", ()), ("known_providers", ())):
        with pytest.raises(FrozenInstanceError):
            setattr(result, name, value)


@pytest.mark.parametrize("spec", [
    {}, {"output_type": None}, {"output_type": "countryshare"},
    {"output_type": "CountryShare "}, {"output_type": ["CountryShare"]},
    {"output_fields": frozenset({"CountryShare"})},
    {"fields": ["CountryShare"]}, {"surface_metrics": frozenset({"CountryShare"})},
    {"output_type": ValueType.FACT_SET.value},
])
def test_provider_requires_exact_output_type_not_declared_fields_or_runtime_type(spec):
    result = diagnose_output_coverage(["CountryShare"], [], provider_specs={"candidate": spec})
    assert result.known_providers == (("CountryShare", ()),)
    assert result.missing == ("CountryShare",)
    assert result.status == "MISSING"


def test_providers_are_sorted_missing_only_and_do_not_complete_coverage():
    specs = {
        "z.provider": {"output_type": "B"},
        "covered.provider": {"output_type": "A"},
        "a.provider": {"output_type": "B"},
    }
    result = diagnose_output_coverage(["C", "B", "A"], ["A"], provider_specs=specs)
    assert result.known_providers == (("B", ("a.provider", "z.provider")), ("C", ()))
    assert result.required == frozenset({"A", "B", "C"})
    assert result.produced == result.covered == frozenset({"A"})
    assert result.missing == ("B", "C")
    assert result.status == "PARTIAL"
    assert diagnose_output_coverage(["A"], ["A"], provider_specs=specs).known_providers == ()


@pytest.mark.parametrize("providers,expected", [(None, ()), ({}, (("Missing", ()),))])
def test_optional_provider_diagnostics_are_distinct_from_empty_catalog(providers, expected):
    result = diagnose_output_coverage(["Missing"], [], provider_specs=providers)
    assert result.known_providers == expected
    assert result.missing == ("Missing",)


def test_real_catalog_country_share_provider_is_not_concentration_or_execution():
    before = deepcopy(CAPABILITY_ARGUMENTS)
    result = diagnose_output_coverage(
        ["CountryShare", "ConcentrationMetric"], [], provider_specs=CAPABILITY_ARGUMENTS,
    )
    assert result.known_providers == (
        ("ConcentrationMetric", ()), ("CountryShare", ("trade.country_rank",)),
    )
    assert result.missing == ("ConcentrationMetric", "CountryShare")
    assert result.produced == result.covered == frozenset()
    assert result.status == "MISSING"
    assert CAPABILITY_ARGUMENTS == before


def test_no_inputs_mutated_and_provider_discovery_never_calls_action():
    action = Mock(side_effect=AssertionError("diagnostics must not execute actions"))
    required, produced = ["B", "A", "B"], ["A"]
    specs = {"action": {"output_type": "B", "handler": action, "fields": ["B"]}}
    result = diagnose_output_coverage(required, produced, provider_specs=specs)
    assert required == ["B", "A", "B"] and produced == ["A"]
    assert specs == {"action": {"output_type": "B", "handler": action, "fields": ["B"]}}
    action.assert_not_called()
    required.append("later")
    produced.append("B")
    specs["action"]["output_type"] = "later"
    assert result.required == frozenset({"A", "B"})
    assert result.produced == frozenset({"A"})
    assert result.known_providers == (("B", ("action",)),)


@pytest.mark.parametrize("reverse", [False, True])
def test_to_dict_is_deterministic_json_shaped_and_detached(reverse):
    required, produced = ["z", "b", "a"], ["extra", "a"]
    specs = [("z.provider", {"output_type": "b"}), ("a.provider", {"output_type": "b"})]
    if reverse:
        required.reverse()
        produced.reverse()
        specs.reverse()
    result = diagnose_output_coverage(required, produced, provider_specs=dict(specs))
    expected = {
        "required": ["a", "b", "z"], "produced": ["a", "extra"],
        "covered": ["a"], "missing": ["b", "z"],
        "known_providers": {"b": ["a.provider", "z.provider"], "z": []},
        "status": "PARTIAL",
    }
    serialized = result.to_dict()
    assert serialized == expected
    assert list(serialized["known_providers"]) == ["b", "z"]
    for field in ("required", "produced", "covered", "missing"):
        serialized[field].append("changed")
    serialized["known_providers"]["b"].append("changed")
    serialized["known_providers"]["new"] = []
    assert result.to_dict() == expected


def test_default_to_dict_has_no_provider_or_action_payload():
    assert diagnose_output_coverage(["CountryShare"], []).to_dict() == {
        "required": ["CountryShare"], "produced": [], "covered": [],
        "missing": ["CountryShare"], "known_providers": {}, "status": "MISSING",
    }


@pytest.mark.parametrize("requested,expected", [
    ({"current_price"}, None), ({"latest_price"}, None),
    ({"current_price", "latest_price"}, None), (set(), None),
    ({"Current_Price"}, "requested_output_not_produced:Current_Price"),
    ({"current_price "}, "requested_output_not_produced:current_price "),
    ({"price"}, "requested_output_not_produced:price"),
    ({"z", "a"}, "requested_output_not_produced:a,z"),
])
def test_legacy_wrapper_owns_only_existing_current_price_alias(requested, expected):
    requirements = [SemanticRequirement(domain="price", metric="current", mineral="니켈")]
    before = deepcopy((requirements, requested))
    assert produced_outputs(requirements) == frozenset({"latest_price"})
    assert validate_requested_outputs(requirements, requested) == expected
    assert (requirements, requested) == before


@pytest.mark.parametrize("kind,expected", [
    (None, "requested_output_not_produced:date,inventory_series"),
    ("latest", "requested_output_not_produced:date,inventory_series"),
    ("trailing_months", None), ("range", None), ("calendar_year", None),
])
def test_legacy_bounded_inventory_produced_outputs_remain_authoritative(kind, expected):
    req = SimpleNamespace(domain="inventory", metric="latest", period={"kind": kind})
    assert validate_requested_outputs([req], {"inventory_series", "date"}) == expected
    assert {"latest_inventory", "inventory"} <= produced_outputs([req])


def test_legacy_catalog_type_and_allowed_fields_do_not_expand_produced_outputs():
    req = SemanticRequirement(domain="trade", metric="country_rank", mineral="니켈")
    assert "CountryShare" not in produced_outputs([req])
    assert "import_amount" not in produced_outputs([req])
    assert validate_requested_outputs([req], {"CountryShare", "import_amount"}) == (
        "requested_output_not_produced:CountryShare,import_amount"
    )


@pytest.mark.parametrize("names,produced,expected", [
    ([], {}, ()), (["b", "a", "b"], {}, ("a", "b")),
    (["a", "b"], {"one": {"a"}, "two": {"b", "extra"}}, ()),
    (["a", "b"], {"one": {"a"}}, ("b",)),
    (["a"], {"a": {"other"}}, ("a",)),
    (["current_price"], {"p": {"latest_price"}}, ("current_price",)),
    (["CountryShare"], {"p": {"country_share"}}, ("CountryShare",)),
    ([" A"], {"p": {"A"}}, (" A",)),
])
def test_v2_wrapper_uses_requested_names_and_flattened_values_only(names, produced, expected):
    plan = SemanticRequirementPlanV2(requested_outputs=[RequestedOutput(name=n) for n in names])
    before = deepcopy((plan, produced))
    assert validate_output_coverage(plan, produced) == expected
    assert (plan, produced) == before


def test_v2_requested_output_metadata_does_not_replace_name_or_constrain_source():
    plan = SemanticRequirementPlanV2(requested_outputs=[RequestedOutput(
        name="display", source_node="first", fields=["value"], aliases={"value": "display"},
    )])
    assert validate_output_coverage(plan, {"first": {"value"}}) == ("display",)
    assert validate_output_coverage(plan, {"other": {"display"}}) == ()


@pytest.mark.parametrize("name,canonical", [("usage_info", "usage"), ("latest_nickel_price", "current_price")])
def test_v2_existing_model_alias_remains_outside_diagnostic_core(name, canonical):
    plan = SemanticRequirementPlanV2(requested_outputs=[RequestedOutput(name=name)])
    assert plan.requested_outputs[0].name == canonical
    assert validate_output_coverage(plan, {"source": {canonical}}) == ()
    assert diagnose_output_coverage([name], [canonical]).missing == (name,)


@pytest.mark.parametrize("status,item_reason,requested,expected", [
    ("unresolved", None, {"z", "a"}, "requested_output_not_produced:a,z"),
    ("resolved", "item unresolved", {"z"}, "requested_output_not_produced:z"),
    ("unresolved", None, set(), "plan unresolved"),
    ("resolved", "item unresolved", set(), "plan unresolved"),
    ("resolved", None, {"z"}, "requested_output_not_produced:z"),
    ("resolved", None, set(), "unsupported semantic capability: concept/current"),
])
def test_resolver_and_parser_preserve_failure_order_without_action_plan(
    monkeypatch, status, item_reason, requested, expected,
):
    monkeypatch.delenv("RAG_PARSER_TRACE_PATH", raising=False)
    plan = SemanticPlan(
        requirements=[SemanticRequirement(domain="concept", metric="current", unresolved_reason=item_reason)],
        requested_outputs=requested, status=status, unresolved_reason="plan unresolved",
    )
    with pytest.raises(SemanticResolutionError) as error:
        resolve_semantic_plan(plan)
    assert str(error.value) == expected
    llm = Mock()
    llm.invoke.return_value = SimpleNamespace(output=plan)
    result = parse_and_resolve("", llm)
    assert result.reason == "SemanticResolutionError:" + expected
    assert result.intent_plan is None and result.action_plan is None
    llm.invoke.assert_called_once()


@pytest.mark.parametrize("payload", [None, {}, {"requirements": []}, "unknown"])
def test_parser_unknown_payload_still_fails_typed_boundary(monkeypatch, payload):
    monkeypatch.delenv("RAG_PARSER_TRACE_PATH", raising=False)
    llm = Mock()
    llm.invoke.return_value = SimpleNamespace(output=payload)
    result = parse_and_resolve("", llm)
    assert result.reason == "SemanticResolutionError:semantic_output_schema_invalid"
    assert result.semantic_plan is None
    assert result.intent_plan is None and result.action_plan is None


@pytest.mark.parametrize("with_requirement,expected", [
    (False, "unsupported_request:UNKNOWN_CAPABILITY"),
    (True, "unsupported_request_with_requirements"),
])
def test_parser_unsupported_request_gate_still_precedes_output_coverage(
    monkeypatch, with_requirement, expected,
):
    monkeypatch.delenv("RAG_PARSER_TRACE_PATH", raising=False)
    plan = SemanticPlan(
        request_class="UNSUPPORTED_REQUEST", unsupported_reason="UNKNOWN_CAPABILITY",
        requested_outputs={"not_produced"},
        requirements=[SemanticRequirement(domain="concept", metric="current")] if with_requirement else [],
    )
    llm = Mock()
    llm.invoke.return_value = SimpleNamespace(output=plan)
    result = parse_and_resolve("", llm)
    assert result.reason == "SemanticResolutionError:" + expected
    assert result.intent_plan is None and result.action_plan is None
