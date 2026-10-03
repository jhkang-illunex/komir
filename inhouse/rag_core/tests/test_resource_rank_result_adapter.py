"""Characterize resource physical-column renaming without repairing semantics."""

from copy import deepcopy
from unittest.mock import patch

import pytest

from inhouse.rag_core.ragkit import live_multihop as live
from inhouse.rag_core.ragkit import resource_rank_result_adapter as adapter
from inhouse.rag_core.ragkit.action_contract import ActionCall, ActionSlots, Period
from inhouse.rag_core.ragkit.action_results import ActionResult, RetrievalResult
from inhouse.rag_core.ragkit.pipe_runtime import ResultStatus
from inhouse.rag_core.ragkit.semantic_ir import ValueType
from inhouse.rag_core.retrieval.evidence import Evidence


METRICS = [("production", "production_volume"), ("reserves", "reserves_volume")]


@pytest.mark.parametrize("metric,field", METRICS)
@pytest.mark.parametrize("key", ["total", "TOTAL", "ToTaL(label(nested))", "총계", "총계(톤)"])
def test_total_keys_are_renamed_not_copied(metric, field, key):
    row = {"country": "A", key: "1,200", "share": "90%"}
    result = adapter.canonicalize_resource_rank_rows([row], metric)
    assert result == [{"country": "A", field: "1,200", "share": "90%"}]
    assert key not in result[0] and row[key] == "1,200"
    assert "value" not in result[0]


@pytest.mark.parametrize("key", [" total", "total ", "total (tonnes)", " 총계", "총계 (톤)",
                                  "subtotal", "total[tonnes]", "total_volume"])
def test_physical_key_matching_does_not_strip_or_broaden_aliases(key):
    row = {key: 3}
    result = adapter.canonicalize_resource_rank_rows([row], "production")
    assert result == [row] and result[0] is not row
    assert "production_volume" not in result[0]


@pytest.mark.parametrize("metric,field", METRICS)
@pytest.mark.parametrize("order,expected", [
    (("canonical", "total", "총계"), 3),
    (("total", "총계", "canonical"), 1),
    (("총계", "canonical", "total"), 2),
    (("total", "canonical", "총계"), 3),
])
def test_collisions_use_last_insertion_value_even_over_existing_canonical(metric, field, order, expected):
    entries = {"canonical": (field, 1), "total": ("TOTAL(tonnes)", 2), "총계": ("총계", 3)}
    row = dict([("country", "A"), *(entries[key] for key in order), ("tail", "kept")])
    before = deepcopy(row)
    result = adapter.canonicalize_resource_rank_rows([row], metric)[0]
    assert result == {"country": "A", field: expected, "tail": "kept"}
    assert list(result) == ["country", field, "tail"] and row == before


@pytest.mark.parametrize("metric,field", METRICS)
@pytest.mark.parametrize("value", [None, "", "invalid", "NaN", "Infinity", True, -1])
def test_values_are_not_parsed_validated_or_filtered(metric, field, value):
    rows = [{"total": value}, {field: value}]
    result = adapter.canonicalize_resource_rank_rows(rows, metric)
    assert len(result) == 2
    assert result[0][field] is value and result[1][field] is value


@pytest.mark.parametrize("metric", [None, "", "PRODUCTION", "Production", "production ",
                                     "RESERVES", " reserves", "production_volume", "import_amount", 0])
def test_unsupported_metric_preserves_exact_input_identity_without_inspection(metric):
    rows = [{1: "non-string-key", "total": 9}]
    result = adapter.canonicalize_resource_rank_rows(rows, metric)
    assert result is rows and result[0] is rows[0]


@pytest.mark.parametrize("metric,field", METRICS)
def test_supported_rows_are_shallow_copies_in_original_order(metric, field):
    nested = {"keep": True}
    row = {"country": "B", "total": 5, "nested": nested}
    rows = [row, {"country": "A"}, row]
    before = deepcopy(rows)
    result = adapter.canonicalize_resource_rank_rows(rows, metric)
    assert rows == before and result is not rows
    assert [item["country"] for item in result] == ["B", "A", "B"]
    assert all(new is not old for new, old in zip(result, rows))
    assert result[0] is not result[2] and result[0]["nested"] is nested
    assert result[0][field] == result[2][field] == 5 and field not in result[1]
    empty = []
    assert adapter.canonicalize_resource_rank_rows(empty, metric) == []
    assert adapter.canonicalize_resource_rank_rows(empty, metric) is not empty


@pytest.mark.parametrize("key", [1, None, ("total",), True])
def test_non_string_keys_keep_existing_attribute_error(key):
    rows = [{key: 5}]
    with pytest.raises(AttributeError, match="split"):
        adapter.canonicalize_resource_rank_rows(rows, "production")
    assert rows == [{key: 5}]


@pytest.mark.parametrize("metric", [[], {}, {"production"}])
def test_unhashable_metric_raises_even_with_empty_rows(metric):
    with pytest.raises(TypeError, match="unhashable"):
        adapter.canonicalize_resource_rank_rows([], metric)


@pytest.mark.parametrize("keys,expected", [(["total"], 1), (["총계"], 2), (["총계", "total"], 1)])
def test_retained_fallback_prefers_exact_total_before_korean_alias(keys, expected):
    # Ordinary string aliases rename earlier; a str subclass exposes the legacy fallback.
    class UnmatchedBase(str):
        def split(self, *args, **kwargs):
            return ["not-a-total-base"]

    values = {"total": 1, "총계": 2}
    row = {UnmatchedBase(key): values[key] for key in keys}
    result = adapter.canonicalize_resource_rank_rows([row], "production")[0]
    assert result["production_volume"] == expected
    assert all(result[key] == values[key] for key in keys)
    assert "production_volume" not in row


def action(metric="production", action_id="resource.rank"):
    return ActionCall(requirement_id="resource", action_id=action_id,
                      slots=ActionSlots(metric=metric, mineral="니켈", period=Period(kind="calendar_year", calendar_year=2024)))


def evidence(text, name="source", source_id="physical", unit="t"):
    return Evidence("structured", name, "fixture", text, unit=unit, source_id=source_id)


def raw_result(call, items, status="success", reason=None, action_evidence=None):
    item = ActionResult(call.requirement_id, call.action_id, call.slots, status,
                        items if action_evidence is None else action_evidence,
                        warnings=["existing_warning"], failure_reason=reason)
    return RetrievalResult(None, [item], items, ["top_level_warning"])


@pytest.mark.parametrize("metric,field", METRICS)
def test_raw_typed_common_envelope_value_fill_and_entity_normalization(metric, field):
    call = action(metric)
    primary = evidence("| 국가명 | total(톤) | crtr_yr |\n| --- | --- | --- |\n| B | 12 | 2024 |\n| A | bad | 2024 |")
    extra = evidence("No table, still evidence.", "supplement", None)
    raw = raw_result(call, [primary, extra, primary])
    before = deepcopy(raw)
    result = live._typed_from_retrieval(raw, call, input_entities=["Ni", "NiCkEl", "니켈"])
    assert result.status == ResultStatus.SUCCESS and result.sufficient and result.failure_reason is None
    assert result.result_type == ValueType.FACT_SET and result.metric == metric
    assert [row["country"] for row in result.value] == ["B", "A", "B", "A"]
    assert [row[field] for row in result.value] == ["12", "bad", "12", "bad"]
    assert [row["value"] for row in result.value] == ["12", "bad", "12", "bad"]
    assert all("total(톤)" not in row for row in result.value)
    assert result.entity == ("Ni", "니켈") and result.unit == "톤"
    assert result.period == call.slots.period.model_dump(mode="json")
    assert result.source == ("source", "supplement")
    assert result.provenance == ("resource:physical", "resource:supplement")
    assert result.evidence == (primary, extra, primary) and result.evidence[0] is primary
    assert result.warnings == ("existing_warning",) and raw == before


@pytest.mark.parametrize("metric,field", METRICS)
@pytest.mark.parametrize("canonical_first", [False, True])
def test_raw_existing_value_fill_precedes_resource_collision(metric, field, canonical_first):
    call = action(metric)
    header, values = (f"{field} | total", "5 | 9") if canonical_first else (f"total | {field}", "9 | 5")
    item = evidence(f"| {header} |\n| --- | --- |\n| {values} |")
    result = live._typed_from_retrieval(raw_result(call, [item]), call, input_entities=[])
    assert result.status == ResultStatus.SUCCESS
    assert result.value[0][field] == ("9" if canonical_first else "5")
    # Common canonicalization already filled value=5; no reconciliation follows rename.
    assert result.value[0]["value"] == "5"


@pytest.mark.parametrize("existing", [None, "", "other", 0])
def test_raw_existing_value_is_not_replaced_even_when_null(existing):
    call = action()
    rows = [{"total": 9, "value": existing}]
    with patch.object(live, "_rows", return_value=rows):
        result = live._typed_from_retrieval(raw_result(call, [evidence("fixture")]), call, input_entities=[])
    assert result.status == ResultStatus.SUCCESS
    assert result.value == [{"production_volume": 9, "value": existing}]
    assert rows == [{"total": 9, "value": existing}]


@pytest.mark.parametrize("metric", [None, "import_amount"])
def test_raw_unsupported_resource_metric_does_not_infer_measure_or_value(metric):
    call = action(metric)
    item = evidence("| total |\n| --- |\n| 10 |")
    result = live._typed_from_retrieval(raw_result(call, [item]), call, input_entities=[])
    assert result.status == ResultStatus.SUCCESS and result.result_type == ValueType.FACT_SET
    assert result.metric == metric and result.value == [{"total": "10"}]


@pytest.mark.parametrize("status,reason,expected", [
    ("validation_failed", "resource_population_unit_unverified:private", "resource_population_unit_unverified"),
    ("validation_failed", "internal:private", "retrieval unavailable: validation_failed"),
    ("no_data", None, "retrieval unavailable: no_data"),
    ("source_unavailable", None, "retrieval unavailable: source_unavailable"),
])
def test_raw_failure_preserves_evidence_without_success_metadata(status, reason, expected):
    call = action()
    item = evidence("| total |\n| --- |\n| 10 |")
    result = live._typed_from_retrieval(raw_result(call, [item], status, reason), call, input_entities=["Ni"])
    assert result.status == ResultStatus.EMPTY and not result.sufficient and result.value is None
    assert result.result_type == ValueType.FACT_SET and result.failure_reason == expected
    assert result.evidence == (item,) and result.warnings == ("existing_warning",)
    assert result.source == result.provenance == result.entity == ()
    assert result.metric is None and result.unit is None and result.period is None


@pytest.mark.parametrize("has_evidence", [False, True])
def test_raw_no_rows_and_no_evidence_keep_distinct_outcomes(has_evidence):
    call = action()
    items = [evidence("No markdown table.")] if has_evidence else []
    result = live._typed_from_retrieval(raw_result(call, items), call, input_entities=[])
    assert result.result_type == ValueType.FACT_SET and result.evidence == tuple(items)
    if has_evidence:
        assert result.status == ResultStatus.SUCCESS and result.value == items
        assert result.provenance == ("resource:physical",)
    else:
        assert result.status == ResultStatus.EMPTY and result.value is None
        assert result.failure_reason == "retrieval unavailable: success"


@pytest.mark.parametrize("action_id", ["trade.monthly", "document.retrieve"])
def test_non_resource_action_does_not_delegate(action_id):
    call = action(action_id=action_id)
    item = evidence("| total |\n| --- |\n| 10 |")
    with patch.object(adapter, "canonicalize_resource_rank_rows", side_effect=AssertionError("wrong action gate")) as helper:
        result = live._typed_from_retrieval(raw_result(call, [item]), call, input_entities=[])
    helper.assert_not_called()
    assert result.status == ResultStatus.SUCCESS and result.value == [{"total": "10"}]
